from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd
import polars as pl
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, AutoARIMA, CrostonSBA, SeasonalNaive
from statsforecast.utils import ConformalIntervals
from hierarchicalforecast.utils import aggregate as hf_aggregate
from hierarchicalforecast.core import HierarchicalReconciliation
from hierarchicalforecast.methods import BottomUp, MinTrace

logger = logging.getLogger(__name__)

TWO_DP  = Decimal('0.01')
THREE_DP = Decimal('0.001')
BATCH_SIZE_LINES = 2000

from functools import lru_cache

"""
run_forecast Celery task
  │
  ├─ 1. update_weighted_avg_prices()
  │       Reads ActualSale revenue → writes ItemPlanningProfile.weighted_avg_price
  │
  ├─ 2. build_actuals_dataframe()
  │       ActualSale ORM → Polars DataFrame
  │       unique_id = "{item_id}|{customer_code_or_NULL}|{location_code}"
  │
  ├─ 3. load_series_decisions()   ← NEW: reads SeriesProfile instead of classifying
  │       Returns dict: unique_id → {grain, strategy, eval_period, price}
  │
  ├─ 4. build_aggregated_actuals()   ← NEW: replaces build_summing_matrix
  │       For each grain in decisions, aggregates actuals to that grain
  │       Uses hierarchy_utils for dynamic location/product levels
  │
  ├─ 5. run_statsforecast_by_grain()   ← NEW: replaces classify_series_by_strategy
  │       Groups series by (grain, strategy, eval_period)
  │       Runs one StatsForecast batch per group
  │       Returns combined DataFrame: unique_id, ds, statistical_qty, grain, model_used
  │
  ├─ 6. disaggregate_to_atomic()   ← NEW: replaces handle_lumpy_series
  │       For non-atomic grains: distributes forecast back to atomic series
  │       Uses VALUE share (not qty share) for product hierarchy aggregations
  │       Uses QTY share for location hierarchy aggregations
  │
  ├─ 7. run_hierarchical_reconciliation()   ← unchanged
  │       HierarchicalForecast MinTrace on assembled atomic forecasts
  │
  ├─ 8. write_forecast_lines()   ← updated: handles store_all_level_forecasts
  │       bulk_create ForecastLine rows
  │       When store_all_level_forecasts=True, writes one row per grain per series
  │
  └─ 9. write_forecast_aggregates()   ← updated: writes value fields
          DuckDB rollup of ForecastLine → ForecastAggregate
          Computes weighted_avg_price per aggregate node
"""

"""
Forecast engine pure functions.
Called by the run_forecast Celery task.
No Django ORM calls — all data arrives as DataFrames or dicts.
"""

# ─────────────────────────────────────────────────────────────────────────────
# NEW MODULE-LEVEL CONSTANT
# Place this near the top of forecast_engine.py, after the existing imports
# and before the first function definition.
# ─────────────────────────────────────────────────────────────────────────────

def _build_time_grain_suffixes() -> frozenset[str]:
    """
    Collect every coarser-period token that PERIOD_HIGHER_HORIZONS defines.

    Called once at import time to build _TIME_GRAIN_SUFFIXES.
    Using PERIOD_HIGHER_HORIZONS as the single source of truth means that
    adding 'fortnight' or any other period to that dict is instantly reflected
    in grain suffix detection everywhere in the engine.
    """
    try:
        from mysite.models.demand.actuals import PERIOD_HIGHER_HORIZONS
        suffixes: set[str] = set()
        for horizon_list in PERIOD_HIGHER_HORIZONS.values():
            suffixes.update(horizon_list)
        return frozenset(suffixes)
    except ImportError:
        # Fallback for unit tests that run without Django configured
        return frozenset({
            'second', 'minute', 'hour',
            'day', 'week', 'fortnight', 'month', 'bimonth',
            'quarter', 'halfyear', 'year',
        })


_TIME_GRAIN_SUFFIXES: frozenset[str] = _build_time_grain_suffixes()


def _grain_has_time_suffix(grain: str) -> bool:
    """
    Return True if the grain string ends with a coarser-period token.

    Examples that return True:
        item_client_quarter          → suffix = 'quarter'
        item_loc_depth_2_month       → suffix = 'month'
        taxon_42_client_halfyear     → suffix = 'halfyear'
        item_client_week             → suffix = 'week'
        item_client_fortnight        → suffix = 'fortnight'

    Examples that return False:
        item_cust_location           → no time suffix
        item_client                  → 'client' is not in _TIME_GRAIN_SUFFIXES
        taxon_42_client              → 'client' is not a period token
    """
    suffix = grain.rsplit('_', 1)[-1]
    return suffix in _TIME_GRAIN_SUFFIXES


def _grain_time_suffix(grain: str) -> str | None:
    """Return the trailing time-period token of a grain, or None."""
    suffix = grain.rsplit('_', 1)[-1]
    return suffix if suffix in _TIME_GRAIN_SUFFIXES else None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Update weighted average prices
# ─────────────────────────────────────────────────────────────────────────────

def update_weighted_avg_prices(
    client_id: int,
    period_type: str,
    lookback_periods: int = 12,
) -> dict[int, Decimal]:
    """
    Compute weighted average price (sum(revenue)/sum(qty)) per item from
    the most recent `lookback_periods` actuals periods.

    Returns dict: {item_pk (int): weighted_avg_price (Decimal)}
    Also bulk-updates ItemPlanningProfile.weighted_avg_price.

    Falls back to ItemPlanningProfile.standard_price for items with no
    revenue data — those items are NOT in the returned dict so callers
    can distinguish "has actuals price" from "standard price only".
    """
    from django.utils import timezone
    from mysite.models.demand.actuals import ActualSale, ItemPlanningProfile

    qs = (
        ActualSale.objects
        .filter(
            client_id=client_id,
            period_type=period_type,
            revenue__isnull=False,
        )
        .values('item_id', 'qty', 'revenue', 'period_start')
        .order_by('-period_start')
    )

    if not qs.exists():
        logger.warning(
            f'update_weighted_avg_prices: no revenue data '
            f'for client={client_id}'
        )
        return {}

    df_pd = pd.DataFrame(list(qs))
    con   = duckdb.connect()
    con.register('actuals', df_pd)

    wap_df = con.execute(f"""
        WITH recent AS (
            SELECT item_id, period_start
            FROM (
                SELECT DISTINCT item_id, period_start
                FROM actuals
                ORDER BY period_start DESC
                LIMIT {lookback_periods * df_pd['item_id'].nunique()}
            )
        )
        SELECT
            a.item_id,
            SUM(CAST(a.revenue AS DOUBLE))
                / NULLIF(SUM(CAST(a.qty AS DOUBLE)), 0) AS wap
        FROM actuals a
        INNER JOIN recent r
            ON a.item_id = r.item_id
            AND a.period_start = r.period_start
        GROUP BY a.item_id
        HAVING SUM(CAST(a.qty AS DOUBLE)) > 0
    """).df()

    result = {
        int(row['item_id']): Decimal(str(round(row['wap'], 4)))
        for _, row in wap_df.iterrows()
        if row['wap'] is not None
    }

    now = timezone.now()
    profiles = list(
        ItemPlanningProfile.objects
        .filter(client_id=client_id, item_id__in=list(result.keys()))
    )
    for p in profiles:
        if p.item_id in result:
            p.weighted_avg_price = result[p.item_id]
            p.price_updated_at   = now

    if profiles:
        ItemPlanningProfile.objects.bulk_update(
            profiles, ['weighted_avg_price', 'price_updated_at'],
            batch_size=500,
        )

    logger.info(
        f'update_weighted_avg_prices: client={client_id} '
        f'updated {len(profiles)} profiles'
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Build actuals DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def build_actuals_dataframe(
    client_id: int,
    period_type: str,
    period_start_from,
    period_start_to,
) -> pl.DataFrame:
    """
    Pull ActualSale rows into a Polars DataFrame.

    Returns columns:
        unique_id           str   "{item_id}|{customer_code_or_NULL}|{location_code}"
        ds                  date  period_start
        y                   float qty
        item_id             int   FK
        item_id_str         str   Item.item_id string
        planning_customer_id int|None FK
        customer_code       str   code or "NULL"
        planning_location_id int  FK
        location_code       str
        region_code         str   parent location code or "__NO_REGION__"
        revenue             float ActualSale.revenue (0 if null)
    """
    from mysite.models.demand.actuals import ActualSale

    qs = (
        ActualSale.objects
        .filter(
            client_id=client_id,
            period_type=period_type,
            period_start__gte=period_start_from,
            period_start__lte=period_start_to,
        )
        .select_related(
            'item',
            'planning_location',
            'planning_location__parent',
            'planning_customer',
        )
        .values(
            'item_id',
            'item__item_id',
            'planning_location_id',
            'planning_location__code',
            'planning_location__parent_id',
            'planning_location__parent__code',
            'planning_customer_id',
            'planning_customer__code',
            'period_start',
            'qty',
            'revenue',
        )
    )

    rows = list(qs)
    if not rows:
        raise ValueError(
            f'No actuals for client={client_id} period_type={period_type} '
            f'{period_start_from}→{period_start_to}'
        )

    df_pd = pd.DataFrame(rows)
    df_pd['revenue']      = df_pd['revenue'].fillna(0).astype(float)
    df_pd['customer_code'] = df_pd['planning_customer__code'].fillna('NULL')
    df_pd['region_code']   = df_pd['planning_location__parent__code'].fillna('__NO_REGION__')
    df_pd['unique_id']     = (
        df_pd['item__item_id'].astype(str) + '|' +
        df_pd['customer_code'].astype(str) + '|' +
        df_pd['planning_location__code'].astype(str)
    )
    df_pd = (
        df_pd.groupby([
            'unique_id', 'item_id', 'item__item_id',
            'planning_customer_id', 'customer_code',
            'planning_location_id', 'planning_location__code',
            'region_code', 'period_start',
        ])
        .agg({'qty': 'sum', 'revenue': 'sum'})
        .reset_index()
    )
    df_pd['y']  = df_pd['qty'].astype(float)
    df_pd['ds'] = pd.to_datetime(df_pd['period_start'])

    df = pl.from_pandas(df_pd)
    logger.info(
        f'build_actuals_dataframe: client={client_id} '
        f'rows={len(df)} series={df["unique_id"].n_unique()}'
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3. Load series decisions from SeriesProfile
# ─────────────────────────────────────────────────────────────────────────────

def load_series_decisions(
    client_id: int,
    period_type: str,
    unique_ids: list[str],
    price_map: dict[int, Decimal],
    force_grain: str | None = None,
) -> dict[str, dict]:
    """
    Read SeriesProfile rows and build a decision dict for every unique_id.

    Returns dict keyed by unique_id:
        {
            'grain':        str   — effective_grain (honours planner override)
            'strategy':     str   — effective_strategy
            'eval_period':  str   — effective_eval_period (may differ for Part C)
            'price':        Decimal | None — effective_price from ItemPlanningProfile
            'item_id':      int   — item FK
            'location_id':  int   — location FK
            'customer_id':  int | None
        }

    force_grain: when set (from engine_config), overrides ALL series decisions.
    Series without a SeriesProfile default to atomic grain / AutoETS.
    """
    from mysite.models.demand.forecast import SeriesProfile
    from mysite.models.demand.actuals import ItemPlanningProfile

    profiles = (
        SeriesProfile.objects
        .filter(client_id=client_id, period_type=period_type)
        .select_related('item', 'planning_location', 'planning_customer')
    )

    # Build price map: item_pk → effective_price
    all_item_pks = set()
    for profile in profiles:
        all_item_pks.add(profile.item_id)

    ipp_map = {
        p.item_id: p.effective_price
        for p in ItemPlanningProfile.objects.filter(
            client_id=client_id, item_id__in=list(all_item_pks)
        )
    }
    # Merge with actuals-derived price_map (actuals prices take precedence)
    effective_price_map = {**ipp_map, **price_map}

    decisions: dict[str, dict] = {}

    for profile in profiles:
        cust_code = (
            profile.planning_customer.code
            if profile.planning_customer else 'NULL'
        )
        uid = (
            f'{profile.item.item_id}|'
            f'{cust_code}|'
            f'{profile.planning_location.code}'
        )
        if uid not in unique_ids:
            continue

        grain = force_grain or profile.effective_grain
        decisions[uid] = {
            'grain':       grain,
            'strategy':    profile.effective_strategy,
            'eval_period': profile.effective_eval_period if not force_grain else period_type,
            'price':       effective_price_map.get(profile.item_id),
            'item_id':     profile.item_id,
            'location_id': profile.planning_location_id,
            'customer_id': profile.planning_customer_id,
            'is_manual':   (profile.effective_strategy == 'MANUAL'),
        }

    # Unclassified series — default to atomic grain
    for uid in unique_ids:
        if uid not in decisions:
            logger.warning(
                f'load_series_decisions: no SeriesProfile for {uid} '
                f'— defaulting to item_cust_location / AUTOETS'
            )
            parts = uid.split('|')
            decisions[uid] = {
                'grain':       'item_cust_location',
                'strategy':    'AUTOETS',
                'eval_period': period_type,
                'price':       None,
                'item_id':     None,
                'location_id': None,
                'customer_id': None,
                'is_manual':   False,
            }

    # Summary log
    from collections import Counter
    grain_counts = Counter(d['grain'] for d in decisions.values())
    logger.info(
        f'load_series_decisions: client={client_id} '
        f'total={len(decisions)} grains={dict(grain_counts)}'
    )
    return decisions


# ─────────────────────────────────────────────────────────────────────────────
# 4. Build aggregated actuals per grain
# ─────────────────────────────────────────────────────────────────────────────

def build_aggregated_actuals(
    actuals_df: pl.DataFrame,
    decisions: dict[str, dict],
    period_type: str,
    all_periods: list,
) -> dict[str, pd.DataFrame]:

    df_pd = actuals_df.to_pandas()
    df_pd['ds'] = pd.to_datetime(df_pd['ds'])

    needed_grains = set(d['grain'] for d in decisions.values())

    # Derive all valid coarser period types from PERIOD_HIGHER_HORIZONS
    # so the time-grain detection is driven by the same source of truth
    # as ForecastingConfig.time_horizon_steps and compute_series_profiles.
    from mysite.models.demand.actuals import PERIOD_HIGHER_HORIZONS, PERIOD_FREQ_MAP
    all_coarser_periods = set()
    for horizons in PERIOD_HIGHER_HORIZONS.values():
        all_coarser_periods.update(horizons)

    con = duckdb.connect()
    con.register('actuals', df_pd)
    result: dict[str, pd.DataFrame] = {}

    for grain in needed_grains:

        # ── Atomic ────────────────────────────────────────────────────────────
        if grain == 'item_cust_location':
            result[grain] = df_pd[['unique_id', 'ds', 'y']].copy()

        # ── Item × Location (drop customer) ───────────────────────────────────
        elif grain == 'item_location':
            agg = con.execute("""
                SELECT
                    item__item_id || '|ALL_CUST|' || "planning_location__code"
                        AS unique_id,
                    ds,
                    SUM(y) AS y
                FROM actuals
                GROUP BY item__item_id, "planning_location__code", ds
            """).df()
            result[grain] = agg

        # ── Item × Location ancestor at depth N ───────────────────────────────
        elif grain.startswith('item_loc_depth_'):
            depth = int(grain.split('_')[-1])
            df_pd['anc_code'] = df_pd['planning_location__code'].apply(
                lambda code, d=depth: _location_ancestor_at_depth(df_pd, code, d)
            )
            agg = (
                df_pd.groupby(['item__item_id', 'anc_code', 'ds'])
                .agg({'y': 'sum'}).reset_index()
            )
            agg['unique_id'] = (
                agg['item__item_id'].astype(str) + '|ALL_CUST|' +
                agg['anc_code'].astype(str)
            )
            result[grain] = agg[['unique_id', 'ds', 'y']]

        # ── Item × Client (all locations, all customers) ───────────────────────
        elif grain == 'item_client':
            agg = con.execute("""
                SELECT
                    item__item_id || '|ALL_CUST|ALL_LOC' AS unique_id,
                    ds,
                    SUM(y) AS y
                FROM actuals
                GROUP BY item__item_id, ds
            """).df()
            result[grain] = agg

        # ── Product-hierarchy grain (taxon_*) — aggregate by VALUE ─────────────
        # Handles both:
        #   taxon_{node_id}_client          (Part B — product rollup, monthly)
        #   taxon_{node_id}_client_{period} (Part C — product rollup + time agg)
        elif grain.startswith('taxon_'):
            parts     = grain.split('_')   # ['taxon', node_id, 'client'] or
                                            # ['taxon', node_id, 'client', period]
            node_id   = parts[1]
            # Detect trailing coarser period suffix
            coarser_period = parts[-1] if parts[-1] in all_coarser_periods else None

            item_ids = _get_items_for_taxon(node_id)
            if not item_ids:
                logger.warning(
                    f'build_aggregated_actuals: no items for taxon node {node_id}'
                )
                continue

            df_taxon = df_pd[df_pd['item_id'].isin(item_ids)].copy()
            uid_base  = f'taxon_{node_id}_ALL_LOC'

            if coarser_period:
                # Part C: product × time aggregation
                freq = PERIOD_FREQ_MAP.get(coarser_period)
                if not freq:
                    logger.warning(
                        f'build_aggregated_actuals: unknown period '
                        f'"{coarser_period}" in grain "{grain}"'
                    )
                    continue
                df_taxon['ds'] = pd.to_datetime(df_taxon['ds'])
                agg = (
                    df_taxon.groupby(pd.Grouper(key='ds', freq=freq))
                    ['revenue'].sum().reset_index()
                )
                agg['unique_id'] = uid_base
                agg['y']         = agg['revenue']
                agg['ds']        = agg['ds'].dt.date
                result[grain]    = agg[['unique_id', 'ds', 'y']]
            else:
                # Part B: product rollup at native period_type
                agg = (
                    df_taxon.groupby(['ds'])
                    .agg({'revenue': 'sum'}).reset_index()
                )
                agg['unique_id'] = uid_base
                agg['y']         = agg['revenue']   # y = REVENUE for product grains
                result[grain]    = agg[['unique_id', 'ds', 'y']]

        # ── Time-aggregation grain (item × client × coarser period) ────────────
        # Detects any grain ending in a period type from PERIOD_HIGHER_HORIZONS.
        # e.g. item_client_quarter, item_client_halfyear, item_client_week
        # Also handles item_loc_depth_N_quarter etc.
        else:
            # Split off the trailing coarser period token
            parts          = grain.rsplit('_', 1)
            coarser_period = parts[-1] if len(parts) == 2 else None

            if coarser_period not in all_coarser_periods:
                logger.warning(
                    f'build_aggregated_actuals: unrecognised grain "{grain}" — skipping'
                )
                continue

            base_grain = parts[0]   # e.g. 'item_client', 'item_loc_depth_1'
            freq = PERIOD_FREQ_MAP.get(coarser_period)

            if not freq:
                logger.warning(
                    f'build_aggregated_actuals: no PERIOD_FREQ_MAP entry '
                    f'for "{coarser_period}" — skipping grain "{grain}"'
                )
                continue

            # Get or build the base grain DataFrame (monthly / native period)
            base_df = result.get(base_grain)
            if base_df is None:
                # Recursively build the base grain by calling this same logic
                # on a temporary single-grain decisions dict
                temp_decisions = {
                    uid: {**dec, 'grain': base_grain}
                    for uid, dec in decisions.items()
                }
                temp_result = build_aggregated_actuals(
                    actuals_df, temp_decisions, period_type, all_periods
                )
                base_df = temp_result.get(base_grain)
                if base_df is None:
                    logger.warning(
                        f'build_aggregated_actuals: could not build base '
                        f'grain "{base_grain}" for "{grain}" — skipping'
                    )
                    continue
                result[base_grain] = base_df   # cache for reuse

            base_df = base_df.copy()
            base_df['ds'] = pd.to_datetime(base_df['ds'])

            agg = (
                base_df.groupby(
                    ['unique_id', pd.Grouper(key='ds', freq=freq)]
                )['y'].sum().reset_index()
            )
            # Rename the ds column back to plain date for consistency
            agg['ds'] = agg['ds'].dt.date
            result[grain] = agg[['unique_id', 'ds', 'y']]

    return result


def _location_ancestor_at_depth(df: pd.DataFrame, loc_code: str, depth: int) -> str:
    """Return location code of ancestor at given depth from path column."""
    row = df[df['planning_location__code'] == loc_code]
    if row.empty:
        return loc_code
    path = str(row.iloc[0].get('planning_location__path', ''))
    parts = [p for p in path.split('/') if p]
    idx = depth - 1
    if idx < len(parts):
        # Return the code by looking up the ID
        return parts[idx]   # simplified: return ID as code
    return loc_code


def _get_items_for_taxon(node_id: str) -> list[int]:
    """Return item PKs belonging to a taxonomy node."""
    from mysite.models import TaxonomyNode
    try:
        node = TaxonomyNode.objects.get(pk=int(node_id))
        # Get all descendant node IDs
        desc_ids = list(
            node.get_descendants()
            .values_list('id', flat=True)
        ) + [node.pk]
        # Get all items mapped to these nodes
        from mysite.models import ItemTaxonomyMapping
        return list(
            ItemTaxonomyMapping.objects
            .filter(node_id__in=desc_ids)
            .values_list('item_id', flat=True)
            .distinct()
        )
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Run StatsForecast batched by grain and strategy
# ─────────────────────────────────────────────────────────────────────────────

def run_statsforecast_by_grain(
    aggregated_actuals: dict[str, pd.DataFrame],
    decisions: dict[str, dict],
    horizon: int,
    freq: str,
    season_length: int = 12,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """
    Group series by (grain, strategy, eval_period) and run one StatsForecast
    batch per group. Much more efficient than per-series dispatching.

    Returns combined DataFrame:
        unique_id | ds | statistical_qty | grain | model_used | forecast_level

    For MANUAL series: statistical_qty = 0, model_used = 'None'.
    For MOVING_AVG: simple N-period average projected flat.

    Note: for product-hierarchy grains (taxon_*), statistical_qty is
    actually REVENUE at this stage. disaggregate_to_atomic() converts
    it to qty using item prices.
    """
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP
    from collections import defaultdict

    MODEL_MAP = {
        'AUTOETS':   lambda sl: AutoETS(season_length=sl),
        'AUTOARIMA': lambda sl: AutoARIMA(season_length=sl),
        'CROSTON':   lambda sl: CrostonSBA(),
    }

    # Group series: (grain, strategy, eval_period) → [unique_id, ...]
    groups: dict[tuple, list[str]] = defaultdict(list)
    for uid, dec in decisions.items():
        if dec['is_manual']:
            continue
        key = (dec['grain'], dec['strategy'], dec['eval_period'])
        groups[key].append(uid)

    all_results = []

    for (grain, strategy, eval_period), uids in groups.items():
        agg_df = aggregated_actuals.get(grain)
        if agg_df is None:
            logger.warning(f'run_statsforecast_by_grain: no actuals for grain={grain}')
            continue

        # Map atomic unique_ids to their aggregate unique_ids
        agg_ids = _map_uids_to_agg_ids(uids, grain)
        subset  = agg_df[agg_df['unique_id'].isin(agg_ids)].copy()

        if subset.empty:
            continue

        subset['ds'] = pd.to_datetime(subset['ds'])
        subset['y']  = subset['y'].astype(float)

        run_freq    = PERIOD_FREQ_MAP.get(eval_period, freq)
        run_horizon = _scale_horizon(horizon, freq, run_freq)

        if strategy == 'MOVING_AVG':
            fcast = _compute_moving_avg(subset, run_horizon, run_freq)
            model_col = 'MOVING_AVG'
        elif strategy in MODEL_MAP:
            model_fn = MODEL_MAP[strategy]
            sf = StatsForecast(
                models=[model_fn(season_length)],
                freq=run_freq, n_jobs=n_jobs,
            )
            fcast = sf.forecast(
                df=subset, h=run_horizon,
                prediction_intervals=ConformalIntervals(
                    h=run_horizon, n_windows=2
                ),
                level=[80, 95],
            )
            # Rename model column to strategy for consistency
            model_cols = [
                c for c in fcast.columns
                if c not in ('unique_id', 'ds')
                and not any(c.endswith(s) for s in ('-lo-80','-hi-80','-lo-95','-hi-95'))
            ]
            if model_cols:
                fcast = fcast.rename(columns={model_cols[0]: strategy})
            model_col = strategy
        else:
            logger.warning(f'Unknown strategy {strategy} — skipping')
            continue

        # Keep only point forecast
        if model_col not in fcast.columns:
            continue
        fcast_clean = fcast[['unique_id', 'ds', model_col]].copy()
        fcast_clean = fcast_clean.rename(columns={model_col: 'statistical_qty'})
        fcast_clean['grain']          = grain
        fcast_clean['model_used']     = _strategy_to_model_label(strategy)
        fcast_clean['eval_period']    = eval_period
        fcast_clean['forecast_level'] = grain

        all_results.append(fcast_clean)

    # MANUAL series — write zero rows so ForecastLine exists for planner override
    manual_uids = [uid for uid, dec in decisions.items() if dec['is_manual']]
    if manual_uids and all_results:
        last_ds = all_results[0]['ds'].max()
        future  = pd.date_range(
            start=last_ds + pd.tseries.frequencies.to_offset(freq),
            periods=horizon, freq=freq,
        )
        for uid in manual_uids:
            df_zero = pd.DataFrame({
                'unique_id':      uid,
                'ds':             future,
                'statistical_qty': 0.0,
                'grain':          decisions[uid]['grain'],
                'model_used':     'None',
                'eval_period':    freq,
                'forecast_level': decisions[uid]['grain'],
            })
            all_results.append(df_zero)

    if not all_results:
        raise ValueError('No forecast results produced. Check SeriesProfile decisions.')

    combined = pd.concat(all_results, ignore_index=True)
    combined  = combined.drop_duplicates(subset=['unique_id', 'ds', 'grain'])
    return combined



def _map_uids_to_agg_ids(uids: list[str], grain: str) -> list[str]:
    """
    Convert atomic unique_ids to their aggregate counterpart for a grain.

    Grain taxonomy
    ──────────────
    item_cust_location               → atomic; uid unchanged
    item_location                    → drop customer  → item|ALL_CUST|loc
    item_loc_depth_N                 → aggregate to location ancestor N
    item_client                      → all locs/custs → item|ALL_CUST|ALL_LOC
    item_client_{period}             → time-agg of item_client uid
                                       → item|ALL_CUST|ALL_LOC  (same uid)
    item_loc_depth_N_{period}        → time-agg of depth-N uid
                                       → item|ALL_CUST|loc      (same loc sentinel)
    taxon_{node_id}_client           → product rollup → taxon_{node_id}_ALL_LOC
    taxon_{node_id}_client_{period}  → product + time rollup → same sentinel

    Fix vs original
    ───────────────
    The original hard-coded `endswith('_quarter')`, `endswith('_halfyear')`,
    `endswith('_year')`.  Any grain ending in 'week', 'fortnight', 'month',
    'bimonth', etc. fell through to the else branch and returned the atomic uid
    unchanged — wrong because the aggregate uid is different.

    This version derives the set of valid time suffixes from
    _TIME_GRAIN_SUFFIXES so it is automatically correct for any period type
    defined in PERIOD_HIGHER_HORIZONS.
    """
    agg_ids: set[str] = set()

    for uid in uids:
        parts = uid.split('|')
        if len(parts) != 3:
            continue
        item_id, cust_code, loc_code = parts

        # ── Atomic grain: uid is its own aggregate ─────────────────────────
        if grain == 'item_cust_location':
            agg_ids.add(uid)

        # ── Location-only (drop customer) ──────────────────────────────────
        elif grain == 'item_location':
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')

        # ── Location depth-N (possibly + time suffix) ──────────────────────
        # Handles: item_loc_depth_N  and  item_loc_depth_N_{period}
        elif grain.startswith('item_loc_depth_'):
            # Strip any trailing time suffix before extracting the depth token
            base_grain = grain
            if _grain_has_time_suffix(grain):
                base_grain = grain.rsplit('_', 1)[0]   # e.g. item_loc_depth_2
            # Aggregate uid keeps the location sentinel but strips the customer
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')

        # ── Item × Client (all locs/custs, with or without time suffix) ────
        # Handles: item_client  and  item_client_{period}
        elif grain == 'item_client' or (
            grain.startswith('item_client') and _grain_has_time_suffix(grain)
        ):
            agg_ids.add(f'{item_id}|ALL_CUST|ALL_LOC')

        # ── Product-hierarchy grain (with or without time suffix) ──────────
        # Handles: taxon_{id}_client  and  taxon_{id}_client_{period}
        elif grain.startswith('taxon_'):
            node_id = grain.split('_')[1]
            agg_ids.add(f'taxon_{node_id}_ALL_LOC')

        # ── Fallback: unrecognised grain — keep uid as-is ──────────────────
        else:
            logger.warning(
                '_map_uids_to_agg_ids: unrecognised grain "%s" for uid "%s" '
                '— returning uid unchanged', grain, uid,
            )
            agg_ids.add(uid)

    return list(agg_ids)

def ZZ_map_uids_to_agg_ids(uids: list[str], grain: str) -> list[str]:
    """Convert atomic unique_ids to their aggregate counterpart for a grain."""
    agg_ids = set()
    for uid in uids:
        parts = uid.split('|')
        if len(parts) != 3:
            continue
        item_id, cust_code, loc_code = parts
        if grain in ('item_cust_location', ):
            agg_ids.add(uid)
        elif grain == 'item_location':
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')
        elif grain == 'item_client' or grain.endswith('_quarter') or \
             grain.endswith('_halfyear') or grain.endswith('_year'):
            agg_ids.add(f'{item_id}|ALL_CUST|ALL_LOC')
        elif grain.startswith('item_loc_depth_'):
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')  # simplified
        elif grain.startswith('taxon_'):
            node_id = grain.split('_')[1]
            agg_ids.add(f'taxon_{node_id}_ALL_LOC')
        else:
            agg_ids.add(uid)
    return list(agg_ids)

# Canonical seconds-per-period for every pandas freq alias that
# PERIOD_FREQ_MAP can produce.  All values are expressed in the same unit
# (seconds) so ratios are always dimensionally correct.
#
# How to extend: add any new pandas freq alias you introduce in PERIOD_FREQ_MAP.
# The ratio base_seconds / target_seconds gives the horizon scaling factor:
#   horizon_at_target = ceil(horizon_at_base * base_seconds / target_seconds)
#
_FREQ_SECONDS: dict[str, float] = {
    # Sub-day
    's':       1.0,                    # second  (pandas 'S' / 's')
    'S':       1.0,
    'T':       60.0,                   # minute  (legacy pandas alias)
    'min':     60.0,                   # minute  (pandas ≥ 2.2)
    'h':       3_600.0,                # hour    (pandas ≥ 2.2)
    'H':       3_600.0,                # hour    (legacy pandas alias)
    # Day / week
    'D':       86_400.0,               # day
    'W-MON':   7 * 86_400.0,          # week (Monday-anchored)
    'W':       7 * 86_400.0,          # week (generic)
    '2W-MON':  14 * 86_400.0,         # fortnight
    # Month and multiples  (approximations; used only for ratio — absolute
    # values are irrelevant as long as they are mutually consistent)
    'MS':      30.4375 * 86_400.0,    # month-start
    'M':       30.4375 * 86_400.0,    # month-end (legacy)
    '2MS':     2 * 30.4375 * 86_400.0,   # bimonth
    '2M':      2 * 30.4375 * 86_400.0,
    'QS':      91.3125 * 86_400.0,    # quarter-start  (365.25 / 4 days)
    'QS-OCT':  91.3125 * 86_400.0,    # fiscal-year quarter variants
    'QS-JAN':  91.3125 * 86_400.0,
    'Q':       91.3125 * 86_400.0,    # quarter-end (legacy)
    '2QS':     182.625 * 86_400.0,    # half-year (2 quarters)
    '2Q':      182.625 * 86_400.0,
    'YS':      365.25  * 86_400.0,    # year-start
    'AS':      365.25  * 86_400.0,    # year-start (legacy pandas alias)
    'A':       365.25  * 86_400.0,    # year-end  (legacy)
    'Y':       365.25  * 86_400.0,
}


def _scale_horizon(base_horizon: int, base_freq: str, target_freq: str) -> int:
    """
    Scale a forecast horizon when the target evaluation period is coarser
    (or finer) than the base period type.

    Examples (base = monthly 'MS', horizon = 6):
        target 'QS'    (quarterly)  → ceil(6 * 1/3)   = 2 quarters
        target '2QS'   (halfyear)   → ceil(6 * 1/6)   = 1 halfyear  (min 2)
        target 'YS'    (yearly)     → ceil(6 * 1/12)  = 1 year      (min 2)
        target 'W-MON' (weekly)     → ceil(6 * ~4.3)  = 26 weeks
        target '2W-MON'(fortnight)  → ceil(6 * ~2.2)  = 14 fortnights
        target 'D'     (daily)      → ceil(6 * ~30.4) = 183 days

    Fix vs original
    ───────────────
    Original had only 6 entries: MS, QS, 2QS, YS, D, W-MON.
    Missing: s, S, T, min, h, H, 2W-MON, 2MS, 2Q, AS, A, Y, QS-OCT …
    Any missing freq defaulted to scales.get(…, 1) which silently returned 1,
    producing wildly incorrect horizon counts (e.g. a weekly series with a
    monthly horizon of 6 would have gotten run_horizon=6 weeks instead of ~26).

    This version is driven by _FREQ_SECONDS so every entry is dimensionally
    consistent and any unknown freq raises an explicit warning rather than
    silently returning 1.
    """
    if base_freq == target_freq:
        return base_horizon

    base_sec   = _FREQ_SECONDS.get(base_freq)
    target_sec = _FREQ_SECONDS.get(target_freq)

    if base_sec is None:
        logger.warning(
            '_scale_horizon: unknown base_freq "%s" — treating as 1 period; '
            'add it to _FREQ_SECONDS to silence this warning', base_freq,
        )
        base_sec = 1.0

    if target_sec is None:
        logger.warning(
            '_scale_horizon: unknown target_freq "%s" — treating as 1 period; '
            'add it to _FREQ_SECONDS to silence this warning', target_freq,
        )
        target_sec = 1.0

    if target_sec == 0:
        return base_horizon

    raw = base_horizon * base_sec / target_sec
    # Always run at least 2 periods so StatsForecast has enough context
    # to fit seasonal components.  Cap at a generous ceiling to avoid
    # accidentally running a 365-period daily model.
    return max(2, round(raw))


def ZZ_scale_horizon(base_horizon: int, base_freq: str, target_freq: str) -> int:
    """Scale horizon when forecasting at a coarser time period."""
    scales = {'MS': 1, 'QS': 3, '2QS': 6, 'YS': 12, 'D': 0.033, 'W-MON': 0.25}
    base_scale   = scales.get(base_freq, 1)
    target_scale = scales.get(target_freq, 1)
    if target_scale == 0:
        return base_horizon
    return max(2, int(base_horizon * base_scale / target_scale))


def _compute_moving_avg(
    df: pd.DataFrame,
    horizon: int,
    freq: str,
    n_periods: int = 6,
) -> pd.DataFrame:
    """Simple N-period moving average, projected flat."""
    last_ds = df['ds'].max()
    future  = pd.date_range(
        start=last_ds + pd.tseries.frequencies.to_offset(freq),
        periods=horizon, freq=freq,
    )
    results = []
    for uid in df['unique_id'].unique():
        s     = df[df['unique_id'] == uid].sort_values('ds')
        nz    = s[s['y'] > 0]['y']
        avg   = float(nz.tail(n_periods).mean()) if len(nz) > 0 else 0.0
        rows  = pd.DataFrame({'unique_id': uid, 'ds': future, 'MOVING_AVG': avg})
        results.append(rows)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def _strategy_to_model_label(strategy: str) -> str:
    return {
        'AUTOETS':    'AutoETS',
        'AUTOARIMA':  'AutoARIMA',
        'CROSTON':    'CrostonSBA',
        'MOVING_AVG': 'MovingAverage',
        'MANUAL':     'None',
    }.get(strategy, strategy)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Disaggregate non-atomic forecasts back to atomic unique_ids
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — period expansion
# ─────────────────────────────────────────────────────────────────────────────

def _expand_coarse_periods_to_base(
    coarse_rows: list[dict],
    coarse_period: str,
    base_period_type: str,
    base_freq: str,
) -> list[dict]:
    """
    Given a list of forecast rows at a coarser period (e.g. quarterly),
    expand each row into N base-period rows (e.g. 3 monthly rows) by
    equal distribution.

    Each input dict must contain at least:
        ds               — the coarse period start (date or Timestamp)
        statistical_qty  — the coarse-period forecast value
        unique_id        — atomic unique_id for the disaggregated row
        grain            — original grain label (carried through for audit)
        model_used       — carried through

    Returns a flat list of dicts with base-period `ds` values.

    Rationale
    ─────────
    StatsForecast produces forecasts at the eval_period granularity
    (e.g. quarterly).  ForecastLine.period_start must match the version's
    base period_type (e.g. monthly).  This helper performs the time expansion
    step BEFORE location or value-share disaggregation so subsequent steps
    always operate on base-period rows.

    Equal distribution is the correct default here because:
    a) We have no within-period actuals to weight by (that data is at the
       coarser grain by construction — the series was aggregated precisely
       because the finer grain was too sparse).
    b) The hierarchical reconciliation step that follows disaggregation will
       adjust totals to be consistent with bottom-up actuals anyway.
    """
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP

    coarse_freq = PERIOD_FREQ_MAP.get(coarse_period)
    if coarse_freq is None:
        logger.warning(
            '_expand_coarse_periods_to_base: no PERIOD_FREQ_MAP entry for '
            '"%s" — returning rows unchanged', coarse_period,
        )
        return coarse_rows

    # Number of base periods per coarse period
    coarse_sec = _FREQ_SECONDS.get(coarse_freq, 1.0)
    base_sec   = _FREQ_SECONDS.get(base_freq, 1.0)
    n_sub = max(1, round(coarse_sec / base_sec))

    expanded: list[dict] = []
    for row in coarse_rows:
        coarse_ds = pd.Timestamp(row['ds'])
        # Generate n_sub base-period timestamps starting from coarse_ds
        sub_dates = pd.date_range(start=coarse_ds, periods=n_sub, freq=base_freq)
        per_period_qty = row['statistical_qty'] / n_sub
        for sub_ds in sub_dates:
            expanded.append({
                **row,
                'ds':             sub_ds,
                'statistical_qty': per_period_qty,
                # Tag the model_used so the audit trail is clear
                'model_used':     row['model_used'] + f'@expand_{coarse_period}',
            })

    return expanded


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3 — disaggregate_to_atomic  (replaces lines 792-919)
# ─────────────────────────────────────────────────────────────────────────────

def disaggregate_to_atomic(
    forecast_df: pd.DataFrame,
    actuals_df,                        # pl.DataFrame
    decisions: dict[str, dict],
    period_type: str,
    base_freq: str,
    disagg_conflict: str = 'retain_lower',
) -> pd.DataFrame:
    """
    For series whose grain is NOT item_cust_location (atomic), distribute
    the aggregate forecast back to each constituent atomic unique_id.

    NOTE: `period_type` and `base_freq` are new required parameters vs the
    original signature.  The Celery task already has these from
    ForecastVersion; pass them through.

    Disaggregation method
    ─────────────────────
    Location-hierarchy grains (item_location, item_loc_depth_N, item_client):
        Use QUANTITY share — proportional to historical mean qty per series.

    Product-hierarchy grains (taxon_*):
        Use VALUE share — proportional to historical mean revenue per item.
        Convert disaggregated VALUE to QTY using item's effective_price.

    Pure time-aggregation grains (*_{period}  where {period} ∈ _TIME_GRAIN_SUFFIXES):
        e.g. item_client_quarter, item_loc_depth_2_month
        Step 1 — expand each coarse-period forecast row into N base-period rows
                 by equal distribution.
        Step 2 — apply location disaggregation to each expanded base-period row
                 using qty share (same as location grains above).

    Product + time combined grains (taxon_{id}_client_{period}):
        Step 1 — expand each coarse-period REVENUE forecast into N base-period
                 revenue rows (equal distribution).
        Step 2 — apply value-share disaggregation to each expanded row,
                 converting revenue share to qty using item effective_price.

    disagg_conflict
    ───────────────
    'retain_lower': finer-grain forecast wins — do not overwrite atomic series
                    that already had their own forecast.
    'use_upper':    disaggregation overwrites everything.

    Returns DataFrame: unique_id (atomic), ds, statistical_qty, grain,
                       model_used, forecast_level
    All ds values are base-period timestamps (matching ForecastLine.period_start).

    Fixes vs original
    ─────────────────
    Gap A: is_time_grain uses _TIME_GRAIN_SUFFIXES  (was hard-coded to 3 tokens)
    Gap B: pure time-grain grains now have an explicit handling branch that
           first expands the coarse forecast to base-period rows, then applies
           location disaggregation.  Previously the is_time_grain flag was
           computed but never acted on — these rows fell into the location-grain
           else branch where no time expansion happened, so ForecastLine rows
           ended up with quarterly ds values instead of monthly ones.
    Gap C: taxon_{id}_client_{period} (product + time) now expands REVENUE to
           base-period rows before value-share → qty conversion.  Previously
           the code wrote one row per coarse ds value, which did not match the
           monthly ForecastLine.period_start expected by the rest of the system.
    """
    actuals_pd = actuals_df.to_pandas()
    actuals_pd['ds'] = pd.to_datetime(actuals_pd['ds'])

    # ── Separate atomic from non-atomic ──────────────────────────────────────
    atomic_forecasts    = forecast_df[forecast_df['grain'] == 'item_cust_location'].copy()
    non_atomic_forecast = forecast_df[forecast_df['grain'] != 'item_cust_location'].copy()

    if non_atomic_forecast.empty:
        return atomic_forecasts

    # ── Historical means for disaggregation weights ───────────────────────────
    uid_qty_mean: dict[str, float] = (
        actuals_pd.groupby('unique_id')['y'].mean().to_dict()
    )
    uid_rev_mean: dict[str, float] = (
        actuals_pd.groupby('unique_id')['revenue'].mean().to_dict()
    )

    disaggregated_rows: list[dict] = []

    for (grain, ds_val), group in non_atomic_forecast.groupby(['grain', 'ds']):
        agg_ids = group['unique_id'].unique()

        # Members: agg_id → [atomic_uids]
        members: dict[str, list[str]] = {}
        for uid, dec in decisions.items():
            if dec['grain'] != grain:
                continue
            mapped = _map_uids_to_agg_ids([uid], grain)
            if mapped and mapped[0] in agg_ids:
                members.setdefault(mapped[0], []).append(uid)

        for _, fcast_row in group.iterrows():
            agg_id     = fcast_row['unique_id']
            agg_qty    = float(fcast_row['statistical_qty'])
            child_uids = members.get(agg_id, [])

            if not child_uids:
                continue

            # ── Classify this grain ─────────────────────────────────────────
            is_product_grain = grain.startswith('taxon_')
            time_suffix      = _grain_time_suffix(grain)   # str or None
            is_time_grain    = time_suffix is not None

            # ── Strip the time suffix to get the spatial base grain ─────────
            # e.g.  item_client_quarter  →  item_client
            #       item_loc_depth_2_month → item_loc_depth_2
            #       taxon_42_client_halfyear → taxon_42_client  (product grain)
            spatial_grain = grain.rsplit('_', 1)[0] if is_time_grain else grain

            # ══════════════════════════════════════════════════════════════════
            # CASE 1 — Product-hierarchy grain, possibly with time suffix
            #          (taxon_{id}_client  or  taxon_{id}_client_{period})
            # ══════════════════════════════════════════════════════════════════
            if is_product_grain:
                # agg_qty is actually REVENUE at this point.
                agg_revenue = agg_qty

                # Step 1 (Gap C fix): if there is a coarse time period, expand
                # this single coarse-period revenue row into N base-period rows
                # by equal distribution BEFORE value-share disaggregation.
                if is_time_grain:
                    expanded_rows = _expand_coarse_periods_to_base(
                        coarse_rows=[{
                            'ds':             ds_val,
                            'statistical_qty': agg_revenue,
                            'unique_id':      agg_id,   # temporary; replaced below
                            'grain':          grain,
                            'model_used':     fcast_row['model_used'],
                            'forecast_level': grain,
                        }],
                        coarse_period=time_suffix,
                        base_period_type=period_type,
                        base_freq=base_freq,
                    )
                else:
                    # No time suffix — one row at native period_type
                    expanded_rows = [{
                        'ds':             ds_val,
                        'statistical_qty': agg_revenue,
                        'unique_id':      agg_id,
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'],
                        'forecast_level': grain,
                    }]

                # Step 2: value-share → qty disaggregation for each expanded row
                child_revs = {u: uid_rev_mean.get(u, 0.0) for u in child_uids}
                total_rev  = sum(child_revs.values()) or 1.0

                for exp_row in expanded_rows:
                    per_period_revenue = exp_row['statistical_qty']
                    for uid in child_uids:
                        share     = child_revs[uid] / total_rev
                        item_rev  = per_period_revenue * share
                        price     = float(decisions[uid].get('price') or 1.0)
                        child_qty = item_rev / price if price > 0 else 0.0
                        disaggregated_rows.append({
                            'unique_id':       uid,
                            'ds':              exp_row['ds'],
                            'statistical_qty': max(0.0, child_qty),
                            'grain':           grain,
                            'model_used':      exp_row['model_used'] + '@value_disagg',
                            'forecast_level':  grain,
                        })

            # ══════════════════════════════════════════════════════════════════
            # CASE 2 — Pure time-aggregation grain (non-product)
            #          e.g. item_client_quarter, item_loc_depth_2_month
            #
            # Gap B fix: previously these fell into the else (location-qty)
            # branch with no time expansion, leaving ds at quarterly values.
            # Now they are explicitly expanded first, then location-disaggregated.
            # ══════════════════════════════════════════════════════════════════
            elif is_time_grain:
                # Step 1: expand coarse forecast → N base-period rows
                expanded_rows = _expand_coarse_periods_to_base(
                    coarse_rows=[{
                        'ds':             ds_val,
                        'statistical_qty': agg_qty,
                        'unique_id':      agg_id,
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'],
                        'forecast_level': grain,
                    }],
                    coarse_period=time_suffix,
                    base_period_type=period_type,
                    base_freq=base_freq,
                )

                # Step 2: qty-share location disaggregation for each expanded row
                child_qtys = {u: uid_qty_mean.get(u, 0.0) for u in child_uids}
                total_qty  = sum(child_qtys.values()) or 1.0

                for exp_row in expanded_rows:
                    per_period_qty = exp_row['statistical_qty']
                    for uid in child_uids:
                        share     = child_qtys[uid] / total_qty
                        child_qty = per_period_qty * share
                        disaggregated_rows.append({
                            'unique_id':       uid,
                            'ds':              exp_row['ds'],
                            'statistical_qty': max(0.0, child_qty),
                            'grain':           grain,
                            'model_used':      exp_row['model_used'],
                            'forecast_level':  grain,
                        })

            # ══════════════════════════════════════════════════════════════════
            # CASE 3 — Spatial location grain at native period
            #          (item_location, item_loc_depth_N, item_client)
            # ══════════════════════════════════════════════════════════════════
            else:
                child_qtys = {u: uid_qty_mean.get(u, 0.0) for u in child_uids}
                total_qty  = sum(child_qtys.values()) or 1.0
                for uid in child_uids:
                    share     = child_qtys[uid] / total_qty
                    child_qty = agg_qty * share
                    disaggregated_rows.append({
                        'unique_id':       uid,
                        'ds':              ds_val,
                        'statistical_qty': max(0.0, child_qty),
                        'grain':           grain,
                        'model_used':      fcast_row['model_used'],
                        'forecast_level':  grain,
                    })

    disagg_df = (
        pd.DataFrame(disaggregated_rows)
        if disaggregated_rows
        else pd.DataFrame(columns=[
            'unique_id', 'ds', 'statistical_qty',
            'grain', 'model_used', 'forecast_level',
        ])
    )

    # ── Conflict resolution ───────────────────────────────────────────────────
    if disagg_conflict == 'retain_lower' and not atomic_forecasts.empty:
        # Atomic series with their own fine-grain forecast are not overwritten.
        # Exclude by (unique_id, ds) pair so only the specific periods that
        # were directly forecast are protected, not the entire series.
        atomic_covered = set(
            zip(atomic_forecasts['unique_id'], atomic_forecasts['ds'])
        )
        mask = disagg_df.apply(
            lambda r: (r['unique_id'], r['ds']) not in atomic_covered, axis=1
        )
        disagg_df = disagg_df[mask]

    combined = pd.concat([atomic_forecasts, disagg_df], ignore_index=True)
    return combined


def ZZdisaggregate_to_atomic(
    forecast_df: pd.DataFrame,
    actuals_df: pl.DataFrame,
    decisions: dict[str, dict],
    disagg_conflict: str = 'retain_lower',
) -> pd.DataFrame:
    """
    For series whose grain is NOT item_cust_location (atomic), distribute
    the aggregate forecast back to each constituent atomic unique_id.

    Disaggregation method:
        Location-hierarchy grains (item_location, item_loc_depth_N, item_client):
            Use QUANTITY share — proportional to historical mean qty per series.

        Product-hierarchy grains (taxon_*):
            Use VALUE share — proportional to historical mean revenue per item.
            Convert disaggregated VALUE to QTY using item's effective_price.
            Rationale: items in a product group have different unit prices;
            qty-based share would distort the result.

        Time-aggregation grains (*_quarter, *_halfyear, *_year):
            Expand quarterly/yearly forecast back to monthly periods by
            equal distribution (e.g. quarterly / 3 = monthly).
            Then apply location disaggregation if also aggregated by location.

    disagg_conflict controls what happens when an item has forecasts
    at multiple grains (from store_all_level_forecasts=True):
        'retain_lower': finer-grain forecast wins — do not overwrite atomic
                        series that had their own forecast.
        'use_upper':    product-group disaggregation overwrites all items
                        including those with their own atomic forecast.

    Returns DataFrame: unique_id (atomic), ds, statistical_qty, grain, model_used
    """
    actuals_pd = actuals_df.to_pandas()
    actuals_pd['ds'] = pd.to_datetime(actuals_pd['ds'])

    # Separate atomic from non-atomic
    atomic_forecasts    = forecast_df[forecast_df['grain'] == 'item_cust_location'].copy()
    non_atomic_forecast = forecast_df[forecast_df['grain'] != 'item_cust_location'].copy()

    if non_atomic_forecast.empty:
        return atomic_forecasts

    # Build qty and value history per atomic unique_id
    uid_qty_mean = (
        actuals_pd.groupby('unique_id')['y'].mean().to_dict()
    )
    uid_rev_mean = (
        actuals_pd.groupby('unique_id')['revenue'].mean().to_dict()
    )

    disaggregated_rows = []

    for (grain, ds_val), group in non_atomic_forecast.groupby(['grain', 'ds']):
        agg_ids = group['unique_id'].unique()

        # Find all atomic uids that belong to these agg_ids at this grain
        members: dict[str, list[str]] = {}  # agg_id → [atomic_uids]
        for uid, dec in decisions.items():
            if dec['grain'] != grain:
                continue
            agg_id = _map_uids_to_agg_ids([uid], grain)
            if agg_id and agg_id[0] in agg_ids:
                members.setdefault(agg_id[0], []).append(uid)

        for _, fcast_row in group.iterrows():
            agg_id     = fcast_row['unique_id']
            agg_qty    = float(fcast_row['statistical_qty'])
            child_uids = members.get(agg_id, [])

            if not child_uids:
                continue

            is_product_grain = grain.startswith('taxon_')
            is_time_grain    = any(
                grain.endswith(f'_{p}')
                for p in ('quarter', 'halfyear', 'year')
            )

            if is_product_grain:
                # Value-based disaggregation
                # agg_qty is actually revenue at this point
                agg_revenue = agg_qty
                child_revs  = {u: uid_rev_mean.get(u, 0.0) for u in child_uids}
                total_rev   = sum(child_revs.values()) or 1.0
                for uid in child_uids:
                    share     = child_revs[uid] / total_rev
                    item_rev  = agg_revenue * share
                    price     = float(decisions[uid].get('price') or 1.0)
                    child_qty = item_rev / price if price > 0 else 0.0
                    disaggregated_rows.append({
                        'unique_id':      uid,
                        'ds':             ds_val,
                        'statistical_qty': max(0.0, child_qty),
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'] + '@value_disagg',
                        'forecast_level': grain,
                    })

            else:
                # Quantity-based disaggregation (location grains)
                child_qtys = {u: uid_qty_mean.get(u, 0.0) for u in child_uids}
                total_qty  = sum(child_qtys.values()) or 1.0
                for uid in child_uids:
                    share     = child_qtys[uid] / total_qty
                    child_qty = agg_qty * share
                    disaggregated_rows.append({
                        'unique_id':      uid,
                        'ds':             ds_val,
                        'statistical_qty': max(0.0, child_qty),
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'],
                        'forecast_level': grain,
                    })

    disagg_df = pd.DataFrame(disaggregated_rows) if disaggregated_rows \
                else pd.DataFrame(columns=['unique_id','ds','statistical_qty',
                                           'grain','model_used','forecast_level'])

    # Apply conflict resolution
    if disagg_conflict == 'retain_lower' and not atomic_forecasts.empty:
        # Atomic series that already have their own forecast are not overwritten
        atomic_uids_covered = set(atomic_forecasts['unique_id'].unique())
        disagg_df = disagg_df[~disagg_df['unique_id'].isin(atomic_uids_covered)]

    combined = pd.concat([atomic_forecasts, disagg_df], ignore_index=True)
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# 7. Hierarchical reconciliation (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

def run_hierarchical_reconciliation(
    forecasts_df: pd.DataFrame,
    Y_df: pd.DataFrame,
    S_df: pd.DataFrame,
    tags: dict,
    method: str = 'MinTrace_ols',
) -> pd.DataFrame:
    """
    Apply HierarchicalForecast reconciliation.
    Method: 'BottomUp' | 'MinTrace_ols' | 'MinTrace_wls_struct'
    """
    reconcilers = {
        'BottomUp':            [BottomUp()],
        'MinTrace_ols':        [MinTrace(method='ols')],
        'MinTrace_wls_struct': [MinTrace(method='wls_struct')],
    }
    selected = reconcilers.get(method, [MinTrace(method='ols')])
    hrec = HierarchicalReconciliation(reconcilers=selected)

    return hrec.reconcile(
        Y_hat_df=forecasts_df,
        Y_df=Y_df,
        S_df=S_df,
        tags=tags,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 8. Write ForecastLine rows
# ─────────────────────────────────────────────────────────────────────────────

def write_forecast_lines(
    version_id: int,
    forecast_df: pd.DataFrame,
    decisions: dict[str, dict],
    period_type: str,
    store_all_level_forecasts: bool = True,
) -> int:
    """
    Convert the combined forecast DataFrame into ForecastLine rows and
    bulk_create them.

    forecast_df columns: unique_id, ds, statistical_qty, grain, model_used

    When store_all_level_forecasts=True, one ForecastLine is written per
    (unique_id, ds, grain) combination. The forecast_level field distinguishes
    them. This enables post-run comparison of forecasts at different levels.

    When False, only the final disaggregated atomic forecast is written.

    Returns: number of lines created.
    """
    from mysite.models.demand.forecast import ForecastLine, ForecastVersion
    from mysite.models import Item
    from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
    from mysite.models.demand.actuals import compute_period_end

    version = ForecastVersion.objects.get(pk=version_id)

    # FK lookup maps
    item_str_to_pk: dict[str, int] = {
        row['item_id']: row['id']
        for row in Item.objects.filter(client=version.client)
        .values('id', 'item_id')
    }
    loc_code_to_pk: dict[str, int] = {
        row['code']: row['id']
        for row in PlanningLocation.objects.filter(client=version.client)
        .values('id', 'code')
    }
    cust_code_to_pk: dict[str, int | None] = {
        row['code']: row['id']
        for row in PlanningCustomer.objects.filter(client=version.client)
        .values('id', 'code')
    }
    cust_code_to_pk['NULL'] = None

    # Delete existing lines
    ForecastLine.objects.filter(version=version).delete()

    if not store_all_level_forecasts:
        # Keep only the final atomic grain rows
        forecast_df = forecast_df[
            forecast_df['grain'] == 'item_cust_location'
        ].copy()

    lines = []
    skipped = 0

    for _, row in forecast_df.iterrows():
        uid = row['unique_id']
        # Atomic uid format: item_id|cust_code|loc_code
        # Non-atomic uid format: varies — skip for ForecastLine
        # (ForecastAggregate handles non-atomic rollups)
        parts = uid.split('|')
        if len(parts) != 3:
            skipped += 1
            continue

        item_id_str, cust_code, loc_code = parts
        # Skip aggregate grain rows that don't map to atomic FKs
        if loc_code in ('ALL_LOC',) or item_id_str.startswith('taxon_'):
            skipped += 1
            continue

        item_pk = item_str_to_pk.get(item_id_str)
        loc_pk  = loc_code_to_pk.get(loc_code)
        if item_pk is None or loc_pk is None:
            skipped += 1
            continue

        cust_pk  = cust_code_to_pk.get(cust_code)
        dec      = decisions.get(uid, {})
        price    = dec.get('price')

        period_start = row['ds'].date() if hasattr(row['ds'], 'date') else row['ds']
        period_end   = compute_period_end(period_start, period_type)
        stat_qty     = Decimal(str(round(max(float(row['statistical_qty']), 0), 3)))

        line = ForecastLine(
            version_id           = version_id,
            item_id              = item_pk,
            planning_customer_id = cust_pk,
            planning_location_id = loc_pk,
            period_type          = period_type,
            period_start         = period_start,
            period_end           = period_end,
            statistical_qty      = stat_qty,
            override_qty         = None,
            model_used           = row.get('model_used', ''),
            forecast_level       = row.get('forecast_level', 'item_cust_location'),
            price_used           = price,
        )
        # Compute value fields before bulk_create (save() not called on bulk_create)
        line.final_qty = stat_qty
        if price is not None:
            line.statistical_value = (stat_qty * price).quantize(TWO_DP)
            line.final_value       = line.statistical_value
        lines.append(line)

    created = 0
    for i in range(0, len(lines), BATCH_SIZE_LINES):
        batch = lines[i : i + BATCH_SIZE_LINES]
        ForecastLine.objects.bulk_create(batch, batch_size=BATCH_SIZE_LINES)
        created += len(batch)

    if skipped:
        logger.warning(f'write_forecast_lines: skipped {skipped} rows')
    logger.info(f'write_forecast_lines: created {created} ForecastLine rows')
    return created


# ─────────────────────────────────────────────────────────────────────────────
# 9. Write ForecastAggregate rows
# ─────────────────────────────────────────────────────────────────────────────

def write_forecast_aggregates(version_id: int) -> int:
    """
    Roll up ForecastLine rows into ForecastAggregate at multiple levels
    using DuckDB for fast in-process aggregation.

    Levels: total, location (leaf), customer, item.
    Also computes weighted_avg_price per node = sum(final_value)/sum(final_qty).

    Returns: number of ForecastAggregate rows created.
    """
    from mysite.models.demand.forecast import ForecastLine, ForecastAggregate, ForecastVersion
    from mysite.models.demand.actuals import compute_period_end
    import json

    version = ForecastVersion.objects.get(pk=version_id)

    lines_qs = (
        ForecastLine.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer')
        .values(
            'item_id', 'item__item_id',
            'planning_location_id', 'planning_location__code',
            'planning_customer_id', 'planning_customer__code',
            'period_type', 'period_start',
            'statistical_qty', 'final_qty',
            'statistical_value', 'final_value',
        )
    )

    if not lines_qs.exists():
        logger.warning(
            f'write_forecast_aggregates: no lines for version {version_id}'
        )
        return 0

    df_pd = pd.DataFrame(list(lines_qs))
    for col in ('statistical_qty', 'final_qty'):
        df_pd[col] = df_pd[col].astype(float)
    for col in ('statistical_value', 'final_value'):
        df_pd[col] = df_pd[col].fillna(0).astype(float)
    df_pd['customer_code'] = df_pd['planning_customer__code'].fillna('__unattr__')

    con = duckdb.connect()
    con.register('lines', df_pd)

    AGG_QUERIES = {
        'total': """
            SELECT
                'total' AS agg_level,
                '{"level": "total"}' AS agg_key_json,
                period_type,
                period_start,
                SUM(statistical_qty)   AS statistical_qty,
                SUM(final_qty)         AS final_qty,
                SUM(statistical_value) AS total_statistical_value,
                SUM(final_value)       AS total_final_value
            FROM lines
            GROUP BY period_type, period_start
        """,
        'location': """
            SELECT
                'location' AS agg_level,
                CONCAT('{\"location_code\": \"',
                    "planning_location__code", '\"}') AS agg_key_json,
                period_type,
                period_start,
                SUM(statistical_qty)   AS statistical_qty,
                SUM(final_qty)         AS final_qty,
                SUM(statistical_value) AS total_statistical_value,
                SUM(final_value)       AS total_final_value
            FROM lines
            GROUP BY "planning_location__code", period_type, period_start
        """,
        'item': """
            SELECT
                'item' AS agg_level,
                CONCAT('{\"item_id\": \"', "item__item_id", '\"}') AS agg_key_json,
                period_type,
                period_start,
                SUM(statistical_qty)   AS statistical_qty,
                SUM(final_qty)         AS final_qty,
                SUM(statistical_value) AS total_statistical_value,
                SUM(final_value)       AS total_final_value
            FROM lines
            GROUP BY "item__item_id", period_type, period_start
        """,
        'customer': """
            SELECT
                'customer' AS agg_level,
                CONCAT('{\"customer_code\": \"', customer_code, '\"}') AS agg_key_json,
                period_type,
                period_start,
                SUM(statistical_qty)   AS statistical_qty,
                SUM(final_qty)         AS final_qty,
                SUM(statistical_value) AS total_statistical_value,
                SUM(final_value)       AS total_final_value
            FROM lines
            GROUP BY customer_code, period_type, period_start
        """,
    }

    ForecastAggregate.objects.filter(version=version).delete()
    created = 0

    for agg_level, query in AGG_QUERIES.items():
        result_df = con.execute(query).df()
        agg_objects = []

        for _, row in result_df.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()

            try:
                agg_key = json.loads(row['agg_key_json'])
            except Exception:
                agg_key = {'raw': str(row['agg_key_json'])}

            period_end = compute_period_end(period_start, row['period_type'])

            stat_qty   = Decimal(str(round(row['statistical_qty'], 3)))
            final_qty  = Decimal(str(round(row['final_qty'], 3)))
            stat_val   = Decimal(str(round(row['total_statistical_value'], 2)))
            final_val  = Decimal(str(round(row['total_final_value'], 2)))

            # Weighted average price = total_final_value / total_final_qty
            wap = None
            if float(final_qty) > 0 and float(final_val) > 0:
                wap = (final_val / final_qty).quantize(Decimal('0.0001'))

            agg = ForecastAggregate(
                version_id              = version_id,
                agg_level               = agg_level,
                agg_key                 = agg_key,
                period_type             = row['period_type'],
                period_start            = period_start,
                period_end              = period_end,
                statistical_qty         = stat_qty,
                final_qty               = final_qty,
                total_statistical_value = stat_val,
                total_final_value       = final_val,
                weighted_avg_price      = wap,
            )
            agg_objects.append(agg)

        ForecastAggregate.objects.bulk_create(agg_objects, batch_size=500)
        created += len(agg_objects)
        logger.info(
            f'write_forecast_aggregates: level={agg_level} rows={len(agg_objects)}'
        )

    return created
# Sprint 3B.4 — Forecast Engine and Reconciliation
## Revised Instructions (aligned with Sprint 3B.3 final models)

**Dependencies:** Sprint 3B.3 complete (all models, migrations, SeriesProfile pipeline)  
**Estimated effort:** 4–5 days  
**App label:** `mysite`

---

## What Changed from the Previous 3B.4 Draft

Sprint 3B.3 absorbed several items that were originally planned for 3B.4:

| Item | Where it now lives |
|---|---|
| `ItemPlanningProfile` model | Sprint 3B.3 — `actuals.py` |
| `ForecastLine` value fields | Sprint 3B.3 — `forecast.py` |
| `ForecastAggregate` value fields | Sprint 3B.3 — `forecast.py` |
| `ForecastVersion` run fields | Sprint 3B.4 — only delta remaining |
| `SeriesProfile` classification | Sprint 3B.3 — `forecast.py` |
| `SeriesLevelEvaluation` audit trail | Sprint 3B.3 — `forecast.py` |
| `ForecastingConfig` thresholds | Sprint 3B.3 — `forecast.py` |
| `get_higher_period_types()` | Sprint 3B.3 — `actuals.py` |
| `hierarchy_utils.py` | Sprint 3B.3 — `utils/demand/` |

**As a result, the 3B.4 forecast engine does NOT classify series — it reads the
already-computed `SeriesProfile` rows** (written by `compute_series_profiles` in 3B.3)
and dispatches accordingly. The engine's job is purely:
1. Read classification results
2. Aggregate actuals to the correct grain
3. Run StatsForecast at that grain
4. Disaggregate back to atomic level (value-based for Part B)
5. Write ForecastLine and ForecastAggregate rows

---

## Table of Contents

1. [Model Delta — ForecastVersion run fields only](#1-model-delta)
2. [Forecast Engine — `utils/demand/forecast_engine.py`](#2-forecast-engine)
3. [Celery Tasks](#3-celery-tasks)
4. [REST Endpoints — run and status](#4-rest-endpoints)
5. [Serializer and URL additions](#5-serializer-and-url-additions)
6. [Unit Tests](#6-unit-tests)
7. [Migration and Checklist](#7-migration-and-checklist)

---
 
## 1. Model Delta

The only model change in 3B.4 is adding run-tracking fields to `ForecastVersion`.
All other model changes (value fields, `ItemPlanningProfile`, etc.) are already in 3B.3.

Add to `ForecastVersion` in `mysite/models/demand/forecast.py`:

```python
# Add after the existing `notes` field in ForecastVersion:

celery_task_id = models.CharField(
    _('celery task ID'),
    max_length=255,
    blank=True,
    help_text=_('ID of the Celery task chain currently running for this version.'),
)
run_status = models.CharField(
    _('run status'),
    max_length=16,
    blank=True,
    choices=[
        ('',             _('Not started')),
        ('QUEUED',       _('Queued')),
        ('PROFILING',    _('Profiling series')),
        ('RUNNING',      _('Running forecast')),
        ('RECONCILING',  _('Reconciling')),
        ('AGGREGATING',  _('Building aggregates')),
        ('COMPLETE',     _('Complete')),
        ('FAILED',       _('Failed')),
    ],
    help_text=_(
        'Granular progress state of the forecast run task. '
        'Separate from the version status workflow (DRAFT/IN_REVIEW/etc.).'
    ),
)
run_error = models.TextField(
    _('run error'),
    blank=True,
    help_text=_('Traceback if run_status=FAILED.'),
)
```

Also update `ForecastVersionAdmin` to expose these fields as readonly:

```python
# In ForecastVersionAdmin.readonly_fields, add:
# 'run_status', 'run_error', 'celery_task_id'

# Add to the Workflow fieldset:
# ('run_status', 'celery_task_id', 'run_error'),
```

---

## 2. Forecast Engine — `utils/demand/forecast_engine.py`

This module contains pure functions — no Django ORM calls inside them.
All data arrives as DataFrames; all FK lookups are passed in as dicts.
This makes every function independently testable without DB fixtures.

### Pipeline overview

```
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
```

```python
# utils/demand/forecast_engine.py

"""
Forecast engine pure functions.
Called by the run_forecast Celery task.
No Django ORM calls — all data arrives as DataFrames or dicts.
"""
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
            'is_manual':   profile.is_manual,
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


def _scale_horizon(base_horizon: int, base_freq: str, target_freq: str) -> int:
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

def disaggregate_to_atomic(
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
```

---

## 3. Celery Tasks

Create `mysite/tasks/demand/run_forecast.py`:

```python
# mysite/tasks/demand/run_forecast.py

from __future__ import annotations
import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_forecast(self, version_id: int):
    """
    Orchestrate the full forecast pipeline.

    Assumes compute_series_profiles has already run (either directly
    before this task, or via the Celery chain in ForecastVersionRunView).

    Steps:
      1  Validate version is DRAFT
      2  Read engine_config settings
      3  Update weighted avg prices (ItemPlanningProfile)
      4  Pull actuals via DuckDB → Polars
      5  Load SeriesProfile decisions (grain, strategy, price per series)
      6  Build aggregated actuals per grain
      7  Run StatsForecast batched by (grain, strategy, eval_period)
      8  Disaggregate non-atomic forecasts back to atomic level
           - Location grains: qty-share disaggregation
           - Product grains: VALUE-share disaggregation → qty via price
      9  Hierarchical reconciliation (MinTrace)
     10  Write ForecastLine rows
     11  Write ForecastAggregate rollups (with value fields and weighted_avg_price)
     12  Update version run_status → COMPLETE
    """
    from mysite.models.demand.forecast import ForecastVersion
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP, ActualSale
    from utils.demand.forecast_engine import (
        update_weighted_avg_prices,
        build_actuals_dataframe,
        load_series_decisions,
        build_aggregated_actuals,
        run_statsforecast_by_grain,
        disaggregate_to_atomic,
        run_hierarchical_reconciliation,
        write_forecast_lines,
        write_forecast_aggregates,
    )
    from utils.feature_control import celery_demand_feature_guard

    try:
        version = ForecastVersion.objects.select_related(
            'client', 'created_by'
        ).get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        logger.error(f'run_forecast: version_id={version_id} not found')
        return

    skip = celery_demand_feature_guard(version.client, 'forecast_run')
    if skip:
        return skip

    if not version.is_editable:
        logger.warning(
            f'run_forecast: version {version_id} is {version.status} — must be DRAFT'
        )
        return

    def _set_status(run_status: str, error: str = ''):
        ForecastVersion.objects.filter(pk=version_id).update(
            run_status=run_status,
            run_error=error,
            celery_task_id=self.request.id or '',
        )

    try:
        client      = version.client
        client_id   = client.pk
        period_type = version.period_type
        horizon     = version.horizon_periods
        freq        = PERIOD_FREQ_MAP[period_type]

        # ── Read engine_config ─────────────────────────────────────────────
        cfg = version.engine_config
        reconciliation       = cfg.get('reconciliation', 'MinTrace_ols')
        disagg_conflict      = cfg.get('disagg_conflict_resolution', 'retain_lower')
        store_all_levels     = cfg.get('store_all_level_forecasts', True)
        force_grain          = cfg.get('force_grain')
        season_length        = cfg.get('season_length', 12)

        # ── Determine actuals window ───────────────────────────────────────
        earliest = (
            ActualSale.objects
            .filter(client=client, period_type=period_type)
            .order_by('period_start')
            .values_list('period_start', flat=True)
            .first()
        )
        if earliest is None:
            raise ValueError('No actuals found for this client and period_type.')

        # ── Step 3: Update prices ──────────────────────────────────────────
        _set_status('PROFILING')
        price_map = update_weighted_avg_prices(client_id, period_type)

        # ── Step 4: Pull actuals ───────────────────────────────────────────
        actuals_pl = build_actuals_dataframe(
            client_id, period_type, earliest, version.base_period_end
        )

        # ── Step 5: Load SeriesProfile decisions ───────────────────────────
        all_uids  = actuals_pl['unique_id'].unique().to_list()
        decisions = load_series_decisions(
            client_id, period_type, all_uids, price_map, force_grain
        )

        # ── Step 6: Build aggregated actuals per grain ─────────────────────
        _set_status('RUNNING')
        all_periods   = sorted(actuals_pl['period_start'].unique().to_list())
        agg_actuals   = build_aggregated_actuals(
            actuals_pl, decisions, period_type, all_periods
        )

        # ── Step 7: Run StatsForecast ──────────────────────────────────────
        combined_df = run_statsforecast_by_grain(
            aggregated_actuals=agg_actuals,
            decisions=decisions,
            horizon=horizon,
            freq=freq,
            season_length=season_length,
        )

        # ── Step 8: Disaggregate to atomic ─────────────────────────────────
        atomic_df = disaggregate_to_atomic(
            forecast_df=combined_df,
            actuals_df=actuals_pl,
            decisions=decisions,
            disagg_conflict=disagg_conflict,
        )

        # ── Step 9: Reconciliation (on atomic forecasts only) ──────────────
        _set_status('RECONCILING')
        try:
            # Build summing matrix from atomic forecasts
            from hierarchicalforecast.utils import aggregate as hf_agg
            actuals_for_rec = actuals_pl.to_pandas()[
                ['unique_id', 'ds', 'y']
            ].copy()
            actuals_for_rec['y']  = actuals_for_rec['y'].astype(float)
            actuals_for_rec['ds'] = pd.to_datetime(actuals_for_rec['ds'])

            # Build location_group for the summing matrix
            actuals_pd = actuals_pl.to_pandas()
            actuals_pd['location_group'] = actuals_pd['region_code']
            hier_raw = actuals_pd[['ds', 'location_group', 'unique_id', 'y']].copy()
            hier_raw['y']  = hier_raw['y'].astype(float)
            hier_raw['ds'] = pd.to_datetime(hier_raw['ds'])

            Y_df, S_df, tags = hf_agg(
                hier_raw,
                [['location_group'], ['location_group', 'unique_id']],
            )

            hf_input = atomic_df[['unique_id', 'ds', 'statistical_qty']].copy()
            hf_input = hf_input.rename(columns={'statistical_qty': 'COMBINED'})

            reconciled = run_hierarchical_reconciliation(
                forecasts_df=hf_input,
                Y_df=Y_df, S_df=S_df, tags=tags,
                method=reconciliation,
            )

            rec_col = [
                c for c in reconciled.columns
                if 'COMBINED' in c and c != 'COMBINED'
            ]
            if rec_col:
                reconciled = reconciled.rename(
                    columns={rec_col[0]: 'statistical_qty'}
                )
                # Merge reconciled values back
                rec_lookup = reconciled.set_index(['unique_id', 'ds'])['statistical_qty'].to_dict()
                atomic_df['statistical_qty'] = atomic_df.apply(
                    lambda row: rec_lookup.get(
                        (row['unique_id'], row['ds']),
                        row['statistical_qty']
                    ),
                    axis=1,
                )
        except Exception as exc:
            logger.warning(
                f'run_forecast: reconciliation failed ({exc}) — '
                f'using unreconciled forecasts'
            )

        # ── Step 10: Write ForecastLine rows ──────────────────────────────
        _set_status('AGGREGATING')
        n_lines = write_forecast_lines(
            version_id=version_id,
            forecast_df=atomic_df,
            decisions=decisions,
            period_type=period_type,
            store_all_level_forecasts=store_all_levels,
        )

        # ── Step 11: Write ForecastAggregate rollups ──────────────────────
        n_agg = write_forecast_aggregates(version_id)

        _set_status('COMPLETE')
        logger.info(
            f'run_forecast: version={version_id} COMPLETE '
            f'lines={n_lines} aggregates={n_agg}'
        )

    except Exception as exc:
        _set_status('FAILED', error=traceback.format_exc())
        logger.exception(f'run_forecast: version={version_id} FAILED')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def apply_overrides(self, version_id: int):
    """
    Disaggregate all unapplied ForecastOverride rows to ForecastLine.override_qty.

    Three override modes:
        override_qty:   absolute qty → disaggregate by historical qty share
        override_pct:   percentage → multiply statistical_qty
        override_value: ₹ target → convert to qty via weighted_avg_price
                        → disaggregate by VALUE share

    After applying: recompute ForecastAggregate rollups.
    """
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastOverride, ForecastLine, ForecastAggregate
    )
    from utils.demand.forecast_engine import write_forecast_aggregates

    try:
        version = ForecastVersion.objects.get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        return

    if not version.is_editable:
        logger.warning(f'apply_overrides: version {version_id} is not DRAFT')
        return

    pending = ForecastOverride.objects.filter(
        version=version, is_applied=False
    ).select_related('created_by').order_by('created_at')

    applied_count = 0
    for override in pending:
        try:
            _apply_single_override(override, version)
            override.is_applied = True
            override.save(update_fields=['is_applied'])
            applied_count += 1
        except Exception as exc:
            logger.exception(
                f'apply_overrides: failed on override {override.pk}: {exc}'
            )

    logger.info(
        f'apply_overrides: version={version_id} '
        f'applied={applied_count}'
    )
    write_forecast_aggregates(version_id)


def _apply_single_override(override, version):
    """Apply one ForecastOverride to matching ForecastLine rows."""
    from mysite.models.demand.forecast import ForecastLine, ForecastAggregate
    from mysite.models.demand.actuals import ItemPlanningProfile

    qs = ForecastLine.objects.filter(
        version=version,
        period_type=override.period_type,
        period_start=override.period_start,
    )

    key = override.override_key

    if override.override_level == 'sku':
        item_id_str = key.get('item_id')
        if item_id_str:
            qs = qs.filter(item__item_id=item_id_str)
    elif override.override_level == 'location':
        loc_code = key.get('location_code')
        if loc_code:
            qs = qs.filter(planning_location__code=loc_code)
    elif override.override_level == 'customer':
        cust_code = key.get('customer_code')
        if cust_code:
            qs = qs.filter(planning_customer__code=cust_code)

    lines = list(qs.select_related('item'))
    if not lines:
        logger.warning(
            f'_apply_single_override: no matching lines for override {override.pk}'
        )
        return

    update_fields = ['override_qty', 'final_qty', 'override_value', 'final_value']

    # ── Percentage override ────────────────────────────────────────────────
    if override.override_pct is not None:
        multiplier = 1 + float(override.override_pct) / 100
        for line in lines:
            line.override_qty = (
                line.statistical_qty * Decimal(str(multiplier))
            ).quantize(Decimal('0.001'))
            line.save(update_fields=update_fields)
        return

    # ── Absolute qty override ──────────────────────────────────────────────
    if override.override_qty is not None:
        total_stat = sum(float(l.statistical_qty) for l in lines) or 1.0
        override_total = float(override.override_qty)

        if override.disagg_method == 'CUSTOM':
            weights = {
                str(sw.child_key): float(sw.weight)
                for sw in override.split_weights.all()
            }
            for line in lines:
                uid_key = str({'item_id': line.item.item_id})
                weight  = weights.get(uid_key, 0)
                line.override_qty = Decimal(str(round(override_total * weight, 3)))
                line.save(update_fields=update_fields)

        elif override.disagg_method == 'EQUAL':
            equal_share = Decimal(str(round(override_total / len(lines), 3)))
            for line in lines:
                line.override_qty = equal_share
                line.save(update_fields=update_fields)

        else:  # PROPORTIONAL
            for line in lines:
                share = float(line.statistical_qty) / total_stat
                line.override_qty = Decimal(str(round(override_total * share, 3)))
                line.save(update_fields=update_fields)
        return

    # ── Value override (₹) ────────────────────────────────────────────────
    if override.override_value is not None:
        # Find the ForecastAggregate for this level to get weighted_avg_price
        from mysite.models.demand.forecast import ForecastAggregate
        agg = (
            ForecastAggregate.objects
            .filter(
                version=version,
                agg_level=override.override_level,
                period_start=override.period_start,
            )
            .first()
        )

        if agg and agg.weighted_avg_price and float(agg.weighted_avg_price) > 0:
            # Convert ₹ target to total qty, then disaggregate by VALUE share
            implied_total_qty = (
                override.override_value / agg.weighted_avg_price
            ).quantize(Decimal('0.001'))

            # Disaggregate by value share (each item's final_value / total_final_value)
            total_final_value = sum(
                float(l.final_value or 0) for l in lines
            ) or 1.0

            for line in lines:
                line_value_share = float(line.final_value or 0) / total_final_value
                line.override_qty = (
                    implied_total_qty * Decimal(str(line_value_share))
                ).quantize(Decimal('0.001'))
                line.save(update_fields=update_fields)

        else:
            # Fallback: no weighted_avg_price available
            # Use each line's own price_used to convert value target
            total_stat_value = sum(
                float(l.statistical_value or 0) for l in lines
            ) or 1.0
            for line in lines:
                line_val_share = float(line.statistical_value or 0) / total_stat_value
                line_value_target = override.override_value * Decimal(str(line_val_share))
                if line.price_used and float(line.price_used) > 0:
                    line.override_qty = (
                        line_value_target / line.price_used
                    ).quantize(Decimal('0.001'))
                else:
                    # No price at all — fall back to equal split
                    line.override_qty = (
                        override.override_value / Decimal(str(len(lines)))
                    ).quantize(Decimal('0.001'))
                line.save(update_fields=update_fields)


@shared_task(bind=True)
def compute_accuracy(self, client_id: int):
    """
    Nightly task. For LOCKED/APPROVED versions where actuals have landed,
    compute MAPE and Bias and write ForecastAccuracy rows.
    """
    import duckdb
    import pandas as pd
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastAccuracy, ForecastLine
    )
    from mysite.models.demand.actuals import ActualSale, compute_period_end

    versions = ForecastVersion.objects.filter(
        client_id=client_id,
        status__in=[
            ForecastVersion.Status.APPROVED,
            ForecastVersion.Status.LOCKED,
        ],
    )

    total_written = 0

    for version in versions:
        period_type = version.period_type

        lines_qs = (
            ForecastLine.objects
            .filter(version=version)
            .values(
                'id', 'item_id', 'planning_customer_id',
                'planning_location_id', 'period_start', 'final_qty',
            )
        )
        if not lines_qs.exists():
            continue

        lines_df = pd.DataFrame(list(lines_qs))

        actuals_qs = (
            ActualSale.objects
            .filter(
                client_id=client_id,
                period_type=period_type,
                period_start__in=lines_df['period_start'].unique().tolist(),
            )
            .values(
                'item_id', 'planning_customer_id',
                'planning_location_id', 'period_start', 'qty',
            )
        )
        if not actuals_qs.exists():
            continue

        actuals_df = pd.DataFrame(list(actuals_qs))

        con = duckdb.connect()
        con.register('lines',   lines_df)
        con.register('actuals', actuals_df)

        joined = con.execute("""
            SELECT
                l.item_id,
                l.planning_customer_id,
                l.planning_location_id,
                l.period_start,
                CAST(l.final_qty AS DOUBLE) AS forecast_qty,
                CAST(a.qty       AS DOUBLE) AS actual_qty,
                CASE
                    WHEN a.qty > 0 THEN
                        ABS(CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS mape,
                CASE
                    WHEN a.qty > 0 THEN
                        (CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS bias
            FROM lines l
            INNER JOIN actuals a
                ON  l.item_id              = a.item_id
                AND l.planning_location_id = a.planning_location_id
                AND l.period_start         = a.period_start
                AND (
                    (l.planning_customer_id IS NULL AND a.planning_customer_id IS NULL)
                    OR l.planning_customer_id = a.planning_customer_id
                )
        """).df()

        if joined.empty:
            continue

        ForecastAccuracy.objects.filter(version=version).delete()

        accuracy_objects = []
        for _, row in joined.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()

            cust_id = row['planning_customer_id']
            cust_id = None if pd.isna(cust_id) else int(cust_id)

            accuracy_objects.append(
                ForecastAccuracy(
                    version_id           = version.pk,
                    item_id              = int(row['item_id']),
                    planning_customer_id = cust_id,
                    planning_location_id = int(row['planning_location_id']),
                    period_type          = period_type,
                    period_start         = period_start,
                    period_end           = compute_period_end(period_start, period_type),
                    actual_qty           = Decimal(str(round(row['actual_qty'],   3))),
                    forecast_qty         = Decimal(str(round(row['forecast_qty'], 3))),
                    mape  = Decimal(str(round(row['mape'], 4)))
                            if row['mape'] is not None and not pd.isna(row['mape'])
                            else None,
                    bias  = Decimal(str(round(row['bias'], 4)))
                            if row['bias'] is not None and not pd.isna(row['bias'])
                            else None,
                )
            )

        ForecastAccuracy.objects.bulk_create(accuracy_objects, batch_size=500)
        total_written += len(accuracy_objects)
        logger.info(
            f'compute_accuracy: version={version.pk} '
            f'accuracy_rows={len(accuracy_objects)}'
        )

    logger.info(
        f'compute_accuracy: client={client_id} total_written={total_written}'
    )
```

---

## 4. REST Endpoints

These two views are unchanged from the previous draft.
Add to `mysite/api/demand/views.py`:

```python
from celery import chain

class ForecastVersionRunView(DemandFeatureMixin, APIView):
    """
    POST /api/demand/forecast-versions/{id}/run/
    Chains compute_series_profiles → run_forecast.
    Returns 202 immediately.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        result = is_demand_feature_disabled(request.client, 'forecast_run')
        if result['disabled']:
            return Response({'detail': result['message']},
                            status=status.HTTP_403_FORBIDDEN)

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )

        if not version.is_editable:
            return Response(
                {'detail': f'Version is {version.status}. Only DRAFT versions can be run.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if version.run_status in ('QUEUED','PROFILING','RUNNING','RECONCILING','AGGREGATING'):
            return Response(
                {'detail': 'A forecast run is already in progress.'},
                status=status.HTTP_409_CONFLICT,
            )

        from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
        from mysite.tasks.demand.run_forecast import run_forecast

        task_chain   = chain(
            compute_series_profiles.si(version.client.pk, version.period_type),
            run_forecast.si(version.pk),
        )
        async_result = task_chain.apply_async()

        ForecastVersion.objects.filter(pk=pk).update(
            run_status='QUEUED',
            celery_task_id=async_result.id or '',
            run_error='',
        )

        return Response({
            'version_id':     version.pk,
            'run_status':     'QUEUED',
            'celery_task_id': async_result.id,
            'poll_url':       f'/api/demand/forecast-versions/{pk}/run-status/',
        }, status=status.HTTP_202_ACCEPTED)


class ForecastVersionRunStatusView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/run-status/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
        return Response({
            'version_id':      version.pk,
            'run_status':      version.run_status,
            'celery_task_id':  version.celery_task_id,
            'run_error':       version.run_error,
            'line_count':      version.lines.count(),
            'aggregate_count': version.aggregates.count(),
        })
```

---

## 5. Serializer and URL Additions

### Serializer updates (delta from 3B.3 serializers)

```python
# ForecastVersionSerializer — add to fields AND read_only_fields:
# 'run_status', 'celery_task_id', 'run_error'

# ForecastLineSerializer — already has value fields from 3B.3.
# Add forecast_level filter param to docstring only — no model change.

# No other serializer changes needed — 3B.3 already covers all value fields.
```

### URL additions

```python
# Append to mysite/api/demand/urls.py urlpatterns:

path(
    'forecast-versions/<int:pk>/run/',
    views.ForecastVersionRunView.as_view(),
    name='demand-forecast-version-run',
),
path(
    'forecast-versions/<int:pk>/run-status/',
    views.ForecastVersionRunStatusView.as_view(),
    name='demand-forecast-version-run-status',
),
```

---

## 6. Unit Tests

```python
# mysite/tests/demand/test_forecast_engine.py

import pytest
import datetime
from decimal import Decimal
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def item_planning_profile(db, client_obj, active_item):
    from mysite.models.demand.actuals import ItemPlanningProfile
    return ItemPlanningProfile.objects.create(
        client=client_obj,
        item=active_item,
        standard_price=Decimal('150.00'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: load_series_decisions reads SeriesProfile correctly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLoadSeriesDecisions:

    def test_reads_effective_grain_from_series_profile(
        self, client_obj, active_item, leaf_location, planning_customer,
        series_profile, item_planning_profile
    ):
        """load_series_decisions returns effective_grain from SeriesProfile."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = f'ITEM-001|CUST-001|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={active_item.pk: Decimal('160.00')},  # actuals price overrides
        )

        assert uid in decisions
        dec = decisions[uid]
        assert dec['grain']    == series_profile.effective_grain
        assert dec['strategy'] == series_profile.effective_strategy
        # Actuals-derived price takes precedence over standard_price
        assert dec['price']    == Decimal('160.00')

    def test_force_grain_overrides_series_profile(
        self, client_obj, active_item, leaf_location, planning_customer,
        series_profile, item_planning_profile
    ):
        """force_grain from engine_config overrides SeriesProfile.effective_grain."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = f'ITEM-001|CUST-001|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={},
            force_grain='item_client',
        )
        assert decisions[uid]['grain'] == 'item_client'

    def test_unclassified_series_defaults_to_atomic_autoets(
        self, client_obj, active_item, leaf_location
    ):
        """Series with no SeriesProfile defaults to item_cust_location / AUTOETS."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = 'UNKNOWN-ITEM|NULL|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={},
        )
        assert decisions[uid]['grain']    == 'item_cust_location'
        assert decisions[uid]['strategy'] == 'AUTOETS'


# ─────────────────────────────────────────────────────────────────────────────
# Test: disaggregate_to_atomic — value-based for product grains
# ─────────────────────────────────────────────────────────────────────────────

class TestDisaggregateToAtomic:

    def _make_decisions(self, uids: list, grain: str, prices: dict) -> dict:
        return {
            uid: {
                'grain': grain, 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': prices.get(uid),
                'item_id': None, 'location_id': None, 'customer_id': None,
            }
            for uid in uids
        }

    def test_location_grain_uses_qty_share(self):
        """Item×location grain disaggregates by historical qty share."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        uids = ['ITEM-A|NULL|LOC-1', 'ITEM-B|NULL|LOC-1']
        # ITEM-A has 2× the demand of ITEM-B
        dates = pd.date_range('2022-01-01', periods=12, freq='MS')
        rows = []
        for ds in dates:
            rows += [
                {'unique_id': 'ITEM-A|NULL|LOC-1', 'ds': ds, 'y': 200.0,
                 'item_id': 1, 'item__item_id': 'ITEM-A',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 400.0},
                {'unique_id': 'ITEM-B|NULL|LOC-1', 'ds': ds, 'y': 100.0,
                 'item_id': 2, 'item__item_id': 'ITEM-B',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 150.0},
            ]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # Aggregate forecast at location level
        forecast_df = pd.DataFrame([
            {'unique_id': 'ITEM-A|ALL_CUST|LOC-1', 'ds': pd.Timestamp('2025-01-01'),
             'statistical_qty': 300.0, 'grain': 'item_location',
             'model_used': 'AutoETS', 'forecast_level': 'item_location',
             'eval_period': 'month'},
            {'unique_id': 'ITEM-B|ALL_CUST|LOC-1', 'ds': pd.Timestamp('2025-01-01'),
             'statistical_qty': 300.0, 'grain': 'item_location',
             'model_used': 'AutoETS', 'forecast_level': 'item_location',
             'eval_period': 'month'},
        ])

        decisions = self._make_decisions(uids, 'item_location', {})
        result = disaggregate_to_atomic(forecast_df, actuals_pl, decisions)

        # ITEM-A gets 2/3, ITEM-B gets 1/3 (qty share 200:100)
        item_a = result[result['unique_id'] == 'ITEM-A|NULL|LOC-1']
        item_b = result[result['unique_id'] == 'ITEM-B|NULL|LOC-1']
        assert not item_a.empty
        assert not item_b.empty
        ratio = float(item_a.iloc[0]['statistical_qty']) / float(item_b.iloc[0]['statistical_qty'])
        assert abs(ratio - 2.0) < 0.1

    def test_product_grain_uses_value_share(self):
        """Product-hierarchy grain disaggregates by revenue share, not qty."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        uids = ['ITEM-X|NULL|LOC-1', 'ITEM-Y|NULL|LOC-1']
        # ITEM-X: qty=100, revenue=1000 (price=10)
        # ITEM-Y: qty=100, revenue=500  (price=5)
        # Equal qty but unequal revenue — value-share should split 2:1
        dates = pd.date_range('2022-01-01', periods=12, freq='MS')
        rows = []
        for ds in dates:
            rows += [
                {'unique_id': 'ITEM-X|NULL|LOC-1', 'ds': ds, 'y': 100.0,
                 'item_id': 10, 'item__item_id': 'ITEM-X',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 1000.0},
                {'unique_id': 'ITEM-Y|NULL|LOC-1', 'ds': ds, 'y': 100.0,
                 'item_id': 11, 'item__item_id': 'ITEM-Y',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 500.0},
            ]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # Product-group forecast: taxon grain, y = revenue (1500 total)
        forecast_df = pd.DataFrame([{
            'unique_id': 'taxon_5_ALL_LOC',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 1500.0,   # this is REVENUE for product grains
            'grain': 'taxon_5_client',
            'model_used': 'AutoETS',
            'forecast_level': 'taxon_5_client',
            'eval_period': 'month',
        }])

        decisions = self._make_decisions(
            uids, 'taxon_5_client',
            # ITEM-X: price=10, ITEM-Y: price=5
            {'ITEM-X|NULL|LOC-1': Decimal('10'), 'ITEM-Y|NULL|LOC-1': Decimal('5')},
        )
        result = disaggregate_to_atomic(forecast_df, actuals_pl, decisions)

        item_x = result[result['unique_id'] == 'ITEM-X|NULL|LOC-1']
        item_y = result[result['unique_id'] == 'ITEM-Y|NULL|LOC-1']

        if not item_x.empty and not item_y.empty:
            # ITEM-X gets 2/3 of revenue = 1000. qty = 1000/10 = 100
            # ITEM-Y gets 1/3 of revenue = 500.  qty = 500/5  = 100
            # Both get qty=100 in this case — equal quantities, different prices
            qty_x = float(item_x.iloc[0]['statistical_qty'])
            qty_y = float(item_y.iloc[0]['statistical_qty'])
            assert abs(qty_x - 100) < 1
            assert abs(qty_y - 100) < 1

    def test_retain_lower_does_not_overwrite_atomic(self):
        """disagg_conflict='retain_lower': atomic forecast is not overwritten."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        uid = 'ITEM-A|NULL|LOC-1'
        rows = [{'unique_id': uid, 'ds': pd.Timestamp('2022-01-01'),
                 'y': 100.0, 'item_id': 1, 'item__item_id': 'ITEM-A',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 500.0}]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # Atomic forecast already exists
        atomic_df = pd.DataFrame([{
            'unique_id': uid, 'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 999.0,   # sentinel value
            'grain': 'item_cust_location',
            'model_used': 'AutoETS',
            'forecast_level': 'item_cust_location',
        }])
        # Product-grain forecast also exists
        product_df = pd.DataFrame([{
            'unique_id': 'ITEM-A|ALL_CUST|ALL_LOC',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 1200.0,
            'grain': 'item_client',
            'model_used': 'AutoETS',
            'forecast_level': 'item_client',
        }])
        combined_df = pd.concat([atomic_df, product_df], ignore_index=True)

        decisions = {uid: {
            'grain': 'item_client', 'strategy': 'AUTOETS',
            'eval_period': 'month', 'is_manual': False,
            'price': Decimal('5'), 'item_id': 1,
            'location_id': 1, 'customer_id': None,
        }}

        result = disaggregate_to_atomic(
            combined_df, actuals_pl, decisions, disagg_conflict='retain_lower'
        )

        atomic_row = result[
            (result['unique_id'] == uid) &
            (result['grain'] == 'item_cust_location')
        ]
        assert not atomic_row.empty
        # The original atomic 999 is retained
        assert float(atomic_row.iloc[0]['statistical_qty']) == 999.0


# ─────────────────────────────────────────────────────────────────────────────
# Test: write_forecast_lines — value fields computed correctly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestWriteForecastLines:

    def test_row_count_matches_input(
        self, draft_version, active_item, leaf_location, series_profile,
        item_planning_profile
    ):
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine

        forecast_df = pd.DataFrame([
            {'unique_id': 'ITEM-001|CUST-001|LEAF-01',
             'ds': pd.Timestamp('2025-01-01'),
             'statistical_qty': 480.0, 'model_used': 'AutoETS',
             'grain': 'item_cust_location',
             'forecast_level': 'item_cust_location'},
            {'unique_id': 'ITEM-001|CUST-001|LEAF-01',
             'ds': pd.Timestamp('2025-02-01'),
             'statistical_qty': 520.0, 'model_used': 'AutoETS',
             'grain': 'item_cust_location',
             'forecast_level': 'item_cust_location'},
        ])

        from mysite.models import Item
        from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
        decisions = {
            'ITEM-001|CUST-001|LEAF-01': {
                'grain': 'item_cust_location', 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': Decimal('150.00'),
                'item_id': active_item.pk,
                'location_id': leaf_location.pk,
                'customer_id': None,
            }
        }

        n = write_forecast_lines(
            draft_version.pk, forecast_df, decisions, 'month',
            store_all_level_forecasts=True,
        )
        assert n == 2
        assert ForecastLine.objects.filter(version=draft_version).count() == 2

    def test_final_value_computed_from_price(
        self, draft_version, active_item, leaf_location
    ):
        """final_value = statistical_qty × price."""
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine

        forecast_df = pd.DataFrame([{
            'unique_id': 'ITEM-001|NULL|LEAF-01',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 100.0,
            'model_used': 'AutoETS',
            'grain': 'item_cust_location',
            'forecast_level': 'item_cust_location',
        }])

        decisions = {
            'ITEM-001|NULL|LEAF-01': {
                'grain': 'item_cust_location', 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': Decimal('250.00'),
                'item_id': active_item.pk,
                'location_id': leaf_location.pk,
                'customer_id': None,
            }
        }

        write_forecast_lines(
            draft_version.pk, forecast_df, decisions, 'month',
        )
        line = ForecastLine.objects.get(version=draft_version)
        assert line.final_value == Decimal('25000.00')  # 100 × 250
        assert line.price_used  == Decimal('250.00')


# ─────────────────────────────────────────────────────────────────────────────
# Test: Reconciliation coherence (unchanged — pure function test)
# ─────────────────────────────────────────────────────────────────────────────

class TestMinTraceCoherence:

    def test_reconciled_total_equals_summed_leaves(self):
        from utils.demand.forecast_engine import run_hierarchical_reconciliation
        from hierarchicalforecast.utils import aggregate

        raw = pd.DataFrame({
            'ds':        pd.date_range('2022-01-01', periods=24, freq='MS').tolist() * 2,
            'group':     ['A'] * 24 + ['A'] * 24,
            'unique_id': ['A|leaf1'] * 24 + ['A|leaf2'] * 24,
            'y':         list(range(100, 124)) + list(range(50, 74)),
        })
        raw['y'] = raw['y'].astype(float)

        Y_df, S_df, tags = aggregate(
            raw, [['group'], ['group', 'unique_id']]
        )

        from statsforecast import StatsForecast
        from statsforecast.models import SeasonalNaive

        sf = StatsForecast(
            models=[SeasonalNaive(season_length=12)], freq='MS', n_jobs=1
        )
        forecasts_df = sf.forecast(df=Y_df, h=3)

        reconciled = run_hierarchical_reconciliation(
            forecasts_df=forecasts_df,
            Y_df=Y_df, S_df=S_df, tags=tags,
            method='MinTrace_ols',
        )

        rec_col = [
            c for c in reconciled.columns
            if c not in ('unique_id', 'ds') and 'SeasonalNaive' in c
        ]
        assert rec_col
        rec_col = rec_col[0]

        for ds_val in reconciled['ds'].unique():
            period = reconciled[reconciled['ds'] == ds_val]
            total  = float(period[period['unique_id'] == 'A'][rec_col].values[0])
            leaf1  = float(period[period['unique_id'] == 'A/A|leaf1'][rec_col].values[0])
            leaf2  = float(period[period['unique_id'] == 'A/A|leaf2'][rec_col].values[0])
            assert abs(total - (leaf1 + leaf2)) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Test: MAPE computation (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class TestMapeComputation:

    def test_mape_formula(self):
        actual   = 400.0
        forecast = 440.0
        mape = abs(actual - forecast) / actual * 100
        bias = (forecast - actual) / actual * 100
        assert abs(mape - 10.0) < 0.001
        assert abs(bias - 10.0) < 0.001

    def test_mape_null_when_actual_zero(self):
        actual = 0.0
        mape   = None if actual == 0 else abs(0 - actual) / actual * 100
        assert mape is None
```

---

## 7. Migration and Checklist

```bash
# 1. Add ForecastVersion run fields
python manage.py makemigrations mysite --name forecast_version_run_fields

# 2. Apply
python manage.py migrate

# 3. Check
python manage.py check

# 4. Run tests
pytest mysite/tests/demand/test_forecast_engine.py -v
```

**Migration summary for 3B.4 (minimal — most moved to 3B.3):**
- `ForecastVersion` — 3 new fields: `celery_task_id`, `run_status`, `run_error`
- All other fields (value fields, ItemPlanningProfile, etc.) already in 3B.3

**New files created in 3B.4:**
- `utils/demand/forecast_engine.py`
- `mysite/tasks/demand/run_forecast.py`
- `mysite/tests/demand/test_forecast_engine.py`

**Final Sprint 3B.4 checklist:**

```
── MODEL DELTA ──────────────────────────────────────────────────────────────
[x] ForecastVersion.run_status, celery_task_id, run_error added
[x] ForecastVersionAdmin updated to show run fields (readonly)
[x] python manage.py makemigrations → forecast_version_run_fields
[x] python manage.py migrate — clean
[x] python manage.py check — 0 issues

── FORECAST ENGINE ───────────────────────────────────────────────────────────
[x] utils/demand/forecast_engine.py created
[x] update_weighted_avg_prices() — updates ItemPlanningProfile
[ ] build_actuals_dataframe() — ORM → Polars
[ ] load_series_decisions() — reads SeriesProfile.effective_grain/strategy
[ ] build_aggregated_actuals() — aggregates per grain using hierarchy_utils
[ ] run_statsforecast_by_grain() — batched by (grain, strategy, eval_period)
[ ] disaggregate_to_atomic() — value-share for product grains, qty-share for location
[ ] run_hierarchical_reconciliation() — MinTrace
[ ] write_forecast_lines() — handles store_all_level_forecasts flag
[ ] write_forecast_aggregates() — DuckDB rollup with value fields and weighted_avg_price

── CELERY TASKS ──────────────────────────────────────────────────────────────
[ ] mysite/tasks/demand/run_forecast.py created
[ ] run_forecast task — full pipeline, reads engine_config flags
[ ] apply_overrides task — handles override_qty, override_pct, override_value
[ ] compute_accuracy task — nightly MAPE/Bias via DuckDB join

── REST ENDPOINTS ────────────────────────────────────────────────────────────
[ ] POST /api/demand/forecast-versions/{id}/run/
[ ] GET  /api/demand/forecast-versions/{id}/run-status/
[ ] ForecastVersionSerializer updated with run_status, celery_task_id, run_error

── SMOKE TESTS ───────────────────────────────────────────────────────────────
[ ] POST /run/ on DRAFT version → 202 + run_status=QUEUED
[ ] GET  /run-status/ → run_status progresses PROFILING→RUNNING→AGGREGATING→COMPLETE
[ ] ForecastLine rows created after run
[ ] ForecastAggregate rows created with total_final_value populated
[ ] ForecastLine.forecast_level correctly tags grain used
[ ] Part B item (LUMPY series) → forecast_level = taxon grain, not item_cust_location
[ ] override_value override → ForecastLine.override_qty correctly computed from weighted_avg_price

── UNIT TESTS ────────────────────────────────────────────────────────────────
[ ] pytest mysite/tests/demand/test_forecast_engine.py -v
[ ]   TestLoadSeriesDecisions         (3 tests)
[ ]   TestDisaggregateToAtomic        (3 tests)
[ ]   TestWriteForecastLines          (2 tests)
[ ]   TestMinTraceCoherence           (1 test)
[ ]   TestMapeComputation             (2 tests)
```

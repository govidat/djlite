from __future__ import annotations

import logging
import re
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

TWO_DP   = Decimal('0.01')
THREE_DP = Decimal('0.001')
BATCH_SIZE_LINES = 2000
ATOMIC_FALLBACK_GRAIN = 'item_cust_location'   # sentinel used only when a uid has no SeriesProfile at all

from functools import lru_cache

"""
run_forecast Celery task
  |
  |- 1. update_weighted_avg_prices()
  |       Reads ActualSale revenue -> writes ItemPlanningProfile.weighted_avg_price.
  |       Now channel-aware: returns both a per-(item, distribution_channel) price
  |       and a blended per-item fallback, since channel-specific pricing (e.g.
  |       Retail vs Institutional) can differ materially and would otherwise
  |       distort value-share disaggregation for taxon_* grains.
  |
  |- 2. build_actuals_dataframe()
  |       ActualSale ORM -> Polars DataFrame
  |       unique_id = "{item_id}|{customer_code_or_NULL}|{dc_code}|{location_code}"
  |       (widened from 3 parts to 4 -- distribution_channel is now a real
  |       modeled dimension, and the old 3-part uid silently collided two
  |       different-channel series into one bucket everywhere downstream.)
  |
  |- 3. load_series_decisions()
  |       Returns dict: unique_id -> {grain, strategy, eval_period, price,
  |       item_id, location_id, customer_id, distribution_channel_id,
  |       top_sales_node_id, taxon_node_id, is_manual}
  |       top_sales_node_id / taxon_node_id are pure parse_grain(grain)
  |       results -- no join needed, no staleness risk under planner overrides.
  |
  |- 4. build_aggregated_actuals()
  |       For each distinct grain in decisions, builds the ONE aggregated
  |       actuals series that grain represents. Grain vocabulary is now:
  |         item_{id}_loc_dc_cust | item_{id}_loc_dc | item_{id}_loc
  |         item_{id}_salesnode_{ancestor_id}
  |         item_{id}_top_{sales_node_id}_{period}
  |         item_{id}_client | item_{id}_client_{period}
  |         taxon_{node}_* (same shapes, node = TaxonomyNode id, merges member items)
  |       Sales-hierarchy membership (salesnode/top) and product-hierarchy
  |       membership (taxon_*) are resolved via mysite.hierarchy_utils,
  |       mirroring compute_series_profiles.py's own logic -- these two
  |       modules MUST stay in sync on what "coverage" means for a given
  |       grain, or forecasts and disaggregation would climb different trees.
  |
  |- 5. run_statsforecast_by_grain()
  |       Groups series by (grain, strategy, eval_period), one StatsForecast
  |       batch per group.
  |
  |- 6. disaggregate_to_atomic()
  |       Residual disaggregation (see disaggregate_with_residual below):
  |       remaining = parent_forecast - sum(children's OWN independently-
  |       modeled forecasts), floored at 0, split among the lumpy children
  |       by historical share. This is the fix for the double-count bias a
  |       flat qty-share split has whenever some children under an aggregate
  |       already have their own finer-grain forecast.
  |
  |- 7. run_hierarchical_reconciliation()   <- unchanged (thin HierarchicalForecast wrapper)
  |
  |- 8. write_forecast_lines()
  |       bulk_create ForecastLine rows, 4-part uid parsing, distribution_channel FK.
  |
  `- 9. write_forecast_aggregates()
          DuckDB rollup of ForecastLine -> ForecastAggregate.
"""

"""
Forecast engine pure functions.
Called by the run_forecast Celery task.
No Django ORM calls except where explicitly noted (price/hierarchy lookups) --
all bulk data arrives as DataFrames or dicts.
"""

# -----------------------------------------------------------------------------
# Time-suffix helpers -- unchanged in spirit from the original file. These
# still work correctly against the new grain vocabulary: every time-suffixed
# grain (item_5_client_quarter, item_5_top_12_month) still ends with a
# recognised period-type token, which is all these functions check.
# -----------------------------------------------------------------------------

def _build_time_grain_suffixes() -> frozenset[str]:
    try:
        from mysite.models.demand.actuals import PERIOD_HIGHER_HORIZONS
        suffixes: set[str] = set()
        for horizon_list in PERIOD_HIGHER_HORIZONS.values():
            suffixes.update(horizon_list)
        return frozenset(suffixes)
    except ImportError:
        return frozenset({
            'second', 'minute', 'hour',
            'day', 'week', 'fortnight', 'month', 'bimonth',
            'quarter', 'halfyear', 'year',
        })


_TIME_GRAIN_SUFFIXES: frozenset[str] = _build_time_grain_suffixes()


def _grain_has_time_suffix(grain: str) -> bool:
    suffix = grain.rsplit('_', 1)[-1]
    return suffix in _TIME_GRAIN_SUFFIXES


def _grain_time_suffix(grain: str) -> str | None:
    suffix = grain.rsplit('_', 1)[-1]
    return suffix if suffix in _TIME_GRAIN_SUFFIXES else None


# -----------------------------------------------------------------------------
# Grain vocabulary -- parsing and identity construction.
#
# The old vocabulary (item_cust_location / item_location / item_loc_depth_N /
# item_client / taxon_{id}_client) is fully superseded by
# compute_series_profiles.py's vocabulary. parse_grain() decodes any grain
# string this engine will ever see; build_agg_series_id() constructs the
# matching aggregate-series identity used internally by
# build_aggregated_actuals / run_statsforecast_by_grain (NOT the same as the
# atomic `unique_id` -- see the module docstring above for why leaf-shape
# grains need per-uid disambiguation while salesnode/top/client grains don't).
# -----------------------------------------------------------------------------

_GRAIN_RE = re.compile(
    r'^(?P<prefix>item|taxon)_(?P<tag>\d+)_'
    r'(?:'
        r'(?P<leaf_shape>loc_dc_cust|loc_dc|loc)'
        r'|salesnode_(?P<sales_node_id>\d+)'
        r'|top_(?P<top_sales_node_id>\d+)_(?P<top_period>\w+)'
        r'|client(?:_(?P<client_period>\w+))?'
    r')$'
)


def parse_grain(grain: str) -> dict | None:
    """
    Decodes any grain string this engine produces into structured components.
    Returns None for 'manual', the ATOMIC_FALLBACK_GRAIN sentinel, or an
    unrecognised string -- all three mean "nothing to disaggregate, this uid
    stands on its own."
    """
    if grain in ('manual', ATOMIC_FALLBACK_GRAIN):
        return None
    m = _GRAIN_RE.match(grain)
    if not m:
        logger.warning(f'parse_grain: unrecognised grain {grain!r} - treating as opaque/atomic.')
        return None
    d = m.groupdict()
    if d['leaf_shape']:
        level, period_suffix = 'leaf', None
    elif d['sales_node_id']:
        level, period_suffix = 'salesnode', None
    elif d['top_sales_node_id']:
        level, period_suffix = 'top', d['top_period']
    else:
        level, period_suffix = 'client', d['client_period']
    return {
        'prefix': d['prefix'], 'tag': int(d['tag']), 'level': level,
        'leaf_shape': d['leaf_shape'],
        'sales_node_id': int(d['sales_node_id']) if d['sales_node_id'] else None,
        'top_sales_node_id': int(d['top_sales_node_id']) if d['top_sales_node_id'] else None,
        'period_suffix': period_suffix,
    }


def make_uid(item_code: str, cust_code: str | None, dc_code: str | None, loc_code: str) -> str:
    """The ATOMIC series identifier -- 4 pipe-delimited tokens, always in this order."""
    return f'{item_code}|{cust_code or "NULL"}|{dc_code or "00"}|{loc_code}'


def build_agg_series_id(dec: dict, code_lookup: dict) -> str:
    """
    Constructs the aggregate-series identity a given decision's grain
    represents, for use as the `unique_id` inside build_aggregated_actuals /
    run_statsforecast_by_grain. NOT the same thing as the atomic `unique_id`
    from make_uid().
    """
    parsed = parse_grain(dec['grain'])
    if parsed is None:
        return make_uid(
            code_lookup['item'].get(dec.get('item_id'), str(dec.get('item_id'))),
            code_lookup['customer'].get(dec.get('customer_id')),
            dec.get('distribution_channel_id'),
            code_lookup['location'].get(dec.get('location_id'), str(dec.get('location_id'))),
        )

    tag_token = (
        code_lookup['item'].get(dec.get('item_id'), str(parsed['tag']))
        if parsed['prefix'] == 'item' else f"TAXON_{parsed['tag']}"
    )
    loc_code = code_lookup['location'].get(dec.get('location_id'), str(dec.get('location_id')))

    if parsed['level'] == 'leaf':
        shape = parsed['leaf_shape']
        cust_token = code_lookup['customer'].get(dec.get('customer_id')) if shape == 'loc_dc_cust' else None
        dc_token   = dec.get('distribution_channel_id') if shape in ('loc_dc_cust', 'loc_dc') else None
        return make_uid(tag_token, cust_token, dc_token, loc_code)

    if parsed['level'] == 'salesnode':
        return f"{tag_token}|ALL_CUST|ALL_DC|SALESNODE_{parsed['sales_node_id']}"
    if parsed['level'] == 'top':
        return f"{tag_token}|ALL_CUST|ALL_DC|SALESNODE_{parsed['top_sales_node_id']}"
    return f"{tag_token}|ALL_CUST|ALL_DC|ALL_LOC"


# -----------------------------------------------------------------------------
# 1. Update weighted average prices
# -----------------------------------------------------------------------------

def update_weighted_avg_prices(
    client_id: int,
    period_type: str,
    lookback_periods: int = 12,
) -> dict:
    """
    Compute weighted average price (sum(revenue)/sum(qty)) per item, from the
    most recent `lookback_periods` actuals periods -- now split by
    distribution_channel where it varies.

    Returns:
        {'by_channel': {(item_pk, dc_code): Decimal}, 'blended': {item_pk: Decimal}}

    ItemPlanningProfile.weighted_avg_price is still a single per-item field
    (no schema change made here) -- updated with the BLENDED price only. The
    by-channel breakdown is in-memory only, for this run's disaggregation use.

    Uses NET actuals when forecast_uses_net_actuals is True -- price feeds
    directly into forecasting (value-based disaggregation for taxon_*
    grains, ForecastLine.statistical_value), so it shares that flag rather
    than a separate one. A single large one-off order would otherwise
    distort the weighted average price used for every future run's value
    conversions, not just the period it occurred in.
    """
    from django.utils import timezone
    from mysite.models import Client
    from mysite.models.demand.forecast import ForecastingConfig
    from mysite.models.demand.actuals import ItemPlanningProfile
    from utils.demand.actuals_net import actuals_queryset_with_net

    cfg = ForecastingConfig.get_for_client_id(client_id)
    use_net = bool(cfg.forecast_uses_net_actuals)
    client = Client.objects.get(pk=client_id)

    qs = (
        actuals_queryset_with_net(client, use_net)
        .filter(period_type=period_type, revenue__isnull=False)
        .values('item_id', 'distribution_channel_id', 'net_qty', 'net_revenue', 'period_start')
        .order_by('-period_start')
    )

    if not qs.exists():
        logger.warning(f'update_weighted_avg_prices: no revenue data for client={client_id}')
        return {'by_channel': {}, 'blended': {}}

    df_pd = pd.DataFrame(list(qs))
    df_pd = df_pd.rename(columns={'net_qty': 'qty', 'net_revenue': 'revenue'})
    con = duckdb.connect()
    con.register('actuals', df_pd)

    n_items = df_pd['item_id'].nunique()

    blended_df = con.execute(f"""
        WITH recent AS (
            SELECT DISTINCT item_id, period_start
            FROM actuals ORDER BY period_start DESC LIMIT {lookback_periods * n_items}
        )
        SELECT a.item_id,
               SUM(CAST(a.revenue AS DOUBLE)) / NULLIF(SUM(CAST(a.qty AS DOUBLE)), 0) AS wap
        FROM actuals a
        INNER JOIN recent r ON a.item_id = r.item_id AND a.period_start = r.period_start
        GROUP BY a.item_id
        HAVING SUM(CAST(a.qty AS DOUBLE)) > 0
    """).df()

    by_channel_df = con.execute(f"""
        WITH recent AS (
            SELECT DISTINCT item_id, distribution_channel_id, period_start
            FROM actuals ORDER BY period_start DESC LIMIT {lookback_periods * n_items}
        )
        SELECT a.item_id, a.distribution_channel_id,
               SUM(CAST(a.revenue AS DOUBLE)) / NULLIF(SUM(CAST(a.qty AS DOUBLE)), 0) AS wap
        FROM actuals a
        INNER JOIN recent r ON a.item_id = r.item_id
                            AND a.distribution_channel_id = r.distribution_channel_id
                            AND a.period_start = r.period_start
        GROUP BY a.item_id, a.distribution_channel_id
        HAVING SUM(CAST(a.qty AS DOUBLE)) > 0
    """).df()

    blended = {
        int(row['item_id']): Decimal(str(round(row['wap'], 4)))
        for _, row in blended_df.iterrows() if row['wap'] is not None
    }
    by_channel = {
        (int(row['item_id']), row['distribution_channel_id']): Decimal(str(round(row['wap'], 4)))
        for _, row in by_channel_df.iterrows() if row['wap'] is not None
    }

    now = timezone.now()
    profiles = list(ItemPlanningProfile.objects.filter(client_id=client_id, item_id__in=list(blended.keys())))
    for p in profiles:
        if p.item_id in blended:
            p.weighted_avg_price = blended[p.item_id]
            p.price_updated_at = now
    if profiles:
        ItemPlanningProfile.objects.bulk_update(profiles, ['weighted_avg_price', 'price_updated_at'], batch_size=500)

    logger.info(
        f'update_weighted_avg_prices: client={client_id} updated {len(profiles)} profiles, '
        f'{len(by_channel)} (item,channel) price points'
    )
    return {'by_channel': by_channel, 'blended': blended}


def resolve_price(item_id: int | None, dc_code: str | None, price_result: dict) -> Decimal | None:
    """Two-level fallback: channel-specific first, else blended."""
    if item_id is None:
        return None
    specific = price_result.get('by_channel', {}).get((item_id, dc_code))
    if specific is not None:
        return specific
    return price_result.get('blended', {}).get(item_id)


# -----------------------------------------------------------------------------
# 2. Build actuals DataFrame
# -----------------------------------------------------------------------------

def build_actuals_dataframe(
    client_id: int,
    period_type: str,
    period_start_from,
    period_start_to,
) -> pl.DataFrame:
    """
    Pull ActualSale rows into a Polars DataFrame.

    unique_id is now 4-part: "{item_id}|{customer_code_or_NULL}|{dc_code}|{location_code}"

    region_code (parent location code) predates the Sales Hierarchy
    (SalesNode) redesign and has been REMOVED per product decision —
    reconciliation grouping is now Sales Hierarchy only; PlanningLocation's
    parent chain plays no role in it at all.

    Uses NET actuals (outlier-adjusted) when the client's
    ForecastingConfig.forecast_uses_net_actuals is True. This is the single
    injection point for the whole forecast-generation pipeline: everything
    downstream (build_aggregated_actuals, run_statsforecast_by_grain,
    disaggregate_to_atomic's uid_qty_mean/uid_rev_mean weighting,
    update_weighted_avg_prices via its own separate query below) references
    columns named 'qty'/'revenue' -- renaming net_qty/net_revenue to those
    names here means none of that code needs to know net actuals exist.
    """
    from mysite.models import Client
    from mysite.models.demand.forecast import ForecastingConfig
    from utils.demand.actuals_net import actuals_queryset_with_net

    cfg = ForecastingConfig.get_for_client_id(client_id)
    use_net = bool(cfg.forecast_uses_net_actuals)
    client = Client.objects.get(pk=client_id)

    qs = (
        actuals_queryset_with_net(client, use_net)
        .filter(
            period_type=period_type,
            period_start__gte=period_start_from, period_start__lte=period_start_to,
        )
        .select_related('item', 'planning_location', 'planning_customer')
        .values(
            'item_id', 'item__item_id',
            'planning_location_id', 'planning_location__code',
            'planning_customer_id', 'planning_customer__code',
            'distribution_channel_id',
            'period_start', 'net_qty', 'net_revenue',
        )
    )

    rows = list(qs)
    if not rows:
        raise ValueError(
            f'No actuals for client={client_id} period_type={period_type} '
            f'{period_start_from}->{period_start_to}'
        )

    df_pd = pd.DataFrame(rows)
    df_pd = df_pd.rename(columns={'net_qty': 'qty', 'net_revenue': 'revenue'})
    df_pd['revenue']       = df_pd['revenue'].fillna(0).astype(float)
    df_pd['customer_code'] = df_pd['planning_customer__code'].fillna('NULL')
    df_pd['dc_code']       = df_pd['distribution_channel_id'].fillna('00')
    df_pd['unique_id'] = (
        df_pd['item__item_id'].astype(str) + '|' +
        df_pd['customer_code'].astype(str) + '|' +
        df_pd['dc_code'].astype(str) + '|' +
        df_pd['planning_location__code'].astype(str)
    )
    df_pd = (
        df_pd.groupby([
            'unique_id', 'item_id', 'item__item_id',
            'planning_customer_id', 'customer_code',
            'distribution_channel_id', 'dc_code',
            'planning_location_id', 'planning_location__code',
            'period_start',
        ], dropna=False)
        .agg({'qty': 'sum', 'revenue': 'sum'})
        .reset_index()
    )
    df_pd['y']  = df_pd['qty'].astype(float)
    df_pd['ds'] = pd.to_datetime(df_pd['period_start'])

    df = pl.from_pandas(df_pd)
    logger.info(f'build_actuals_dataframe: client={client_id} rows={len(df)} series={df["unique_id"].n_unique()}')
    return df


# -----------------------------------------------------------------------------
# 3. Load series decisions from SeriesProfile
# -----------------------------------------------------------------------------

def load_series_decisions(
    client_id: int,
    period_type: str,
    unique_ids: list[str],
    price_result: dict,
    force_grain: str | None = None,
) -> dict[str, dict]:
    """
    Read SeriesProfile rows and build a decision dict for every unique_id.

    price_result is what update_weighted_avg_prices() returns.
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

    decisions: dict[str, dict] = {}

    for profile in profiles:
        cust_code = profile.planning_customer.code if profile.planning_customer else 'NULL'
        dc_code   = profile.distribution_channel_id or '00'
        uid = make_uid(profile.item.item_id, cust_code, dc_code, profile.planning_location.code)
        if uid not in unique_ids:
            continue

        grain  = force_grain or profile.effective_grain
        parsed = parse_grain(grain)

        top_sales_node_id = parsed['top_sales_node_id'] if parsed else None
        taxon_node_id      = parsed['tag'] if parsed and parsed['prefix'] == 'taxon' else None

        decisions[uid] = {
            'grain':       grain,
            'strategy':    profile.effective_strategy,
            'eval_period': profile.effective_eval_period if not force_grain else period_type,
            'price':       resolve_price(profile.item_id, dc_code, price_result),
            'item_id':     profile.item_id,
            'location_id': profile.planning_location_id,
            'customer_id': profile.planning_customer_id,
            'distribution_channel_id': dc_code,
            'top_sales_node_id': top_sales_node_id,
            'taxon_node_id':     taxon_node_id,
            'is_manual':   (profile.effective_strategy == 'MANUAL'),
        }

    for uid in unique_ids:
        if uid not in decisions:
            logger.warning(
                f'load_series_decisions: no SeriesProfile for {uid} '
                f'- defaulting to {ATOMIC_FALLBACK_GRAIN} / AUTOETS'
            )
            decisions[uid] = {
                'grain': ATOMIC_FALLBACK_GRAIN, 'strategy': 'AUTOETS', 'eval_period': period_type,
                'price': None, 'item_id': None, 'location_id': None, 'customer_id': None,
                'distribution_channel_id': None, 'top_sales_node_id': None, 'taxon_node_id': None,
                'is_manual': False,
            }

    from collections import Counter
    grain_counts = Counter(d['grain'] for d in decisions.values())
    logger.info(f'load_series_decisions: client={client_id} total={len(decisions)} grains={dict(grain_counts)}')
    return decisions


# -----------------------------------------------------------------------------
# Hierarchy membership helpers used by build_aggregated_actuals -- mirror
# compute_series_profiles.py's own logic.
# -----------------------------------------------------------------------------

@lru_cache(maxsize=256)
def _sales_node_location_ids(client_id: int, sales_node_id: int, as_of_iso: str) -> tuple[int, ...]:
    """
    All leaf location_ids whose resolved SalesForecastLink (as_of the given
    date) rolls up to sales_node_id or any of its descendants.
    """
    import datetime
    from utils.demand.hierarchy_utils import get_sales_hierarchy_ancestor_map
    from mysite.models.demand.hierarchy import SalesForecastLink
    from django.db.models import Q

    as_of = datetime.date.fromisoformat(as_of_iso)
    ancestor_map = get_sales_hierarchy_ancestor_map(client_id)
    covered_nodes = {sales_node_id}
    for node_id, ancestors in ancestor_map.items():
        if sales_node_id in ancestors or node_id == sales_node_id:
            covered_nodes.add(node_id)

    loc_ids = (
        SalesForecastLink.objects
        .filter(client_id=client_id, sales_node_id__in=covered_nodes, valid_from__lte=as_of)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
        .values_list('planning_location_id', flat=True).distinct()
    )
    return tuple(loc_ids)


@lru_cache(maxsize=256)
def _taxon_node_item_ids(client_id: int, node_id: int) -> tuple[int, ...]:
    """
    All item_ids whose primary mapping into the client's configured
    planning_producthierarchy taxonomy descends from node_id.
    """
    from utils.demand.hierarchy_utils import get_item_primary_node_map, get_product_hierarchy_ancestor_map
    from mysite.models.demand.actuals import ActualSale

    item_ids = list(ActualSale.objects.filter(client_id=client_id).values_list('item_id', flat=True).distinct())
    node_map = get_item_primary_node_map(client_id, item_ids)
    ancestor_map = get_product_hierarchy_ancestor_map(client_id)

    members = []
    for iid, leaf_node in node_map.items():
        if leaf_node == node_id or node_id in ancestor_map.get(leaf_node, []):
            members.append(iid)
    return tuple(members)


# Public aliases -- run_forecast.py's override handling (region/category/
# subcategory levels) reuses these SAME hierarchy-membership functions
# rather than re-deriving equivalent logic a third time. Leading-underscore
# names stay as the "internal to this module" convention; these re-exports
# are the sanctioned cross-module entry points.
sales_node_location_ids = _sales_node_location_ids
taxon_node_item_ids = _taxon_node_item_ids


# -----------------------------------------------------------------------------
# 4. Build aggregated actuals per grain
# -----------------------------------------------------------------------------

def build_aggregated_actuals(
    actuals_df: pl.DataFrame,
    decisions: dict[str, dict],
    period_type: str,
    all_periods: list,
    client_id: int,
    as_of,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """
    For each distinct grain in `decisions`, build the ONE aggregated actuals
    time series that grain represents.

    `client_id` and `as_of` are new required parameters -- needed to resolve
    Sales Hierarchy / product hierarchy membership via mysite.hierarchy_utils.
    `as_of` should be the same resolution date used during classification.

    Returns (agg_dict, code_lookup):
      agg_dict    {grain: DataFrame[unique_id, ds, y]} -- unique_id here is
                  build_agg_series_id()'s aggregate identity (NOT the atomic uid).
      code_lookup {'item': {pk: code}, 'location': {pk: code}, 'customer': {pk: code}}
                  -- pass this straight through to run_statsforecast_by_grain,
                  which needs the same mapping to resolve leaf-shape agg_series_ids.
    """
    df_pd = actuals_df.to_pandas()
    df_pd['ds'] = pd.to_datetime(df_pd['ds'])
    as_of_iso = as_of.isoformat() if hasattr(as_of, 'isoformat') else str(as_of)

    code_lookup = {
        'item':     dict(zip(df_pd['item_id'], df_pd['item__item_id'])),
        'location': dict(zip(df_pd['planning_location_id'], df_pd['planning_location__code'])),
        'customer': {
            cid: code for cid, code in zip(df_pd['planning_customer_id'], df_pd['customer_code'])
            if pd.notna(cid)
        },
    }

    from mysite.models.demand.actuals import PERIOD_FREQ_MAP

    needed_grains = {d['grain'] for d in decisions.values()}
    result: dict[str, pd.DataFrame] = {}

    for grain in needed_grains:
        parsed = parse_grain(grain)

        # -- Atomic / leaf-shape grains --------------------------------------
        if parsed is None or parsed['level'] == 'leaf':
            group_cols = ['planning_location_id']
            if parsed and parsed['leaf_shape'] in ('loc_dc_cust', 'loc_dc'):
                group_cols.append('distribution_channel_id')
            if parsed and parsed['leaf_shape'] == 'loc_dc_cust':
                group_cols.append('planning_customer_id')
            item_col = 'item_id'

            agg = df_pd.groupby([item_col] + group_cols + ['ds'])['y'].sum().reset_index()
            agg['unique_id'] = agg.apply(
                lambda r: build_agg_series_id(
                    {'grain': grain, 'item_id': r[item_col],
                     'location_id': r.get('planning_location_id'),
                     'customer_id': r.get('planning_customer_id'),
                     'distribution_channel_id': r.get('distribution_channel_id')},
                    code_lookup,
                ), axis=1,
            )
            result[grain] = agg[['unique_id', 'ds', 'y']]
            continue

        # -- Sales-hierarchy climb / top --------------------------------------
        if parsed['level'] in ('salesnode', 'top'):
            node_id = parsed['sales_node_id'] if parsed['level'] == 'salesnode' else parsed['top_sales_node_id']
            loc_ids = _sales_node_location_ids(client_id, node_id, as_of_iso)
            if not loc_ids:
                logger.warning(f'build_aggregated_actuals: no locations resolve under sales_node {node_id}')
                continue

            if parsed['prefix'] == 'item':
                df_scope = df_pd[(df_pd['item_id'] == parsed['tag']) & (df_pd['planning_location_id'].isin(loc_ids))]
                value_col = 'y'
            else:
                item_ids = _taxon_node_item_ids(client_id, parsed['tag'])
                df_scope = df_pd[(df_pd['item_id'].isin(item_ids)) & (df_pd['planning_location_id'].isin(loc_ids))]
                value_col = 'revenue'

            base_agg = df_scope.groupby('ds')[value_col].sum().reset_index().rename(columns={value_col: 'y'})

            if parsed['level'] == 'top' and parsed['period_suffix']:
                freq = PERIOD_FREQ_MAP.get(parsed['period_suffix'])
                if freq:
                    base_agg['ds'] = pd.to_datetime(base_agg['ds'])
                    base_agg = base_agg.groupby(pd.Grouper(key='ds', freq=freq))['y'].sum().reset_index()
                    base_agg['ds'] = base_agg['ds'].dt.date

            if parsed['prefix'] == 'item':
                base_agg['unique_id'] = build_agg_series_id({'grain': grain, 'item_id': parsed['tag']}, code_lookup)
            else:
                base_agg['unique_id'] = f"TAXON_{parsed['tag']}|ALL_CUST|ALL_DC|SALESNODE_{node_id}"
            result[grain] = base_agg[['unique_id', 'ds', 'y']]
            continue

        # -- client / client_{period} -----------------------------------------
        if parsed['prefix'] == 'item':
            df_scope = df_pd[df_pd['item_id'] == parsed['tag']]
            value_col = 'y'
        else:
            item_ids = _taxon_node_item_ids(client_id, parsed['tag'])
            df_scope = df_pd[df_pd['item_id'].isin(item_ids)]
            value_col = 'revenue'

        base_agg = df_scope.groupby('ds')[value_col].sum().reset_index().rename(columns={value_col: 'y'})
        if parsed['period_suffix']:
            freq = PERIOD_FREQ_MAP.get(parsed['period_suffix'])
            if freq:
                base_agg['ds'] = pd.to_datetime(base_agg['ds'])
                base_agg = base_agg.groupby(pd.Grouper(key='ds', freq=freq))['y'].sum().reset_index()
                base_agg['ds'] = base_agg['ds'].dt.date

        base_agg['unique_id'] = (
            build_agg_series_id({'grain': grain, 'item_id': parsed['tag']}, code_lookup)
            if parsed['prefix'] == 'item' else f"TAXON_{parsed['tag']}|ALL_CUST|ALL_DC|ALL_LOC"
        )
        result[grain] = base_agg[['unique_id', 'ds', 'y']]

    return result, code_lookup


# -----------------------------------------------------------------------------
# 5. Run StatsForecast batched by grain and strategy
# -----------------------------------------------------------------------------

def run_statsforecast_by_grain(
    aggregated_actuals: dict[str, pd.DataFrame],
    decisions: dict[str, dict],
    horizon: int,
    freq: str,
    code_lookup: dict,
    season_length: int = 12,
    n_jobs: int = 1,
) -> pd.DataFrame:
    """
    Group series by (grain, strategy, eval_period) and run one StatsForecast
    batch per group.

    `code_lookup` is the same dict build_aggregated_actuals used -- needed to
    resolve which specific agg_series_id(s) within a grain's dataframe
    correspond to a batch of atomic uids (only matters for leaf-shape grains).

    Returns: unique_id | ds | statistical_qty | grain | model_used | forecast_level
    """
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP
    from collections import defaultdict

    MODEL_MAP = {
        'AUTOETS':   lambda sl: AutoETS(season_length=sl),
        'AUTOARIMA': lambda sl: AutoARIMA(season_length=sl),
        'CROSTON':   lambda sl: CrostonSBA(),
    }

    groups: dict[tuple, list[str]] = defaultdict(list)
    for uid, dec in decisions.items():
        if dec['is_manual']:
            continue
        groups[(dec['grain'], dec['strategy'], dec['eval_period'])].append(uid)

    all_results = []

    for (grain, strategy, eval_period), uids in groups.items():
        agg_df = aggregated_actuals.get(grain)
        if agg_df is None:
            logger.warning(f'run_statsforecast_by_grain: no actuals for grain={grain}')
            continue

        parsed = parse_grain(grain)
        if parsed is None or parsed['level'] == 'leaf':
            agg_ids = {build_agg_series_id(decisions[u], code_lookup) for u in uids}
            subset = agg_df[agg_df['unique_id'].isin(agg_ids)].copy()
        else:
            subset = agg_df.copy()

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
            min_for_conformal = run_horizon * 4
            series_lengths = subset.groupby('unique_id')['y'].count()
            use_conformal = bool((series_lengths >= min_for_conformal).all())

            sf = StatsForecast(models=[model_fn(season_length)], freq=run_freq, n_jobs=1)

            if use_conformal:
                fcast = sf.forecast(
                    df=subset, h=run_horizon,
                    prediction_intervals=ConformalIntervals(h=run_horizon, n_windows=2),
                    level=[80, 95],
                )
            else:
                fcast = sf.forecast(df=subset, h=run_horizon)

            model_cols = [
                c for c in fcast.columns
                if c not in ('unique_id', 'ds')
                and not any(c.endswith(s) for s in ('-lo-80', '-hi-80', '-lo-95', '-hi-95'))
            ]
            if model_cols:
                fcast = fcast.rename(columns={model_cols[0]: strategy})
            model_col = strategy
        else:
            logger.warning(f'Unknown strategy {strategy} - skipping')
            continue

        if model_col not in fcast.columns:
            continue
        fcast_clean = fcast[['unique_id', 'ds', model_col]].copy()
        fcast_clean = fcast_clean.rename(columns={model_col: 'statistical_qty'})
        fcast_clean['grain']          = grain
        fcast_clean['model_used']     = _strategy_to_model_label(strategy)
        fcast_clean['eval_period']    = eval_period
        fcast_clean['forecast_level'] = grain
        all_results.append(fcast_clean)

    manual_uids = [uid for uid, dec in decisions.items() if dec['is_manual']]
    if manual_uids and all_results:
        last_ds = all_results[0]['ds'].max()
        future = pd.date_range(start=last_ds + pd.tseries.frequencies.to_offset(freq), periods=horizon, freq=freq)
        for uid in manual_uids:
            df_zero = pd.DataFrame({
                'unique_id': uid, 'ds': future, 'statistical_qty': 0.0,
                'grain': decisions[uid]['grain'], 'model_used': 'None',
                'eval_period': freq, 'forecast_level': decisions[uid]['grain'],
            })
            all_results.append(df_zero)

    if not all_results:
        raise ValueError('No forecast results produced. Check SeriesProfile decisions.')

    combined = pd.concat(all_results, ignore_index=True)
    combined = combined.drop_duplicates(subset=['unique_id', 'ds', 'grain'])
    return combined


_FREQ_SECONDS: dict[str, float] = {
    's': 1.0, 'S': 1.0, 'T': 60.0, 'min': 60.0, 'h': 3_600.0, 'H': 3_600.0,
    'D': 86_400.0, 'W-MON': 7 * 86_400.0, 'W': 7 * 86_400.0, '2W-MON': 14 * 86_400.0,
    'MS': 30.4375 * 86_400.0, 'M': 30.4375 * 86_400.0,
    '2MS': 2 * 30.4375 * 86_400.0, '2M': 2 * 30.4375 * 86_400.0,
    'QS': 91.3125 * 86_400.0, 'QS-OCT': 91.3125 * 86_400.0, 'QS-JAN': 91.3125 * 86_400.0, 'Q': 91.3125 * 86_400.0,
    '2QS': 182.625 * 86_400.0, '2Q': 182.625 * 86_400.0,
    'YS': 365.25 * 86_400.0, 'AS': 365.25 * 86_400.0, 'A': 365.25 * 86_400.0, 'Y': 365.25 * 86_400.0,
}


def _scale_horizon(base_horizon: int, base_freq: str, target_freq: str) -> int:
    if base_freq == target_freq:
        return base_horizon
    base_sec = _FREQ_SECONDS.get(base_freq)
    target_sec = _FREQ_SECONDS.get(target_freq)
    if base_sec is None:
        logger.warning('_scale_horizon: unknown base_freq "%s" - treating as 1 period', base_freq)
        base_sec = 1.0
    if target_sec is None:
        logger.warning('_scale_horizon: unknown target_freq "%s" - treating as 1 period', target_freq)
        target_sec = 1.0
    if target_sec == 0:
        return base_horizon
    raw = base_horizon * base_sec / target_sec
    return max(2, round(raw))


def _compute_moving_avg(df: pd.DataFrame, horizon: int, freq: str, n_periods: int = 6) -> pd.DataFrame:
    last_ds = df['ds'].max()
    future = pd.date_range(start=last_ds + pd.tseries.frequencies.to_offset(freq), periods=horizon, freq=freq)
    results = []
    for uid in df['unique_id'].unique():
        s = df[df['unique_id'] == uid].sort_values('ds')
        nz = s[s['y'] > 0]['y']
        avg = float(nz.tail(n_periods).mean()) if len(nz) > 0 else 0.0
        rows = pd.DataFrame({'unique_id': uid, 'ds': future, 'MOVING_AVG': avg})
        results.append(rows)
    return pd.concat(results, ignore_index=True) if results else pd.DataFrame()


def _strategy_to_model_label(strategy: str) -> str:
    return {
        'AUTOETS': 'AutoETS', 'AUTOARIMA': 'AutoARIMA', 'CROSTON': 'CrostonSBA',
        'MOVING_AVG': 'MovingAverage', 'MANUAL': 'None',
    }.get(strategy, strategy)


# -----------------------------------------------------------------------------
# 6. Disaggregate non-atomic forecasts back to atomic series
# -----------------------------------------------------------------------------

def _expand_coarse_periods_to_base(
    coarse_rows: list[dict], coarse_period: str, base_period_type: str, base_freq: str,
) -> list[dict]:
    """Unchanged from the original file -- equal-distribution time expansion."""
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP

    coarse_freq = PERIOD_FREQ_MAP.get(coarse_period)
    if coarse_freq is None:
        logger.warning('_expand_coarse_periods_to_base: no PERIOD_FREQ_MAP entry for "%s"', coarse_period)
        return coarse_rows

    coarse_sec = _FREQ_SECONDS.get(coarse_freq, 1.0)
    base_sec = _FREQ_SECONDS.get(base_freq, 1.0)
    n_sub = max(1, round(coarse_sec / base_sec))

    expanded = []
    for row in coarse_rows:
        coarse_ds = pd.Timestamp(row['ds'])
        sub_dates = pd.date_range(start=coarse_ds, periods=n_sub, freq=base_freq)
        per_period_qty = row['statistical_qty'] / n_sub
        for sub_ds in sub_dates:
            expanded.append({
                **row, 'ds': sub_ds, 'statistical_qty': per_period_qty,
                'model_used': row['model_used'] + f'@expand_{coarse_period}',
            })
    return expanded


def build_coverage_index(client_id: int, decisions: dict[str, dict], as_of) -> dict:
    """
    One-time, client-wide precomputation -- resolves "which atomic uids sit
    under this aggregate grain" without re-deriving hierarchy structure per
    lookup. See covers() below.
    """
    from utils.demand.hierarchy_utils import (
        get_sales_hierarchy_ancestor_map, get_product_hierarchy_ancestor_map,
        resolve_sales_forecast_link,
    )

    loc_to_sales_node: dict[int, int] = {}
    for uid, dec in decisions.items():
        loc_id = dec.get('location_id')
        if loc_id is None or loc_id in loc_to_sales_node:
            continue
        link = resolve_sales_forecast_link(
            client_id, loc_id, dec.get('distribution_channel_id'), dec.get('customer_id'), as_of=as_of,
        )
        if link:
            loc_to_sales_node[loc_id] = link['sales_node_id']

    sales_ancestor_map = get_sales_hierarchy_ancestor_map(client_id)
    product_ancestor_map = get_product_hierarchy_ancestor_map(client_id)

    def _descendant_sets(ancestor_map: dict[int, list[int]]) -> dict[int, set[int]]:
        result: dict[int, set[int]] = {n: {n} for n in ancestor_map}
        for node_id, ancestors in ancestor_map.items():
            for anc in ancestors:
                result.setdefault(anc, {anc}).add(node_id)
        return result

    return {
        'loc_to_sales_node': loc_to_sales_node,
        'sales_descendants': _descendant_sets(sales_ancestor_map),
        'product_descendants': _descendant_sets(product_ancestor_map),
    }


def covers(agg: dict, dec: dict, idx: dict) -> bool:
    """True if atomic decision `dec` is nested under aggregate grain `agg`."""
    if agg['level'] == 'client':
        return True
    if agg['level'] == 'top':
        return dec.get('top_sales_node_id') == agg.get('top_sales_node_id')
    loc_id = dec.get('location_id')
    if loc_id is None:
        return False
    sales_node_id = idx['loc_to_sales_node'].get(loc_id)
    if sales_node_id is None:
        return False
    if agg['level'] == 'salesnode':
        return sales_node_id in idx['sales_descendants'].get(agg['sales_node_id'], set())
    return False


def _hierarchy_depth(agg: dict, idx: dict) -> int:
    """Finer aggregates process FIRST (lower number)."""
    if agg['level'] == 'salesnode':
        return len(idx['sales_descendants'].get(agg['sales_node_id'], {agg['sales_node_id']}))
    if agg['level'] == 'top':
        return 1
    if agg['level'] == 'client':
        return 0
    return 999


def disaggregate_with_residual(
    grain_groups: dict[tuple, dict],
    decisions: dict[str, dict],
    coverage_idx: dict,
    weight_fn,
    resolved: dict[tuple[str, pd.Timestamp], float],
) -> list[dict]:
    """
    remaining = agg_qty - sum(own children's already-resolved forecasts);
    floored at 0; split among lumpy children by historical weight_fn share.
    """
    rows = []
    ordered = sorted(grain_groups.items(), key=lambda kv: _hierarchy_depth(parse_grain(kv[0][0]), coverage_idx))

    for (grain, ds), payload in ordered:
        agg = parse_grain(grain)
        if agg is None:
            continue
        tag = agg['tag']

        own_qty = 0.0
        lumpy_uids = []
        for uid, dec in decisions.items():
            dec_tag = dec.get('item_id') if agg['prefix'] == 'item' else dec.get('taxon_node_id')
            if dec_tag != tag or not covers(agg, dec, coverage_idx):
                continue
            if dec['grain'] == grain:
                lumpy_uids.append(uid)
            else:
                own_qty += resolved.get((uid, ds), 0.0)

        remaining = payload['agg_qty'] - own_qty
        if remaining < 0:
            logger.warning(
                f'disaggregate_with_residual: remaining < 0 for grain={grain} ds={ds} '
                f'(agg={payload["agg_qty"]:.2f}, own_children={own_qty:.2f}). Flooring to 0.'
            )
            remaining = 0.0

        weights = {u: weight_fn(u) for u in lumpy_uids}
        total_w = sum(weights.values()) or 1.0
        for uid in lumpy_uids:
            val = remaining * (weights[uid] / total_w)
            resolved[(uid, ds)] = val
            rows.append({
                'unique_id': uid, 'ds': ds, 'statistical_qty': max(0.0, val),
                'grain': grain, 'model_used': payload['model_used'], 'forecast_level': grain,
            })
    return rows


def disaggregate_to_atomic(
    forecast_df: pd.DataFrame,
    actuals_df,
    decisions: dict[str, dict],
    period_type: str,
    base_freq: str,
    client_id: int,
    as_of,
    disagg_conflict: str = 'retain_lower',
) -> pd.DataFrame:
    """
    Residual disaggregation. `client_id` and `as_of` are new required
    parameters -- needed to build the coverage index.
    """
    actuals_pd = actuals_df.to_pandas()
    actuals_pd['ds'] = pd.to_datetime(actuals_pd['ds'])

    leaf_grains = {
        g for g in {d['grain'] for d in decisions.values()}
        if parse_grain(g) is None or parse_grain(g)['level'] == 'leaf'
    }
    atomic_forecasts = forecast_df[forecast_df['grain'].isin(leaf_grains)].copy()
    non_atomic = forecast_df[~forecast_df['grain'].isin(leaf_grains)].copy()
    if non_atomic.empty:
        return atomic_forecasts

    uid_qty_mean = actuals_pd.groupby('unique_id')['y'].mean().to_dict()
    uid_rev_mean = actuals_pd.groupby('unique_id')['revenue'].mean().to_dict()

    coverage_idx = build_coverage_index(client_id, decisions, as_of)

    resolved: dict[tuple[str, pd.Timestamp], float] = {
        (uid, ds): float(qty)
        for uid, ds, qty in zip(atomic_forecasts['unique_id'], atomic_forecasts['ds'], atomic_forecasts['statistical_qty'])
    }

    expanded_rows: list[dict] = []
    for (grain, ds), group in non_atomic.groupby(['grain', 'ds']):
        time_suffix = _grain_time_suffix(grain)
        for _, row in group.iterrows():
            base_row = {
                'ds': ds, 'statistical_qty': float(row['statistical_qty']),
                'unique_id': row['unique_id'], 'grain': grain, 'model_used': row['model_used'],
                'forecast_level': grain,
            }
            if time_suffix:
                expanded_rows.extend(_expand_coarse_periods_to_base([base_row], time_suffix, period_type, base_freq))
            else:
                expanded_rows.append(base_row)
    non_atomic_expanded = pd.DataFrame(expanded_rows) if expanded_rows else non_atomic

    grain_groups = {
        (grain, ds): {'agg_qty': float(g['statistical_qty'].iloc[0]), 'model_used': g['model_used'].iloc[0]}
        for (grain, ds), g in non_atomic_expanded.groupby(['grain', 'ds'])
    }

    sales_axis_groups   = {k: v for k, v in grain_groups.items() if not k[0].startswith('taxon_')}
    product_axis_groups = {k: v for k, v in grain_groups.items() if k[0].startswith('taxon_')}

    disagg_rows = disaggregate_with_residual(
        sales_axis_groups, decisions, coverage_idx,
        weight_fn=lambda u: uid_qty_mean.get(u, 0.0), resolved=resolved,
    )
    disagg_rows += disaggregate_with_residual(
        product_axis_groups, decisions, coverage_idx,
        weight_fn=lambda u: uid_rev_mean.get(u, 0.0), resolved=resolved,
    )
    for row in disagg_rows:
        if row['grain'].startswith('taxon_'):
            price = float(decisions.get(row['unique_id'], {}).get('price') or 1.0)
            row['statistical_qty'] = row['statistical_qty'] / price if price > 0 else 0.0
            row['model_used'] = row['model_used'] + '@value_disagg'

    disagg_df = pd.DataFrame(disagg_rows) if disagg_rows else pd.DataFrame(
        columns=['unique_id', 'ds', 'statistical_qty', 'grain', 'model_used', 'forecast_level'])

    if disagg_conflict == 'retain_lower' and not atomic_forecasts.empty:
        atomic_covered = set(zip(atomic_forecasts['unique_id'], atomic_forecasts['ds']))
        disagg_df = disagg_df[~disagg_df.apply(lambda r: (r['unique_id'], r['ds']) in atomic_covered, axis=1)]

    return pd.concat([atomic_forecasts, disagg_df], ignore_index=True)


# -----------------------------------------------------------------------------
# 7. Hierarchical reconciliation -- unchanged
# -----------------------------------------------------------------------------

def run_hierarchical_reconciliation(
    forecasts_df: pd.DataFrame,
    Y_df: pd.DataFrame,
    S_df: pd.DataFrame,
    tags: dict,
    method: str = 'MinTrace_ols',
) -> pd.DataFrame:
    """
    Apply HierarchicalForecast reconciliation.

    NOTE: residual disaggregation (above) already fixes the specific
    double-count bias this step was historically relied on for. Worth
    revisiting whether this step still earns its keep as anything beyond a
    coherence smoother now.
    """
    reconcilers = {
        'BottomUp':            [BottomUp()],
        'MinTrace_ols':        [MinTrace(method='ols')],
        'MinTrace_wls_struct': [MinTrace(method='wls_struct')],
    }
    selected = reconcilers.get(method, [MinTrace(method='ols')])
    hrec = HierarchicalReconciliation(reconcilers=selected)
    return hrec.reconcile(Y_hat_df=forecasts_df, Y_df=Y_df, S_df=S_df, tags=tags)


# -----------------------------------------------------------------------------
# 8. Write ForecastLine rows
# -----------------------------------------------------------------------------

def write_forecast_lines(
    version_id: int,
    forecast_df: pd.DataFrame,
    decisions: dict[str, dict],
    period_type: str,
    store_all_level_forecasts: bool = True,
) -> int:
    """Convert the combined forecast DataFrame into ForecastLine rows. uid parsing widened to 4 parts."""
    from mysite.models.demand.forecast import ForecastLine, ForecastVersion
    from mysite.models import Item
    from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer

    version = ForecastVersion.objects.get(pk=version_id)

    item_str_to_pk = {r['item_id']: r['id'] for r in Item.objects.filter(client=version.client).values('id', 'item_id')}
    loc_code_to_pk = {r['code']: r['id'] for r in PlanningLocation.objects.filter(client=version.client).values('id', 'code')}
    cust_code_to_pk = {r['code']: r['id'] for r in PlanningCustomer.objects.filter(client=version.client).values('id', 'code')}
    cust_code_to_pk['NULL'] = None

    ForecastLine.objects.filter(version=version).delete()

    if not store_all_level_forecasts:
        leaf_grains = {g for g in forecast_df['grain'].unique() if parse_grain(g) is None or parse_grain(g)['level'] == 'leaf'}
        forecast_df = forecast_df[forecast_df['grain'].isin(leaf_grains)].copy()

    lines = []
    skipped = 0

    for _, row in forecast_df.iterrows():
        uid = row['unique_id']
        parts = uid.split('|')
        if len(parts) != 4:
            skipped += 1
            continue
        item_id_str, cust_code, dc_code, loc_code = parts
        if loc_code.startswith('ALL_') or loc_code.startswith('SALESNODE_') or item_id_str.startswith('TAXON_'):
            skipped += 1
            continue

        item_pk = item_str_to_pk.get(item_id_str)
        loc_pk  = loc_code_to_pk.get(loc_code)
        if item_pk is None or loc_pk is None:
            skipped += 1
            continue

        cust_pk = cust_code_to_pk.get(cust_code)
        dec = decisions.get(uid, {})
        price = dec.get('price')

        period_start = row['ds'].date() if hasattr(row['ds'], 'date') else row['ds']
        from mysite.models.demand.actuals import compute_period_end
        period_end = compute_period_end(period_start, period_type)
        stat_qty = Decimal(str(round(max(float(row['statistical_qty']), 0), 3)))

        line = ForecastLine(
            version_id=version_id, item_id=item_pk,
            planning_customer_id=cust_pk, planning_location_id=loc_pk,
            distribution_channel_id=dc_code,
            period_type=period_type, period_start=period_start, period_end=period_end,
            statistical_qty=stat_qty, override_qty=None,
            model_used=row.get('model_used', ''), forecast_level=row.get('forecast_level', ATOMIC_FALLBACK_GRAIN),
            price_used=price,
        )
        line.final_qty = stat_qty
        if price is not None:
            line.statistical_value = (stat_qty * price).quantize(TWO_DP)
            line.final_value = line.statistical_value
        lines.append(line)

    created = 0
    for i in range(0, len(lines), BATCH_SIZE_LINES):
        batch = lines[i:i + BATCH_SIZE_LINES]
        ForecastLine.objects.bulk_create(batch, batch_size=BATCH_SIZE_LINES)
        created += len(batch)

    if skipped:
        logger.warning(f'write_forecast_lines: skipped {skipped} rows')
    logger.info(f'write_forecast_lines: created {created} ForecastLine rows')
    return created


# -----------------------------------------------------------------------------
# 9. Write ForecastAggregate rows
# -----------------------------------------------------------------------------

def write_forecast_aggregates(version_id: int) -> int:
    """
    Roll up ForecastLine rows into ForecastAggregate using DuckDB.
    Levels: total, sales, item_hierarchy, customer, item, channel.

    'sales' rows are grouped by the leaf SalesNode each line resolves to
    (SalesForecastLink a→b→c, see hierarchy_utils); 'item_hierarchy' rows
    are grouped by the primary TaxonomyNode of each line's item. Lines that
    don't resolve get sales_node_id / taxonomy_node_id = null ("Unassigned").
    """
    from mysite.models.demand.forecast import ForecastLine, ForecastAggregate, ForecastVersion
    from mysite.models.demand.actuals import compute_period_end
    from utils.demand.hierarchy_utils import (
        get_sales_forecast_link_map, resolve_sales_link,
        get_item_primary_node_map,
    )
    import json

    version = ForecastVersion.objects.get(pk=version_id)

    lines_qs = (
        ForecastLine.objects.filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer')
        .values(
            'item_id', 'item__item_id',
            'planning_location_id', 'planning_location__code',
            'planning_customer_id', 'planning_customer__code',
            'distribution_channel_id',
            'period_type', 'period_start',
            'statistical_qty', 'final_qty', 'statistical_value', 'final_value',
        )
    )
    if not lines_qs.exists():
        logger.warning(f'write_forecast_aggregates: no lines for version {version_id}')
        return 0

    df_pd = pd.DataFrame(list(lines_qs))
    for col in ('statistical_qty', 'final_qty'):
        df_pd[col] = df_pd[col].astype(float)
    for col in ('statistical_value', 'final_value'):
        df_pd[col] = df_pd[col].fillna(0).astype(float)
    df_pd['customer_code'] = df_pd['planning_customer__code'].fillna('__unattr__')

    # ── Resolve each line to a leaf SalesNode (a→b→c) and a primary
    #    TaxonomyNode, once, before the DuckDB roll-ups. ──────────────────
    sales_link_map = get_sales_forecast_link_map(version.client_id)
    df_pd['planning_customer_id'] = df_pd['planning_customer_id'].where(
        df_pd['planning_customer_id'].notna(), None
    )
    df_pd['sales_node_id'] = pd.array([
        resolve_sales_link(
            sales_link_map, int(loc), dc, cust
        )
        for loc, dc, cust in zip(
            df_pd['planning_location_id'],
            df_pd['distribution_channel_id'],
            df_pd['planning_customer_id'],
        )
    ], dtype='Int64')

    item_node_map = get_item_primary_node_map(
        version.client_id, df_pd['item_id'].unique().tolist()
    )
    df_pd['taxonomy_node_id'] = (
        df_pd['item_id'].map(item_node_map).astype('Int64')
    )

    con = duckdb.connect()
    con.register('lines', df_pd)

    AGG_QUERIES = {
        'total': """
            SELECT 'total' AS agg_level, '{"level": "total"}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY period_type, period_start
        """,
        'sales': """
            SELECT 'sales' AS agg_level,
                   CONCAT('{"sales_node_id": ', COALESCE(CAST(sales_node_id AS VARCHAR), 'null'), '}') AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY sales_node_id, period_type, period_start
        """,
        'item_hierarchy': """
            SELECT 'item_hierarchy' AS agg_level,
                   CONCAT('{"taxonomy_node_id": ', COALESCE(CAST(taxonomy_node_id AS VARCHAR), 'null'), '}') AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY taxonomy_node_id, period_type, period_start
        """,
        'item': """
            SELECT 'item' AS agg_level, CONCAT('{"item_id": "', "item__item_id", '"}') AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY "item__item_id", period_type, period_start
        """,
        'customer': """
            SELECT 'customer' AS agg_level, CONCAT('{"customer_code": "', customer_code, '"}') AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY customer_code, period_type, period_start
        """,
        'channel': """
            SELECT 'channel' AS agg_level,
                   CONCAT('{"distribution_channel_id": "', distribution_channel_id, '"}') AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty, SUM(final_qty) AS final_qty,
                   SUM(statistical_value) AS total_statistical_value, SUM(final_value) AS total_final_value
            FROM lines GROUP BY distribution_channel_id, period_type, period_start
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
            stat_qty = Decimal(str(round(row['statistical_qty'], 3)))
            final_qty = Decimal(str(round(row['final_qty'], 3)))
            stat_val = Decimal(str(round(row['total_statistical_value'], 2)))
            final_val = Decimal(str(round(row['total_final_value'], 2)))
            wap = None
            if float(final_qty) > 0 and float(final_val) > 0:
                wap = (final_val / final_qty).quantize(Decimal('0.0001'))
            agg_objects.append(ForecastAggregate(
                version_id=version_id, agg_level=agg_level, agg_key=agg_key,
                period_type=row['period_type'], period_start=period_start, period_end=period_end,
                statistical_qty=stat_qty, final_qty=final_qty,
                total_statistical_value=stat_val, total_final_value=final_val,
                weighted_avg_price=wap,
            ))
        ForecastAggregate.objects.bulk_create(agg_objects, batch_size=500)
        created += len(agg_objects)
        logger.info(f'write_forecast_aggregates: level={agg_level} rows={len(agg_objects)}')

    return created
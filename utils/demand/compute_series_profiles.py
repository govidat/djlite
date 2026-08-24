from __future__ import annotations
import logging
from decimal import Decimal

import numpy as np
import pandas as pd
import duckdb

from utils.demand.hierarchy_utils import (
    client_has_sales_hierarchy,
    get_sales_hierarchy_ancestor_map,
    get_item_hierarchy_chains_bulk,
)

logger = logging.getLogger(__name__)

DEMAND_CLASSES = ['ZERO', 'INSUFFICIENT', 'SMOOTH', 'ERRATIC', 'INTERMITTENT']
STRATEGIES     = ['MANUAL', 'MOVING_AVG', 'AUTOETS', 'AUTOARIMA', 'CROSTON']


# ─────────────────────────────────────────────────────────────────────────────
# Bulk loaders — each is ONE query for the whole client, not one per series.
# ─────────────────────────────────────────────────────────────────────────────

def _load_actuals(con, client_id: int, period_type: str) -> None:
    """
    Registers 'actuals_raw' with columns: item_id, planning_location_id,
    distribution_channel_id, planning_customer_id, period_start, qty.
    Pulled once via the ORM into a DataFrame, handed to DuckDB from there.

    Uses NET actuals (outlier-adjusted) when the client's
    ForecastingConfig.forecast_uses_net_actuals is True — classification and
    forecasting are the same concern (deciding a grain, then fitting a model
    on that grain's history), so they share this flag rather than having
    classification silently run on raw data while forecasting uses net.
    An unconfirmed outlier candidate has no effect either way — netting
    only applies where ActualSaleOutlierAdjustment.status == 'CONFIRMED'.
    """
    from mysite.models.demand.forecast import ForecastingConfig
    from mysite.models import Client
    from utils.demand.actuals_net import actuals_queryset_with_net

    cfg = ForecastingConfig.get_for_client_id(client_id)
    use_net = bool(cfg.forecast_uses_net_actuals)
    use_scheme_net = bool(cfg.scheme_net_actuals)
    use_sub = bool(cfg.use_item_lifecycle)
    client = Client.objects.get(pk=client_id)

    qs = actuals_queryset_with_net(client, use_net, use_scheme_net=use_scheme_net,
                                    use_substitution=use_sub).filter(period_type=period_type)
    item_key = 'eff_item_id' if use_sub else 'item_id'
    rows = qs.values(
        item_key, 'planning_location_id', 'distribution_channel_id',
        'planning_customer_id', 'period_start', 'net_qty',
    )
    df = pd.DataFrame.from_records(rows)
    if df.empty:
        df = pd.DataFrame(columns=[
            item_key, 'planning_location_id', 'distribution_channel_id',
            'planning_customer_id', 'period_start', 'net_qty',
        ])
    if use_sub and item_key in df.columns and item_key != 'item_id':
        df = df.rename(columns={item_key: 'item_id'})
    df = df.rename(columns={'net_qty': 'qty'})   # everything downstream references 'qty'
    df['qty'] = df['qty'].astype(float)
    con.register('actuals_raw', df)


def _resolve_links(con, client_id: int, as_of) -> None:
    """
    Registers 'sales_links' (SalesForecastLink rows active as_of the given
    date — the "pragmatic approach": one snapshot for the whole run, not a
    per-period join) and builds 'actuals' = actuals_raw LEFT JOIN'd against
    the a -> b -> c precedence, tagged with sales_node_id / link_type.
    link_type NULL means no link at all for this leaf_location as_of that
    date — the degraded case, handled explicitly downstream (item_client
    fallback), not silently folded into shape 'c'.
    """
    from django.db.models import Q
    from mysite.models.demand.hierarchy import SalesForecastLink

    link_rows = (
        SalesForecastLink.objects
        .filter(client_id=client_id, valid_from__lte=as_of)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
        .values('planning_location_id', 'distribution_channel_id', 'planning_customer_id', 'sales_node_id')
    )
    link_df = pd.DataFrame.from_records(link_rows)
    if link_df.empty:
        link_df = pd.DataFrame(columns=[
            'planning_location_id', 'distribution_channel_id', 'planning_customer_id', 'sales_node_id',
        ])
    con.register('sales_links', link_df)

    con.execute("""
        CREATE OR REPLACE VIEW actuals AS
        SELECT
            a.*,
            COALESCE(la.sales_node_id, lb.sales_node_id, lc.sales_node_id) AS sales_node_id,
            CASE
                WHEN la.sales_node_id IS NOT NULL THEN 'a'
                WHEN lb.sales_node_id IS NOT NULL THEN 'b'
                WHEN lc.sales_node_id IS NOT NULL THEN 'c'
                ELSE NULL
            END AS link_type
        FROM actuals_raw a
        LEFT JOIN sales_links la
            ON la.planning_location_id = a.planning_location_id
           AND la.distribution_channel_id = a.distribution_channel_id
           AND la.planning_customer_id = a.planning_customer_id
        LEFT JOIN sales_links lb
            ON lb.planning_location_id = a.planning_location_id
           AND lb.distribution_channel_id = a.distribution_channel_id
           AND lb.planning_customer_id IS NULL
        LEFT JOIN sales_links lc
            ON lc.planning_location_id = a.planning_location_id
           AND lc.distribution_channel_id IS NULL
           AND lc.planning_customer_id IS NULL
    """)


def _register_item_hierarchy(con, client_id: int) -> pd.DataFrame:
    """
    Long-format {item_id, level, grain_prefix, node_tag} — one row per
    (item, item-hierarchy level), built once via get_item_hierarchy_chains_bulk
    (itself one query, not one per item).
    """
    from mysite.models.demand.actuals import ActualSale

    item_ids = list(
        ActualSale.objects.filter(client_id=client_id).values_list('item_id', flat=True).distinct()
    )
    chains = get_item_hierarchy_chains_bulk(client_id, item_ids)

    records = []
    for item_id, chain in chains.items():
        for entry in chain:
            records.append({
                'item_id': item_id,
                'level': entry['level'],
                'grain_prefix': entry['grain_prefix'],
                'node_tag': item_id if entry['grain_prefix'] == 'item' else entry['node_id'],
            })
    df = pd.DataFrame.from_records(records) if records else pd.DataFrame(
        columns=['item_id', 'level', 'grain_prefix', 'node_tag'])
    con.register('item_levels', df)
    return df


def _sales_ancestor_long_df(client_id: int) -> pd.DataFrame:
    """One row per (sales_node_id, climb_depth, ancestor_id); climb_depth=1
    is the immediate parent, increasing toward the root."""
    ancestor_map = get_sales_hierarchy_ancestor_map(client_id)  # {node_id: [root...parent]}
    records = []
    for node_id, ancestors in ancestor_map.items():
        climb = list(reversed(ancestors))  # parent, grandparent, ..., root
        for depth, anc_id in enumerate(climb, start=1):
            records.append({'sales_node_id': node_id, 'climb_depth': depth, 'ancestor_id': anc_id})
    return pd.DataFrame.from_records(records) if records else pd.DataFrame(
        columns=['sales_node_id', 'climb_depth', 'ancestor_id'])


def _top_ancestor_map(client_id: int) -> pd.DataFrame:
    """
    {sales_node_id -> its ultimate root ancestor}. A node with NO ancestors
    IS the root, so it maps to itself — this matters: a naive
    max(climb_depth) derivation silently drops root-level nodes (they have
    no ancestor rows at all), which would wrongly exclude series linked
    directly to a root SalesNode from the time-rollup step.
    """
    ancestor_map = get_sales_hierarchy_ancestor_map(client_id)  # {node_id: [root...parent]}
    records = [
        {'sales_node_id': node_id, 'top_ancestor_id': (ancestors[0] if ancestors else node_id)}
        for node_id, ancestors in ancestor_map.items()
    ]
    return pd.DataFrame.from_records(records) if records else pd.DataFrame(
        columns=['sales_node_id', 'top_ancestor_id'])


# ─────────────────────────────────────────────────────────────────────────────
# Vectorized classification — two-stage aggregation is mandatory:
# (1) collapse to (group, period) sums FIRST, (2) THEN compute nonzero_periods
# /mean/std off the collapsed series. Skipping stage 1 overcounts periods
# whenever a group merges multiple atomic rows into one period bucket
# (shape b/c dropping customer/channel, or any time roll-up).
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_and_classify(con, group_cols: list[str], where_sql: str,
                             total_periods: int, adi_threshold: float, cv2_threshold: float,
                             min_nonzero: int, from_view: str = 'level_actuals',
                             period_expr: str = 'period_start') -> pd.DataFrame:
    cols = ', '.join(group_cols)
    q = f"""
        WITH bucketed AS (
            SELECT {cols}, {period_expr} AS period_bucket, SUM(qty) AS qty
            FROM {from_view}
            WHERE {where_sql}
            GROUP BY {cols}, {period_expr}
        )
        SELECT {cols},
               COUNT(*) FILTER (WHERE qty > 0)          AS nonzero_periods,
               SUM(qty)                                  AS total_qty,
               AVG(qty) FILTER (WHERE qty > 0)            AS mean_qty,
               STDDEV_SAMP(qty) FILTER (WHERE qty > 0)     AS std_qty
        FROM bucketed
        GROUP BY {cols}
    """
    df = con.execute(q).df()
    if df.empty:
        return df

    df['zero_rate'] = 1 - df['nonzero_periods'] / total_periods
    with np.errstate(divide='ignore', invalid='ignore'):
        df['adi'] = total_periods / df['nonzero_periods'].replace(0, np.nan)
        std = df['std_qty'].fillna(0.0)
        mean = df['mean_qty'].replace(0, np.nan)
        df['cv2'] = ((std / mean) ** 2).fillna(0.0)

    conditions = [
        df['nonzero_periods'] == 0,
        df['nonzero_periods'] < min_nonzero,
        (df['adi'] < adi_threshold) & (df['cv2'] < cv2_threshold),
        (df['adi'] < adi_threshold),
        (df['cv2'] < cv2_threshold),
    ]
    df['demand_class'] = np.select(conditions, DEMAND_CLASSES, default='LUMPY')
    df['recommended_strategy'] = np.select(conditions, STRATEGIES, default='')
    df['is_forecastable'] = ~df['demand_class'].isin(['LUMPY', 'INSUFFICIENT', 'ZERO'])
    df.loc[df['nonzero_periods'] == 0, 'adi'] = None
    df.loc[df['nonzero_periods'] == 0, 'cv2'] = None
    return df


def _metrics_from_row(row) -> dict:
    return {
        'total_periods': None,   # constant, filled in by caller
        'nonzero_periods': int(row['nonzero_periods']),
        'total_qty': Decimal(str(row['total_qty'])),
        'adi': Decimal(str(row['adi'])) if pd.notna(row.get('adi')) else None,
        'cv2': Decimal(str(row['cv2'])) if pd.notna(row.get('cv2')) else None,
        'zero_rate': Decimal(str(round(row['zero_rate'], 4))),
        'demand_class': row['demand_class'],
        'recommended_strategy': row['recommended_strategy'],
    }


def _duckdb_date_trunc_unit(period_type: str) -> str:
    return {'week': 'week', 'fortnight': 'week', 'month': 'month',
            'quarter': 'quarter', 'halfyear': 'quarter', 'year': 'year'}.get(period_type, 'month')


def _time_horizons_for(period_type: str, steps: int) -> list[str]:
    chain = {
        'day':   ['week', 'fortnight', 'month', 'quarter', 'halfyear'],
        'week':  ['month', 'quarter', 'halfyear'],
        'month': ['quarter', 'halfyear', 'year'],
    }.get(period_type, [])
    return chain[:steps]


def compute_total_periods(period_type: str, analysis_from, analysis_to) -> int:
    """Number of period buckets in the analysis window — constant across
    every series, used as the ADI denominator's ceiling."""
    days = (analysis_to - analysis_from).days + 1
    per_period_days = {'day': 1, 'week': 7, 'fortnight': 14, 'month': 30,
                        'quarter': 91, 'halfyear': 182, 'year': 365}.get(period_type, 30)
    return max(1, round(days / per_period_days))


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: leaf grain, split by resolved link shape (a/b/c). Rows with
# link_type IS NULL (no SalesForecastLink at all as_of the resolution date)
# fold into the shape-'c' pass — location-only grouping is valid regardless
# of whether a link exists, since it doesn't depend on channel/customer
# resolution. Only steps 2/3(a) require an actual resolved sales_node_id.
# ─────────────────────────────────────────────────────────────────────────────

def _accept_and_resolve(con, df: pd.DataFrame, shape: str, key_cols: list[str],
                         where_for_resolve: str, accepted: list[dict], grain_suffix: str,
                         grain_fn=None):
    if df.empty:
        return
    ok = df[df['is_forecastable']]
    if ok.empty:
        return

    for _, row in ok.iterrows():
        key = {'grain_prefix': row['grain_prefix'], 'node_tag': row['node_tag']}
        for c in key_cols:
            if c not in ('grain_prefix', 'node_tag'):
                key[c] = row[c]
        grain = grain_fn(row) if grain_fn else f"{row['grain_prefix']}_{row['node_tag']}_{grain_suffix}"
        accepted.append({'key': key, 'grain': grain, 'metrics': _metrics_from_row(row)})

    con.register('_ok', ok[key_cols])
    join_conds = []
    for c in key_cols:
        if c in ('grain_prefix', 'node_tag'):
            join_conds.append(f'a.{c} = o.{c}')
        else:
            join_conds.append(f'a.{c} IS NOT DISTINCT FROM o.{c}')
    join_sql = ' AND '.join(join_conds)
    con.execute(f"""
        INSERT INTO resolved_keys
        SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
        FROM level_actuals a
        JOIN _ok o ON {join_sql}
        WHERE {where_for_resolve}
    """)


def _run_step1(con, adi_t, cv2_t, min_nz, total_periods, accepted):
    df_a = _aggregate_and_classify(
        con, ['grain_prefix', 'node_tag', 'planning_location_id',
              'distribution_channel_id', 'planning_customer_id'],
        "link_type = 'a'", total_periods, adi_t, cv2_t, min_nz,
    )
    _accept_and_resolve(
        con, df_a, 'a',
        ['grain_prefix', 'node_tag', 'planning_location_id', 'distribution_channel_id', 'planning_customer_id'],
        'TRUE', accepted, 'loc_dc_cust',
    )

    df_b = _aggregate_and_classify(
        con, ['grain_prefix', 'node_tag', 'planning_location_id', 'distribution_channel_id'],
        "link_type = 'b'", total_periods, adi_t, cv2_t, min_nz,
    )
    _accept_and_resolve(
        con, df_b, 'b',
        ['grain_prefix', 'node_tag', 'planning_location_id', 'distribution_channel_id'],
        'TRUE', accepted, 'loc_dc',
    )

    df_c = _aggregate_and_classify(
        con, ['grain_prefix', 'node_tag', 'planning_location_id'],
        "(link_type = 'c' OR link_type IS NULL)", total_periods, adi_t, cv2_t, min_nz,
    )
    _accept_and_resolve(
        con, df_c, 'c', ['grain_prefix', 'node_tag', 'planning_location_id'],
        'TRUE', accepted, 'loc',
    )


def _run_step2_climb(con, sales_ancestors_df: pd.DataFrame, adi_t, cv2_t, min_nz, total_periods, accepted):
    if sales_ancestors_df.empty:
        return
    for depth in sorted(sales_ancestors_df['climb_depth'].unique()):
        view_sql = f"""
            (SELECT la.*, sa.ancestor_id
             FROM level_actuals la
             JOIN sales_ancestors sa ON sa.sales_node_id = la.sales_node_id AND sa.climb_depth = {depth}
             WHERE la.sales_node_id IS NOT NULL)
        """
        df = _aggregate_and_classify(
            con, ['grain_prefix', 'node_tag', 'ancestor_id'], 'TRUE', total_periods,
            adi_t, cv2_t, min_nz, from_view=view_sql,
        )
        if df.empty:
            continue
        ok = df[df['is_forecastable']]
        if ok.empty:
            continue
        for _, row in ok.iterrows():
            grain = f"{row['grain_prefix']}_{row['node_tag']}_salesnode_{row['ancestor_id']}"
            accepted.append({
                'key': {'grain_prefix': row['grain_prefix'], 'node_tag': row['node_tag'],
                        'sales_node_id': row['ancestor_id']},
                'grain': grain, 'metrics': _metrics_from_row(row),
            })
        con.register('_ok_sn', ok[['grain_prefix', 'node_tag', 'ancestor_id']])
        con.execute(f"""
            INSERT INTO resolved_keys
            SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
            FROM level_actuals a
            JOIN sales_ancestors sa ON sa.sales_node_id = a.sales_node_id AND sa.climb_depth = {depth}
            JOIN _ok_sn o ON o.grain_prefix = a.grain_prefix AND o.node_tag = a.node_tag
                          AND o.ancestor_id = sa.ancestor_id
        """)


def _run_step3(con, top_ancestor_df: pd.DataFrame, time_horizons: list[str],
               adi_t, cv2_t, min_nz, total_periods, accepted):
    """
    (a) rows WITH a resolved sales_node_id: time roll-up at the TOP of
        their sales hierarchy.
    (b) rows with NO link at all (degraded, incl. clients with no Sales
        Hierarchy configured): item_client roll-up (drop location
        entirely), THEN item_client_{period} — requirement 3's fallback.
    """
    if not top_ancestor_df.empty and time_horizons:
        con.register('top_nodes', top_ancestor_df)
        for h in time_horizons:
            unit = _duckdb_date_trunc_unit(h)
            view_sql = """
                (SELECT la.*, tn.top_ancestor_id
                 FROM level_actuals la
                 JOIN top_nodes tn ON tn.sales_node_id = la.sales_node_id
                 WHERE la.sales_node_id IS NOT NULL)
            """
            df = _aggregate_and_classify(
                con, ['grain_prefix', 'node_tag', 'top_ancestor_id'], 'TRUE', total_periods,
                adi_t, cv2_t, min_nz, from_view=view_sql,
                period_expr=f"date_trunc('{unit}', period_start)",
            )
            if df.empty:
                continue
            ok = df[df['is_forecastable']]
            if ok.empty:
                continue
            for _, row in ok.iterrows():
                grain = f"{row['grain_prefix']}_{row['node_tag']}_top_{h}"
                accepted.append({
                    'key': {'grain_prefix': row['grain_prefix'], 'node_tag': row['node_tag'],
                            'sales_node_id': row['top_ancestor_id'], 'period_type': h},
                    'grain': grain, 'metrics': _metrics_from_row(row),
                })
            con.register('_ok_top', ok[['grain_prefix', 'node_tag']])
            con.execute("""
                INSERT INTO resolved_keys
                SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
                FROM level_actuals a
                JOIN _ok_top o ON a.grain_prefix = o.grain_prefix AND a.node_tag = o.node_tag
                WHERE a.sales_node_id IS NOT NULL
            """)

    # ── degraded branch: item_client, then item_client_{period} ──────────────
    df_client = _aggregate_and_classify(
        con, ['grain_prefix', 'node_tag'], 'sales_node_id IS NULL', total_periods,
        adi_t, cv2_t, min_nz,
    )
    if not df_client.empty:
        ok = df_client[df_client['is_forecastable']]
        if not ok.empty:
            for _, row in ok.iterrows():
                grain = f"{row['grain_prefix']}_{row['node_tag']}_client"
                accepted.append({
                    'key': {'grain_prefix': row['grain_prefix'], 'node_tag': row['node_tag']},
                    'grain': grain, 'metrics': _metrics_from_row(row),
                })
            con.register('_ok_client', ok[['grain_prefix', 'node_tag']])
            con.execute("""
                INSERT INTO resolved_keys
                SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
                FROM level_actuals a
                JOIN _ok_client o ON a.grain_prefix = o.grain_prefix AND a.node_tag = o.node_tag
                WHERE a.sales_node_id IS NULL
            """)

    for h in time_horizons:
        unit = _duckdb_date_trunc_unit(h)
        df_t = _aggregate_and_classify(
            con, ['grain_prefix', 'node_tag'], 'sales_node_id IS NULL', total_periods,
            adi_t, cv2_t, min_nz, period_expr=f"date_trunc('{unit}', period_start)",
        )
        if df_t.empty:
            continue
        ok_t = df_t[df_t['is_forecastable']]
        if ok_t.empty:
            continue
        for _, row in ok_t.iterrows():
            grain = f"{row['grain_prefix']}_{row['node_tag']}_client_{h}"
            accepted.append({
                'key': {'grain_prefix': row['grain_prefix'], 'node_tag': row['node_tag'], 'period_type': h},
                'grain': grain, 'metrics': _metrics_from_row(row),
            })
        con.register('_ok_client_t', ok_t[['grain_prefix', 'node_tag']])
        con.execute("""
            INSERT INTO resolved_keys
            SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
            FROM level_actuals a
            JOIN _ok_client_t o ON a.grain_prefix = o.grain_prefix AND a.node_tag = o.node_tag
            WHERE a.sales_node_id IS NULL
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — item hierarchy OUTER (level 0..k, finest -> coarsest),
# sales-side cascade INNER, per level.
# ─────────────────────────────────────────────────────────────────────────────

def run_for_client(client_id: int, period_type: str, analysis_from, analysis_to) -> dict:
    """
    Returns {'results': [...], 'item_hierarchy': item_levels_df}.

    'results' is one {key, grain, metrics} dict per resolved series
    (including MANUAL fallbacks for anything never resolved).

    'item_hierarchy' is the long-format {item_id, level, grain_prefix,
    node_tag} DataFrame built once for this run — persist_results needs it
    to expand a taxon-level acceptance (one row covering a whole product
    group) back out into one SeriesProfile per member item. Returning it
    here avoids recomputing it from scratch in persist_results.
    """
    from mysite.models.demand.forecast import ForecastingConfig

    cfg = ForecastingConfig.get_for_client_id(client_id)
    adi_t, cv2_t, min_nz = float(cfg.adi_threshold), float(cfg.cv2_threshold), cfg.min_nonzero_periods
    time_horizons = _time_horizons_for(period_type, cfg.time_horizon_steps)
    total_periods = compute_total_periods(period_type, analysis_from, analysis_to)

    has_sh = client_has_sales_hierarchy(client_id)
    if not has_sh:
        logger.warning(
            f'run_for_client: client_id={client_id} has no Sales Hierarchy configured. '
            f'All series use the degraded fallback: item_loc -> item_client -> item_client_{{period}}.'
        )

    con = duckdb.connect()
    _load_actuals(con, client_id, period_type)
    _resolve_links(con, client_id, as_of=analysis_to)   # pragmatic approach — one snapshot
    item_levels_df = _register_item_hierarchy(con, client_id)
    sales_ancestors_df = _sales_ancestor_long_df(client_id) if has_sh else pd.DataFrame(
        columns=['sales_node_id', 'climb_depth', 'ancestor_id'])
    top_ancestor_df = _top_ancestor_map(client_id) if has_sh else pd.DataFrame(
        columns=['sales_node_id', 'top_ancestor_id'])
    con.register('sales_ancestors', sales_ancestors_df)

    max_item_level = int(item_levels_df['level'].max()) if not item_levels_df.empty else 0

    accepted: list[dict] = []
    con.execute("""
        CREATE OR REPLACE TABLE resolved_keys (
            item_id INTEGER, planning_location_id INTEGER,
            distribution_channel_id VARCHAR, planning_customer_id INTEGER
        )
    """)

    for level in range(0, max_item_level + 1):
        level_items = item_levels_df[item_levels_df['level'] == level]
        if level_items.empty:
            continue
        con.register('this_level', level_items[['item_id', 'grain_prefix', 'node_tag']])

        # level_actuals is a VIEW referencing resolved_keys, so it dynamically
        # reflects every INSERT made by earlier stages within this same loop
        # iteration — no need to rebuild it between step1/step2/step3.
        con.execute("""
            CREATE OR REPLACE VIEW level_actuals AS
            SELECT a.*, tl.grain_prefix, tl.node_tag
            FROM actuals a
            JOIN this_level tl ON tl.item_id = a.item_id
            LEFT JOIN resolved_keys rk
              ON rk.item_id = a.item_id AND rk.planning_location_id = a.planning_location_id
             AND rk.distribution_channel_id IS NOT DISTINCT FROM a.distribution_channel_id
             AND rk.planning_customer_id IS NOT DISTINCT FROM a.planning_customer_id
            WHERE rk.item_id IS NULL
        """)

        _run_step1(con, adi_t, cv2_t, min_nz, total_periods, accepted)
        if has_sh:
            _run_step2_climb(con, sales_ancestors_df, adi_t, cv2_t, min_nz, total_periods, accepted)
        _run_step3(con, top_ancestor_df, time_horizons, adi_t, cv2_t, min_nz, total_periods, accepted)
        # anything still unresolved escalates to level+1 automatically —
        # level_actuals is rebuilt fresh next iteration against the grown
        # resolved_keys table.

    manual_df = con.execute("""
        SELECT DISTINCT a.item_id, a.planning_location_id, a.distribution_channel_id, a.planning_customer_id
        FROM actuals a
        LEFT JOIN resolved_keys rk
          ON rk.item_id = a.item_id AND rk.planning_location_id = a.planning_location_id
         AND rk.distribution_channel_id IS NOT DISTINCT FROM a.distribution_channel_id
         AND rk.planning_customer_id IS NOT DISTINCT FROM a.planning_customer_id
        WHERE rk.item_id IS NULL
    """).df()
    for _, row in manual_df.iterrows():
        accepted.append({
            'key': row.to_dict(), 'grain': 'manual',
            'metrics': {
                'total_periods': total_periods, 'nonzero_periods': 0, 'total_qty': Decimal('0'),
                'adi': None, 'cv2': None, 'zero_rate': Decimal('1'),
                'demand_class': 'LUMPY', 'recommended_strategy': 'MANUAL',
            },
        })

    con.close()
    for e in accepted:
        if e['metrics'].get('total_periods') is None:
            e['metrics']['total_periods'] = total_periods
    return {'results': accepted, 'item_hierarchy': item_levels_df}


# ─────────────────────────────────────────────────────────────────────────────
# Persistence — bulk_create, not one .create() per row. At 12K items this is
# the difference between ~200K individual INSERTs and a handful of batched
# ones.
# ─────────────────────────────────────────────────────────────────────────────

def persist_results(client_id: int, period_type: str, analysis_from, analysis_to,
                     run_output: dict, batch_size: int = 2000) -> None:
    """
    run_output is exactly what run_for_client() returns:
    {'results': [...], 'item_hierarchy': item_levels_df}.

    Writes:
      - one SeriesLevelEvaluation row per accepted series (bulk_create)
      - one SeriesProfile row per (item, location, channel, customer) —
        including, for a taxon-level acceptance, ONE ROW PER MEMBER ITEM
        under that taxonomy node, all sharing the same chosen_grain. See
        the long comment below — this is the fix for the gap flagged
        previously: without this expansion, member items would have NO
        SeriesProfile row at all and forecast_engine.load_series_decisions()
        would silently default them to atomic AutoETS, discarding the
        product-hierarchy roll-up decision entirely.
    """
    from mysite.models.demand.forecast import SeriesLevelEvaluation, SeriesProfile

    results = run_output['results']
    item_levels_df = run_output['item_hierarchy']

    # ── SeriesLevelEvaluation: straight bulk_create, index-aligned with `results` ──
    eval_rows = []
    for r in results:
        m, k = r['metrics'], r['key']
        eval_rows.append(SeriesLevelEvaluation(
            client_id=client_id,
            item_id=k.get('item_id') or (k.get('node_tag') if k.get('grain_prefix') == 'item' else None),
            planning_customer_id=k.get('planning_customer_id'),
            period_type=period_type, grain=r['grain'], evaluation_key=k,
            eval_period_type=k.get('period_type', period_type),
            analysis_from=analysis_from, analysis_to=analysis_to,
            total_periods=m['total_periods'], nonzero_periods=m['nonzero_periods'],
            total_qty=m['total_qty'], adi=m['adi'], cv2=m['cv2'], zero_rate=m['zero_rate'],
            demand_class=m['demand_class'], is_accepted=True,
            recommended_strategy=m.get('recommended_strategy', ''),
        ))
    # bulk_create returns the same objects with .pk populated on backends that
    # support RETURNING (Postgres does, since Django 3.0) — index-aligned with
    # `results` because eval_rows was built in the same order. On backends
    # without RETURNING support, eval_row.pk stays None below and
    # chosen_evaluation_id is simply left unset — degrades gracefully, doesn't
    # raise, but confirm your DB backend before relying on that FK being populated.
    created_evals = SeriesLevelEvaluation.objects.bulk_create(eval_rows, batch_size=batch_size)

    # ── Build item -> node membership once, from the hierarchy already
    #    computed during run_for_client (not a fresh query) ─────────────────
    # A taxon-level grain (e.g. 'taxon_5_loc') was accepted for node_tag=5 —
    # its members are every item whose OWN ancestor chain passes through
    # node 5 at some level, i.e. every row in item_levels_df with
    # grain_prefix='taxon' and node_tag==5, REGARDLESS of which level that
    # was recorded at. This is deliberately NOT a plain
    # "ItemTaxonomyNode.filter(node_id=5)" query — that would only catch
    # items mapped DIRECTLY to node 5, missing items whose primary leaf node
    # is a finer descendant of 5 (the normal case for a category-level node).
    taxon_members: dict[int, list[int]] = {}
    if not item_levels_df.empty:
        taxon_rows = item_levels_df[item_levels_df['grain_prefix'] == 'taxon']
        for node_tag, grp in taxon_rows.groupby('node_tag'):
            taxon_members[node_tag] = grp['item_id'].unique().tolist()

    profile_rows = []
    for r, eval_row in zip(results, created_evals):
        m, k = r['metrics'], r['key']
        if 'planning_location_id' not in k:
            continue  # sales-node / item_client / manual-without-location grains —
                       # not representable as a single leaf-location SeriesProfile row.

        # NOT-NULL fix: shape 'c' and every sales-hierarchy-climb / top /
        # client grain groups WITHOUT distribution_channel_id in its key —
        # that means "spans every channel", which maps to the '00' default,
        # not to a missing/NULL value. SeriesProfile.distribution_channel
        # has no null=True, so leaving this as k.get(...) (None) would raise
        # an IntegrityError on save for every non-shape-'a'/'b' series.
        dc_id = k.get('distribution_channel_id') or '00'

        common = dict(
            client_id=client_id,
            planning_customer_id=k.get('planning_customer_id'),
            planning_location_id=k['planning_location_id'],
            distribution_channel_id=dc_id,
            period_type=period_type,
            analysis_from=analysis_from, analysis_to=analysis_to,
            chosen_evaluation_id=eval_row.pk,
            chosen_grain=r['grain'], chosen_demand_class=m['demand_class'],
            chosen_strategy=m.get('recommended_strategy', ''),
            chosen_eval_period=k.get('period_type', period_type),
            total_periods=m['total_periods'], nonzero_periods=m['nonzero_periods'],
            total_qty=m['total_qty'], adi=m['adi'], cv2=m['cv2'], zero_rate=m['zero_rate'],
            demand_class_atomic=m['demand_class'],
        )

        if k.get('grain_prefix') == 'item':
            profile_rows.append(SeriesProfile(item_id=k['node_tag'], **common))
        else:
            # taxon-level acceptance — expand to every member item sharing
            # this same location/channel/customer key, all pointing at the
            # SAME chosen_grain string. forecast_engine's disaggregation
            # step (which already groups atomic uids by matching
            # decisions[uid]['grain']) is what actually splits this shared
            # forecast back out per item using historical share — this loop
            # only ensures every member item HAS a SeriesProfile row to be
            # found by that grouping in the first place.
            member_items = taxon_members.get(k['node_tag'], [])
            if not member_items:
                logger.warning(
                    f'persist_results: taxon node {k["node_tag"]} accepted at grain '
                    f'{r["grain"]!r} has no member items in item_hierarchy — nothing written.'
                )
            for item_id in member_items:
                profile_rows.append(SeriesProfile(item_id=item_id, **common))

    # update_conflicts requires Django 4.1+ and a real DB-level unique
    # constraint matching unique_fields exactly (SeriesProfile.Meta.unique_together
    # already covers this combination). chosen_evaluation is included in
    # update_fields so re-running persist_results for the same window
    # re-points existing rows at the newest evaluation rather than leaving
    # them stale.
    SeriesProfile.objects.bulk_create(
        profile_rows,
        update_conflicts=True,
        unique_fields=['client', 'item', 'planning_customer', 'planning_location',
                        'distribution_channel', 'period_type'],
        update_fields=[
            'analysis_from', 'analysis_to', 'chosen_evaluation',
            'chosen_grain', 'chosen_demand_class', 'chosen_strategy', 'chosen_eval_period',
            'total_periods', 'nonzero_periods', 'total_qty', 'adi', 'cv2', 'zero_rate',
            'demand_class_atomic',
        ],
        batch_size=batch_size,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible entry point — keeps the old name/call shape so existing
# callers (Celery task, management commands, etc.) don't all need editing at
# once. Delegates to run_for_client() + persist_results() internally.
#
# IMPORTANT: I don't have your original compute_series_profiles() signature
# in front of me right now (it was from earlier in this conversation and
# isn't in my current context) — this wrapper assumes
# (client_id, period_type, analysis_from, analysis_to), matching every other
# entry point in this file. If your real call sites pass different
# parameter names, a Client instance instead of client_id, keyword args in a
# different order, or expect a specific return value (e.g. a queryset, a
# count, or None), paste one actual call site and I'll match this wrapper to
# it exactly rather than you having to adapt every caller.
# ─────────────────────────────────────────────────────────────────────────────

def compute_series_profiles(client_id: int, period_type: str, analysis_from, analysis_to,
                             batch_size: int = 2000):
    """
    Drop-in replacement for the original compute_series_profiles() entry
    point. Runs the full classification cascade and persists results,
    matching whatever the old single-call version did end to end.

    Returns the same dict run_for_client() returns
    ({'results': [...], 'item_hierarchy': item_levels_df}) in case any
    caller inspected the return value — if your old function returned
    something else (a count, a queryset, None), tell me and I'll adjust
    this wrapper's return instead of changing every call site.
    """
    run_output = run_for_client(client_id, period_type, analysis_from, analysis_to)
    persist_results(client_id, period_type, analysis_from, analysis_to, run_output, batch_size=batch_size)
    return run_output
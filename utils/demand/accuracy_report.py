# utils/demand/accuracy_report.py
"""
Weighted accuracy roll-up and hierarchy drill support.

Leaf accuracy rows (ForecastAccuracy) are aggregated numerator-first so the
reported MAPE is a qty-weighted WMAPE (Σ|forecast − actual| / Σactual × 100)
and Bias (Σ(forecast − actual) / Σactual × 100), plus value-weighted
equivalents over actual_value / forecast_value.

Hierarchy drill surfaces the same metrics at every level of the Location
tree (client → region → … → leaf → items) and the product Taxonomy
(Segment → Family → Class → Brick → items). Both navigators are driven by
the materialized paths already stored on PlanningLocation and TaxonomyNode,
so aggregation is always "roll everything under this node".
"""
from __future__ import annotations

import pandas as pd
from django.db.models import Q

from mysite.models.demand.forecast import ForecastAccuracy, ForecastingConfig
from mysite.models.demand.hierarchy import PlanningLocation
from mysite.models.catalogue import TaxonomyNode, ItemTaxonomyNode
from utils.demand.hierarchy_utils import (
    get_sales_forecast_link_map,
    get_sales_node_subtree_ids,
    resolve_sales_link,
)

# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

METRIC_KEYS = (
    'record_count', 'graded_count',
    'n_items',
    'sum_actual', 'sum_forecast', 'wmape', 'wbias', 'over_forecast_pct',
    'value_count', 'sum_value_actual', 'sum_value_forecast',
    'value_mape', 'value_bias',
)

EMPTY_METRICS = dict.fromkeys(METRIC_KEYS, None)
EMPTY_METRICS['record_count'] = 0
EMPTY_METRICS['graded_count'] = 0
EMPTY_METRICS['n_items'] = 0
EMPTY_METRICS['value_count'] = 0


def _path_segments(path):
    """Materialized-path → tuple of segments (both '/' and '.' separators)."""
    if not path:
        return ()
    return tuple(p for p in path.replace('.', '/').split('/') if p)


def _path_under(path, prefix):
    """
    True when the materialized path is at or below the prefix, compared by
    segment so sibling paths never collide (e.g. '1/5/' vs '1/50/').
    """
    segs, pre = _path_segments(path), _path_segments(prefix)
    return len(segs) >= len(pre) and segs[:len(pre)] == pre


def _fmt(v):
    """Round to 2dp for display; None for missing/non-finite values."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if pd.isna(f) or f in (float('inf'), float('-inf')):
        return None
    return round(f, 2)


def compute_metrics(df: pd.DataFrame) -> dict:
    """
    Weighted metrics over an accuracy frame with columns actual_qty,
    forecast_qty, actual_value, forecast_value (numeric or coercible).

    Qty metrics use rows where actual_qty > 0 (matches per-row MAPE which is
    NULL when actual = 0). Value metrics use rows where actual_value > 0.
    """
    m = dict(EMPTY_METRICS)

    if df is None or len(df) == 0:
        return m

    qty = df[pd.to_numeric(df['actual_qty'], errors='coerce') > 0]
    m['record_count'] = int(len(df))
    m['graded_count'] = int(len(qty))
    if 'item_id' in df.columns:
        m['n_items'] = int(pd.to_numeric(df['item_id'], errors='coerce').nunique())

    if len(qty):
        sum_act = float(pd.to_numeric(qty['actual_qty'], errors='coerce').sum())
        sum_fc = float(pd.to_numeric(qty['forecast_qty'], errors='coerce').sum())
        abs_err = float(
            (pd.to_numeric(qty['forecast_qty'], errors='coerce')
             - pd.to_numeric(qty['actual_qty'], errors='coerce')).abs().sum()
        )
        diff = float(
            (pd.to_numeric(qty['forecast_qty'], errors='coerce')
             - pd.to_numeric(qty['actual_qty'], errors='coerce')).sum()
        )
        m['sum_actual'] = _fmt(sum_act)
        m['sum_forecast'] = _fmt(sum_fc)
        m['wmape'] = _fmt(abs_err / sum_act * 100.0)
        m['wbias'] = _fmt(diff / sum_act * 100.0)
        m['over_forecast_pct'] = _fmt(
            100.0 * int((qty['forecast_qty'] > qty['actual_qty']).sum()) / len(qty)
        )

    val = df[pd.to_numeric(df['actual_value'], errors='coerce') > 0]
    val = val[pd.to_numeric(val['actual_value'], errors='coerce').notna()]
    m['value_count'] = int(len(val))
    if len(val):
        sum_va = float(pd.to_numeric(val['actual_value'], errors='coerce').sum())
        sum_vf = float(pd.to_numeric(val['forecast_value'], errors='coerce').sum())
        vabs = float(
            (pd.to_numeric(val['forecast_value'], errors='coerce')
             - pd.to_numeric(val['actual_value'], errors='coerce')).abs().sum()
        )
        vdiff = float(
            (pd.to_numeric(val['forecast_value'], errors='coerce')
             - pd.to_numeric(val['actual_value'], errors='coerce')).sum()
        )
        m['sum_value_actual'] = _fmt(sum_va)
        m['sum_value_forecast'] = _fmt(sum_vf)
        m['value_mape'] = _fmt(vabs / sum_va * 100.0)
        m['value_bias'] = _fmt(vdiff / sum_va * 100.0)

    return m


# ─────────────────────────────────────────────────────────────────────────────
# Accuracy frame
# ─────────────────────────────────────────────────────────────────────────────

def accuracy_records_df(version) -> pd.DataFrame:
    """
    All ForecastAccuracy leaf rows for a version as a DataFrame with the
    location materialized path included (for subtree roll-ups).
    """
    qs = ForecastAccuracy.objects.filter(version=version)
    df = pd.DataFrame(list(qs.values(
        'item_id',
        'planning_location_id',
        'planning_location__path',
        'period_start',
        'actual_qty', 'forecast_qty',
        'actual_value', 'forecast_value',
        'mape', 'bias',
    )))
    if not df.empty:
        for col in ('actual_qty', 'forecast_qty', 'actual_value',
                    'forecast_value', 'mape', 'bias'):
            df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Location hierarchy drill
# ─────────────────────────────────────────────────────────────────────────────

def location_children(version, location_id=None):
    """
    One row per child of the given location (None = top-level/root nodes),
    with weighted metrics over all accuracy rows under that child.

    Returns (rows, current_location, breadcrumb).
    """
    client = version.client
    current = None
    if location_id is not None:
        current = PlanningLocation.objects.get(pk=location_id, client=client)
        children = list(PlanningLocation.objects.filter(
            client=client, parent=current, is_active=True,
        ).order_by('code'))
    else:
        children = list(PlanningLocation.objects.filter(
            client=client, parent__isnull=True, is_active=True,
        ).order_by('code'))

    df = accuracy_records_df(version)

    rows = []
    for child in children:
        sub = df[
            df['planning_location__path'].map(
                lambda p: _path_under(p, child.path)
            )
        ]
        rows.append({
            'type': 'location',
            'location_id': child.pk,
            'key': child.code,
            'label': child.name or child.code,
            'has_children': PlanningLocation.objects.filter(
                parent=child, is_active=True,
            ).exists(),
            **compute_metrics(sub),
        })

    breadcrumb = _location_breadcrumb(current)
    return rows, current, breadcrumb


def location_items(version, location_id):
    """
    Item-level rows for accuracy at a location (including descendants).
    """
    current = PlanningLocation.objects.get(pk=location_id, client=version.client)
    df = accuracy_records_df(version)
    sub = df[
        df['planning_location__path'].map(
            lambda p: _path_under(p, current.path)
        )
    ]

    rows = []
    if not sub.empty:
        for item_id, group in sub.groupby('item_id'):
            rows.append({
                'type': 'item',
                'item_id': int(item_id),
                'key': item_id,
                'label': _item_name(version, int(item_id)),
                'has_children': False,
                **compute_metrics(group),
            })
        rows.sort(key=lambda r: (r['wmape'] is None, r['wmape'] if r['wmape'] is not None else 0))

    breadcrumb = _location_breadcrumb(current)
    return rows, current, breadcrumb


def _location_breadcrumb(current):
    if current is None:
        return []
    crumbs = []
    node = current
    while node is not None:
        crumbs.append({
            'location_id': node.pk,
            'label': node.name or node.code,
        })
        node = node.parent
    crumbs.reverse()
    return crumbs


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy hierarchy drill
# ─────────────────────────────────────────────────────────────────────────────

def _planning_taxonomy_slug(version):
    cfg = ForecastingConfig.get_for_client(version.client)
    if cfg and cfg.planning_producthierarchy:
        return cfg.planning_producthierarchy
    return 'gpc'


def _mapped_nodes(version, item_ids):
    """
    item_id → primary TaxonomyNode, scoped to the client's planning
    product hierarchy; falls back to any primary mapping when the configured
    taxonomy has no mappings.
    """
    if not item_ids:
        return {}
    slug = _planning_taxonomy_slug(version)
    mappings = (
        ItemTaxonomyNode.objects
        .filter(item_id__in=item_ids, is_primary=True, node__taxonomy__slug=slug)
        .select_related('node')
    )
    item_map = {m.item_id: m.node for m in mappings}
    if not item_map:
        mappings = (
            ItemTaxonomyNode.objects
            .filter(item_id__in=item_ids, is_primary=True)
            .select_related('node')
        )
        item_map = {m.item_id: m.node for m in mappings}
    return item_map


def _mapped_taxonomy_id(item_map):
    """
    Single taxonomy shared by all mapped primary nodes, else None.
    Materialized paths are only unique WITHIN a taxonomy — every
    TaxonomyNode lookup below must be scoped (a global 'sector' tree
    reuses paths like '001' just like any client product hierarchy).
    """
    tax_ids = {n.taxonomy_id for n in item_map.values()}
    return tax_ids.pop() if len(tax_ids) == 1 else None


def _taxonomy_branch_names(branches, taxonomy_id=None):
    """Map materialized path → (node_id, name) via the TaxonomyNode table."""
    names = {}
    qs = TaxonomyNode.objects.filter(path__in=branches).only(
        'pk', 'path', 'name', 'slug'
    )
    if taxonomy_id is not None:
        qs = qs.filter(taxonomy_id=taxonomy_id)
    for node in qs:
        names[node.path] = (node.pk, node.name or node.slug)
    for bp in branches:
        names.setdefault(bp, (None, bp))
    return names


def taxonomy_children(version, node_path=None):
    """
    One row per branch below the given taxonomy node (None = top level),
    with weighted metrics over items mapped under that branch.

    Branches are derived from the distinct materialized-path prefixes of the
    items' primary taxonomy nodes, so empty intermediate levels are skipped.

    Returns (rows, current_path, breadcrumb).
    """
    df = accuracy_records_df(version)
    item_ids = set(df['item_id']) if not df.empty else set()
    item_map = _mapped_nodes(version, item_ids)

    if not item_map:
        return [], None, []

    paths = sorted({n.path for n in item_map.values()})

    if node_path is None:
        depth = 1
        branches = sorted({
            '.'.join(_path_segments(p)[:depth]) for p in paths
        })
    else:
        depth = len(_path_segments(node_path))
        branches = sorted({
            '.'.join(_path_segments(p)[:depth + 1])
            for p in paths
            if len(_path_segments(p)) > depth and _path_under(p, node_path)
        })

    branch_names = _taxonomy_branch_names(branches, _mapped_taxonomy_id(item_map))

    rows = []
    for bp in branches:
        sub_ids = {
            iid for iid, node in item_map.items()
            if _path_under(node.path, bp)
        }
        sub = df[df['item_id'].isin(sub_ids)]
        node_id, label = branch_names[bp]
        has_children = any(
            _path_under(p, bp) and _path_segments(p) != _path_segments(bp)
            for p in paths
        )
        rows.append({
            'type': 'taxon',
            'node_path': bp,
            'node_id': node_id,
            'key': label,
            'label': label,
            'depth': len(bp.split('.')),
            'has_children': has_children,
            **compute_metrics(sub),
        })

    rows.sort(key=lambda r: (r['wmape'] is None, r['wmape'] if r['wmape'] is not None else 0))

    return rows, node_path, _taxonomy_breadcrumb(node_path, _mapped_taxonomy_id(item_map))


def taxonomy_items(version, node_path):
    """Item-level rows for accuracy under a taxonomy branch."""
    df = accuracy_records_df(version)
    item_ids = set(df['item_id']) if not df.empty else set()
    item_map = _mapped_nodes(version, item_ids)

    sub_ids = {
        iid for iid, node in item_map.items()
        if _path_under(node.path, node_path)
    }
    sub = df[df['item_id'].isin(sub_ids)]

    rows = []
    if not sub.empty:
        for item_id, group in sub.groupby('item_id'):
            rows.append({
                'type': 'item',
                'item_id': int(item_id),
                'key': item_id,
                'label': _item_name(version, int(item_id)),
                'has_children': False,
                **compute_metrics(group),
            })
        rows.sort(key=lambda r: (r['wmape'] is None, r['wmape'] if r['wmape'] is not None else 0))

    return rows, _taxonomy_breadcrumb(node_path, _mapped_taxonomy_id(item_map))


def _taxonomy_breadcrumb(node_path, taxonomy_id=None):
    if not node_path:
        return []
    segments = node_path.split('.')
    crumbs = []
    for i in range(1, len(segments) + 1):
        prefix = '.'.join(segments[:i])
        qs = TaxonomyNode.objects.filter(path=prefix)
        if taxonomy_id is not None:
            qs = qs.filter(taxonomy_id=taxonomy_id)
        node = qs.first()
        crumbs.append({
            'node_path': prefix,
            'label': (node.name or node.slug) if node else prefix,
        })
    return crumbs


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate drill (Value Summary / Actuals Summary style)
# ─────────────────────────────────────────────────────────────────────────────

def accuracy_agg_records_df(version) -> pd.DataFrame:
    """
    Rich leaf-accuracy frame for aggregate drills: every ForecastAccuracy row
    for the version plus the resolved Sales Hierarchy node (a→b→c via
    SalesForecastLink), the primary Taxonomy node, the customer code, and the
    distribution channel code.
    """
    from mysite.models.demand.forecast import ForecastAccuracy

    df = pd.DataFrame(list(
        ForecastAccuracy.objects
        .filter(version=version)
        .values(
            'pk', 'item_id',
            'planning_location_id', 'planning_customer_id',
            'planning_customer__code', 'distribution_channel__code',
            'period_start',
            'actual_qty', 'forecast_qty', 'actual_value', 'forecast_value',
        )
    ))
    for col in ('sales_node_id', 'taxonomy_node_id', 'taxonomy_path'):
        df[col] = None
    if df.empty:
        return df
    for col in ('actual_qty', 'forecast_qty', 'actual_value', 'forecast_value'):
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Sales hierarchy: resolve each row to its leaf SalesNode via a→b→c.
    link_map = get_sales_forecast_link_map(version.client_id)
    df['sales_node_id'] = [
        resolve_sales_link(link_map, loc, dc, cust)
        for loc, dc, cust in zip(
            df['planning_location_id'],
            df['distribution_channel__code'],
            df['planning_customer_id'],
        )
    ]

    # Item hierarchy: primary taxonomy node per item.
    item_map = _mapped_nodes(version, set(df['item_id']))
    df['taxonomy_node_id'] = df['item_id'].map(
        lambda iid: item_map[iid].pk if iid in item_map else None)
    df['taxonomy_path'] = df['item_id'].map(
        lambda iid: item_map[iid].path if iid in item_map else None)
    return df


def _agg_dim_isna(v) -> bool:
    try:
        return v is None or pd.isna(v)
    except (TypeError, ValueError):
        return False


def accuracy_aggregate_rows(
    version,
    agg_level='total',
    period_start=None,
    customer_code=None,
    sales_node_id=None,
    taxonomy_node_id=None,
    value_min=None,
    value_max=None,
):
    """
    Value-based accuracy rows grouped by (period, dimension key) at the
    requested level — the accuracy equivalent of ForecastAggregate rows, so the
    Accuracy page can reuse the Value Summary / Actuals Summary layout.

    agg_level ∈ {'total', 'sales', 'item_hierarchy', 'customer'}.

    Returns (rows, grand_metrics). Each row carries the compute_metrics dict
    plus 'period_start', 'dim', 'display_key', 'display_hierarchy'.
    """
    valid = {'total', 'sales', 'item_hierarchy', 'customer'}
    if agg_level not in valid:
        raise ValueError(f'agg_level must be one of: {sorted(valid)}.')

    df = accuracy_agg_records_df(version)
    grand = compute_metrics(df)
    if df.empty:
        return [], grand

    # ── Filters (applied to leaf rows, before grouping) ──────────────────
    if period_start:
        df = df[df['period_start'] == period_start]
    if customer_code:
        df = df[df['planning_customer__code'] == customer_code]
    if sales_node_id is not None:
        subtree = set(get_sales_node_subtree_ids(version.client_id, sales_node_id))
        df = df[df['sales_node_id'].isin(subtree)]
    if taxonomy_node_id is not None:
        from utils.taxonomy_filters import resolve_node_subtree_ids
        try:
            subtree = set(resolve_node_subtree_ids(version.client, taxonomy_node_id))
        except Exception:
            subtree = set()
        df = df[df['taxonomy_node_id'].isin(subtree)]

    grand = compute_metrics(df)
    if df.empty:
        return [], grand

    # ── Dimension column per level ────────────────────────────────────────
    if agg_level == 'total':
        df = df.copy()
        df['dim'] = 0
    elif agg_level == 'sales':
        df = df.copy()
        df['dim'] = df['sales_node_id']
    elif agg_level == 'item_hierarchy':
        df = df.copy()
        df['dim'] = df['taxonomy_node_id']
    else:  # customer
        df = df.copy()
        df['dim'] = df['planning_customer__code']

    rows = []
    for (period, dim), group in df.groupby(['period_start', 'dim'], dropna=False):
        m = compute_metrics(group)
        if value_min is not None or value_max is not None:
            va = m['sum_value_actual']
            if va is None:
                continue
            if value_min is not None and va < float(value_min):
                continue
            if value_max is not None and va > float(value_max):
                continue
        rows.append({
            'period_start': period,
            'dim': dim,
            **m,
        })

    _attach_agg_display(version, agg_level, rows)
    rows.sort(key=lambda r: (r['period_start'], r['display_key']))
    return rows, grand


def _attach_agg_display(version, agg_level, rows):
    """Fill display_key / display_hierarchy for each aggregate row."""
    if agg_level == 'total':
        for r in rows:
            r['display_key'] = 'All'
            r['display_hierarchy'] = ''
        return

    if agg_level == 'sales':
        from utils.demand.hierarchy_utils import get_sales_node_info_map
        info = get_sales_node_info_map(version.client_id)
        for r in rows:
            nid = None if _agg_dim_isna(r['dim']) else int(r['dim'])
            node = info.get(nid)
            if node is None:
                r['display_key'] = 'Unassigned'
                r['display_hierarchy'] = ''
            else:
                r['display_key'] = f'{node["code"]} — {node["name"] or node["code"]}'
                chain = [info[a]['code'] for a in node['ancestors'] if a in info]
                chain.append(node['code'])
                r['display_hierarchy'] = ' › '.join(chain)
        return

    if agg_level == 'item_hierarchy':
        from mysite.models.catalogue import TaxonomyNode
        from utils.demand.hierarchy_utils import get_product_hierarchy_ancestor_map
        node_rows = list(
            TaxonomyNode.objects.filter(client=version.client)
            .values('id', 'name', 'taxonomy_id')
        )
        ancestors = get_product_hierarchy_ancestor_map(version.client_id)
        info = {
            n['id']: {
                'name': n['name'],
                'ancestors': ancestors.get(n['id'], []),
            }
            for n in node_rows
        }
        for r in rows:
            nid = None if _agg_dim_isna(r['dim']) else int(r['dim'])
            node = info.get(nid)
            if node is None:
                r['display_key'] = 'Unassigned'
                r['display_hierarchy'] = ''
            else:
                r['display_key'] = node['name']
                chain = [info[a]['name'] for a in node['ancestors'] if a in info]
                chain.append(node['name'])
                r['display_hierarchy'] = ' › '.join(chain)
        return

    # customer
    for r in rows:
        if _agg_dim_isna(r['dim']):
            r['display_key'] = 'Unassigned'
        else:
            r['display_key'] = str(r['dim'])
        r['display_hierarchy'] = ''


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _item_name(version, item_id):
    from mysite.models.catalogue import Item
    name = Item.objects.filter(pk=item_id).values_list('name', flat=True).first()
    return name or str(item_id)


def rollup(version, group_by: str):
    """
    Weighted metrics grouped by one dimension.

    group_by ∈ {'item', 'location', 'period'} — grouped by item_id,
    planning_location code, or period_start respectively.
    """
    df = accuracy_records_df(version)
    key_col = {
        'item': 'item_id',
        'location': 'planning_location_id',
        'period': 'period_start',
    }.get(group_by)
    if key_col is None:
        raise ValueError("group_by must be one of: item, location, period.")

    if df.empty:
        return [], compute_metrics(df)

    rows = []
    for key, group in df.groupby(key_col, dropna=False):
        rows.append({
            'group_by': group_by,
            'group_key': key,
            **compute_metrics(group),
        })
    rows.sort(key=lambda r: (r['wmape'] is None, r['wmape'] if r['wmape'] is not None else 0))
    return rows, compute_metrics(df)

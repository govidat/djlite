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

# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

METRIC_KEYS = (
    'record_count', 'graded_count',
    'sum_actual', 'sum_forecast', 'wmape', 'wbias', 'over_forecast_pct',
    'value_count', 'sum_value_actual', 'sum_value_forecast',
    'value_mape', 'value_bias',
)

EMPTY_METRICS = dict.fromkeys(METRIC_KEYS, None)
EMPTY_METRICS['record_count'] = 0
EMPTY_METRICS['graded_count'] = 0
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


def _taxonomy_branch_names(branches):
    """Map materialized path → (node_id, name) via the TaxonomyNode table."""
    names = {}
    for node in TaxonomyNode.objects.filter(path__in=branches).only(
        'pk', 'path', 'name', 'slug'
    ):
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

    branch_names = _taxonomy_branch_names(branches)

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

    return rows, node_path, _taxonomy_breadcrumb(node_path)


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

    return rows, _taxonomy_breadcrumb(node_path)


def _taxonomy_breadcrumb(node_path):
    if not node_path:
        return []
    segments = node_path.split('.')
    crumbs = []
    for i in range(1, len(segments) + 1):
        prefix = '.'.join(segments[:i])
        node = TaxonomyNode.objects.filter(path=prefix).first()
        crumbs.append({
            'node_path': prefix,
            'label': (node.name or node.slug) if node else prefix,
        })
    return crumbs


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

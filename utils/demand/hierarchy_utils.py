from __future__ import annotations
from collections import defaultdict
from django.db.models import Q
from django.db import models
import logging
logger = logging.getLogger(__name__)

#from mysite.models import ForecastingConfig, Taxonomy

def get_location_levels(client_id: int) -> list[dict]:
    """
    Return the location hierarchy levels for a client, ordered from
    root (level 0 = client total) to leaves.

    Returns list of dicts:
        [
            {'depth': 0, 'level_label': 'Client Total',
             'location_ids': None},         # virtual — all locations
            {'depth': 1, 'level_label': 'Region',
             'location_ids': [1, 2, 3]},
            {'depth': 2, 'level_label': 'Zone',
             'location_ids': [4, 5, 6, 7]},
            {'depth': 3, 'level_label': 'Branch',
             'location_ids': [8, 9, ...], 'is_leaf': True},
        ]

    Depth 0 is the virtual "Client Total" (no model row — just the aggregate).
    Actual PlanningLocation nodes start at depth 1.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    locations = list(
        PlanningLocation.objects
        .filter(client_id=client_id, is_active=True)
        .values('id', 'code', 'name', 'level_label', 'parent_id', 'is_leaf', 'path')
        .order_by('path')
    )

    if not locations:
        return [{'depth': 0, 'level_label': 'Client Total',
                 'location_ids': None, 'is_leaf': False}]

    # Compute depth from path (path = "1/4/12/" → depth = 2)
    def _depth(loc: dict) -> int:
        return loc['path'].count('/') - 1

    by_depth: dict[int, list] = defaultdict(list)
    for loc in locations:
        d = _depth(loc)
        by_depth[d].append(loc)

    max_depth = max(by_depth.keys())

    # Level 0 is always the virtual Client Total
    levels = [{'depth': 0, 'level_label': 'Client Total',
                'location_ids': None, 'is_leaf': False}]

    for depth in range(0, max_depth + 1):
        locs = by_depth.get(depth, [])
        if not locs:
            continue
        label = locs[0]['level_label'] or f'Level {depth}'
        levels.append({
            'depth': depth + 1,   # +1 because 0 is Client Total
            'level_label': label,
            'location_ids': [l['id'] for l in locs],
            'location_codes': [l['code'] for l in locs],
            'is_leaf': all(l['is_leaf'] for l in locs),
        })

    return levels


def get_location_children_map(client_id: int) -> dict[int | None, list[int]]:
    """
    Returns dict: {parent_id → [child_ids]}.
    parent_id=None means root nodes (direct children of client total).
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result: dict[int | None, list[int]] = defaultdict(list)
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'parent_id'):
        result[loc['parent_id']].append(loc['id'])
    return dict(result)


def get_location_ancestor_map(client_id: int) -> dict[int, list[int]]:
    """
    Returns dict: {location_id → [ancestor_ids from root to parent]}.
    Used to find the region/zone a leaf belongs to.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result = {}
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'path'):
        parts = [p for p in loc['path'].split('/') if p]
        ancestor_ids = [int(p) for p in parts[:-1]]
        result[loc['id']] = ancestor_ids
    return result



# ─────────────────────────────────────────────────────────────────────────────
# Location — leaf-only helper (Part A no longer drills the location tree;
# grain search now anchors on the leaf PlanningLocation and climbs the
# SalesNode tree instead). Kept as a thin accessor for callers that just
# need "is this a leaf, and which client does it belong to".
# ─────────────────────────────────────────────────────────────────────────────
 
def get_leaf_location(location_id: int):
    """Return the PlanningLocation row, raising if it isn't a leaf."""
    from mysite.models.demand.hierarchy import PlanningLocation
 
    loc = PlanningLocation.objects.get(id=location_id)
    if not loc.is_leaf:
        raise ValueError(
            f'PlanningLocation {location_id} ({loc.code}) is not a leaf. '
            f'Sales forecasting grain search only operates on leaf locations.'
        )
    return loc
 
 
# The full location-tree helpers (get_location_levels, get_location_children_map,
# get_location_ancestor_map) are UNCHANGED from the existing file — the location
# tree is still used elsewhere in the app (org/reporting views) — they are just
# no longer called by compute_series_profiles.py. Omitted here for brevity;
# keep them as-is.
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Sales Hierarchy (SalesNode) — climbed during grain search, level 0 = leaf
# location's resolved SalesNode, climbing toward the root.
# ─────────────────────────────────────────────────────────────────────────────
 
def client_has_sales_hierarchy(client_id: int) -> bool:
    """
    Cheap existence check. Callers should compute this ONCE per client per
    run (not per series) and pass the result down, to avoid a DB hit per
    series and to avoid spamming warnings.
    """
    from mysite.models.demand.hierarchy import SalesNode
    return SalesNode.objects.filter(client_id=client_id, is_active=True).exists()
 
 
def get_sales_hierarchy_ancestor_map(client_id: int) -> dict[int, list[int]]:
    """
    {sales_node_id -> [ancestor_ids, root...parent]} built from the
    MaterializedPathMixin `path` field, same convention as
    get_location_ancestor_map.
    """
    from mysite.models.demand.hierarchy import SalesNode
 
    result: dict[int, list[int]] = {}
    for node in SalesNode.objects.filter(client_id=client_id, is_active=True).values('id', 'path'):
        parts = [p for p in node['path'].split('/') if p]
        result[node['id']] = [int(p) for p in parts[:-1]]
    return result
 
 
def get_sales_forecast_link_map(
    client_id: int,
    as_of=None,
) -> dict[tuple, int | None]:
    """
    Bulk resolution of (leaf_location, distribution_channel, planning_customer)
    → leaf SalesNode id, replicating resolve_sales_forecast_link's a→b→c
    precedence for EVERY location in ONE query (instead of one query per row).

    Keys are (planning_location_id, distribution_channel_code or None,
    planning_customer_id or None). The stored value is the resolved leaf
    SalesNode id, or None when no link is active for that key (callers bucket
    those under "Unassigned"). Within a precedence class the lowest-pk link
    wins, matching the .first() behaviour of resolve_sales_forecast_link.
    """
    from django.utils import timezone
    from mysite.models.demand.hierarchy import SalesForecastLink

    as_of = as_of or timezone.now().date()

    links = list(
        SalesForecastLink.objects
        .filter(client_id=client_id, valid_from__lte=as_of)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
        .order_by('id')
        .values_list(
            'planning_location_id', 'distribution_channel_id',
            'planning_customer_id', 'sales_node_id',
        )
    )

    by_loc: dict[int, list[tuple]] = defaultdict(list)
    for loc_id, dc_code, cust_id, node_id in links:
        by_loc[loc_id].append((dc_code, cust_id, node_id))

    result: dict[tuple, int | None] = {}
    for loc_id, entries in by_loc.items():
        for dc_code, cust_id, node_id in entries:
            # shape a: exact (dc + customer)
            if dc_code and cust_id:
                result.setdefault((loc_id, dc_code, cust_id), node_id)
            # shape b: dc only (customer NULL)
            elif dc_code:
                result.setdefault((loc_id, dc_code, None), node_id)
            # shape c: location only (channel & customer NULL)
            else:
                result.setdefault((loc_id, None, None), node_id)
    return result


def resolve_sales_link(
    sales_link_map: dict[tuple, int | None],
    leaf_location_id: int,
    distribution_channel_code: str | None,
    planning_customer_id: int | None,
) -> int | None:
    """
    Look up one (location, dc, customer) key against a map built by
    get_sales_forecast_link_map, applying a→b→c precedence.
    """
    if planning_customer_id is not None and distribution_channel_code:
        for key in (
            (leaf_location_id, distribution_channel_code, planning_customer_id),
            (leaf_location_id, distribution_channel_code, None),
            (leaf_location_id, None, None),
        ):
            if key in sales_link_map:
                return sales_link_map[key]
        return None
    if distribution_channel_code:
        for key in (
            (leaf_location_id, distribution_channel_code, None),
            (leaf_location_id, None, None),
        ):
            if key in sales_link_map:
                return sales_link_map[key]
        return None
    return sales_link_map.get((leaf_location_id, None, None))


def get_sales_node_info_map(client_id: int) -> dict[int, dict]:
    """
    {sales_node_id -> {id, code, name, level_label, depth, ancestors}}
    ancestors = [root, ..., parent] ids (for breadcrumb labels). One query
    over the active sales org, reusing get_sales_hierarchy_ancestor_map.
    """
    from mysite.models.demand.hierarchy import SalesNode

    nodes = list(
        SalesNode.objects.filter(client_id=client_id, is_active=True)
        .values('id', 'code', 'name', 'level_label', 'path')
    )
    ancestors = get_sales_hierarchy_ancestor_map(client_id)
    return {
        n['id']: {
            'id': n['id'],
            'code': n['code'],
            'name': n['name'],
            'level_label': n['level_label'],
            'depth': n['path'].count('/') - 1,
            'ancestors': ancestors.get(n['id'], []),
        }
        for n in nodes
    }


def get_sales_node_subtree_ids(client_id: int, node_id: int) -> list[int]:
    """All sales-node ids under `node_id` (the node itself + descendants)."""
    from mysite.models.demand.hierarchy import SalesNode

    node = SalesNode.objects.get(pk=node_id, client_id=client_id)
    qs = SalesNode.objects.filter(client_id=client_id, is_active=True)
    if node.path:
        qs = qs.filter(path__startswith=node.path)
    return list(qs.values_list('id', flat=True))


def get_sales_hierarchy_levels(client_id: int) -> list[dict]:
    """
    Same shape as get_location_levels(): depth 0 = virtual 'Top' (whole
    sales org), depth 1..n = actual SalesNode rows, root -> leaf.
    Used for display/labeling only; the grain search itself walks the
    ancestor map directly (see _climb_sales_hierarchy below).
    """
    from mysite.models.demand.hierarchy import SalesNode
 
    nodes = list(
        SalesNode.objects.filter(client_id=client_id, is_active=True)
        .values('id', 'code', 'level_label', 'parent_id', 'path')
        .order_by('path')
    )
    if not nodes:
        return [{'depth': 0, 'level_label': 'Top', 'node_ids': None}]
 
    by_depth: dict[int, list] = defaultdict(list)
    for n in nodes:
        by_depth[n['path'].count('/') - 1].append(n)
 
    levels = [{'depth': 0, 'level_label': 'Top', 'node_ids': None}]
    for depth in range(0, max(by_depth) + 1):
        grp = by_depth.get(depth, [])
        if not grp:
            continue
        levels.append({
            'depth': depth + 1,
            'level_label': grp[0]['level_label'] or f'Level {depth}',
            'node_ids': [n['id'] for n in grp],
        })
    return levels
 
 
def resolve_sales_forecast_link(
    client_id: int,
    leaf_location_id: int,
    distribution_channel_code: str | None,
    planning_customer_id: int | None,
    as_of=None,
) -> dict | None:
    """
    Resolve a -> b -> c precedence for one (leaf_location, dc, customer) key,
    scoped to whichever SalesForecastLink row was active as_of a given date.
 
    as_of defaults to today. Grain search (compute_series_profiles.py) does
    NOT rely on that default — it always passes as_of=analysis_to explicitly,
    per the "route historical actuals by today's org structure" decision:
    classification evaluates the whole analysis window against ONE snapshot
    of the sales hierarchy (the one active at the end of the window), rather
    than joining per-period against whichever link was active at the time of
    each sale. Only callers that genuinely want "right now" (admin UI,
    ad-hoc lookups) should rely on the default.
 
    Returns {'link_type': 'a'|'b'|'c', 'sales_node_id': int} or None if no
    link was active for THIS leaf_location as_of that date (a data-quality
    or history gap for this location, not necessarily "no sales hierarchy
    configured" — see client_has_sales_hierarchy for the client-wide case).
    """
    from django.db.models import Q
    from django.utils import timezone
    from mysite.models.demand.hierarchy import SalesForecastLink
 
    as_of = as_of or timezone.now().date()
 
    qs = (
        SalesForecastLink.objects
        .filter(client_id=client_id, planning_location_id=leaf_location_id, valid_from__lte=as_of)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
    )
 
    if distribution_channel_code and planning_customer_id:
        link = qs.filter(
            distribution_channel_id=distribution_channel_code,
            planning_customer_id=planning_customer_id,
        ).first()
        if link:
            return {'link_type': 'a', 'sales_node_id': link.sales_node_id}
 
    if distribution_channel_code:
        link = qs.filter(
            distribution_channel_id=distribution_channel_code,
            planning_customer__isnull=True,
        ).first()
        if link:
            return {'link_type': 'b', 'sales_node_id': link.sales_node_id}
 
    link = qs.filter(distribution_channel__isnull=True, planning_customer__isnull=True).first()
    if link:
        return {'link_type': 'c', 'sales_node_id': link.sales_node_id}
 
    return None
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Item / product hierarchy — slug now comes from ForecastingConfig, and the
# taxonomy can be per-item-hierarchy-level ancestor-chained the same way
# locations were.
# ─────────────────────────────────────────────────────────────────────────────
 
def get_product_hierarchy_levels(client_id: int) -> list[dict]:
    """
    Return the product taxonomy levels ordered from FINEST (one above leaf)
    to COARSEST (root). Taxonomy slug is read from
    ForecastingConfig.planning_producthierarchy (default 'gpc') instead of being
    hardcoded, per client configurability.
 
    Returns [] if:
      - the client has no ForecastingConfig row and no default can be created, or
      - no Taxonomy exists for that slug (client-specific or global), or
      - the taxonomy exists but has zero nodes.
    In all three cases the caller (compute_series_profiles) treats this as
    "the item-hierarchy dimension is not required for this client" and
    evaluates only at the item's own level, per product decision.
    """
    from mysite.models import TaxonomyNode, Taxonomy
    from mysite.models.demand.forecast import ForecastingConfig
 
    slug = ForecastingConfig.get_for_client_id(client_id).planning_producthierarchy or 'gpc'

    taxonomy = (
        Taxonomy.objects
        .filter(Q(client_id=client_id) | Q(client=None), slug=slug)
        .order_by('-client_id')
        .first()
    )
    if taxonomy is None:
        logger.warning(
            f'get_product_hierarchy_levels: no Taxonomy with slug={slug!r} for client_id={client_id}. '
            f'Item-hierarchy roll-up will be skipped for this client.'
        )
        return []
 
    nodes = list(
        TaxonomyNode.objects.filter(taxonomy=taxonomy)
        .values('id', 'name', 'parent_id', 'depth')
        .order_by('depth')
    )
    if not nodes:
        logger.warning(
            f'get_product_hierarchy_levels: Taxonomy {slug!r} has no nodes for client_id={client_id}. '
            f'Item-hierarchy roll-up will be skipped for this client.'
        )
        return []
 
    max_depth = max(n['depth'] for n in nodes)
    by_depth: dict[int, list] = defaultdict(list)
    for n in nodes:
        by_depth[n['depth']].append(n)
 
    levels = []
    for depth in range(max_depth - 1, -1, -1):   # skip leaf/SKU level
        group = by_depth.get(depth, [])
        if not group:
            continue
        label = group[0].get('level_label') or f'Level {depth}'
        levels.append({
            'depth': depth,
            'level_label': label,
            'node_ids': [n['id'] for n in group],
            'node_names': [n['name'] for n in group],
        })
    return levels
 
 
def get_product_hierarchy_ancestor_map(client_id: int) -> dict[int, list[int]]:
    """
    {taxonomy_node_id -> [ancestor_ids, root...parent]}, mirroring
    get_location_ancestor_map / get_sales_hierarchy_ancestor_map, but keyed
    by TaxonomyNode.id (node depth uses parent_id chase since TaxonomyNode
    doesn't carry a materialized path in the schema we've seen).
    """
    from mysite.models import TaxonomyNode, Taxonomy
    from mysite.models.demand.forecast import ForecastingConfig
 
    slug = ForecastingConfig.get_for_client_id(client_id).planning_producthierarchy or 'gpc'
    taxonomy = (
        Taxonomy.objects.filter(Q(client_id=client_id) | Q(client=None), slug=slug)
        .order_by('-client_id').first()
    )
    if taxonomy is None:
        return {}

    nodes = {n['id']: n['parent_id'] for n in
             TaxonomyNode.objects.filter(taxonomy=taxonomy).values('id', 'parent_id')}
 
    result: dict[int, list[int]] = {}
    for node_id in nodes:
        chain = []
        cur = nodes.get(node_id)
        while cur is not None:
            chain.append(cur)
            cur = nodes.get(cur)
        result[node_id] = list(reversed(chain))  # root...parent
    return result
 
 
def get_item_hierarchy_chain(client_id: int, item_id: int) -> list[dict]:
    """
    Build the finest -> coarsest chain of {'level': int, 'key': dict} the
    grain search should walk for a single item, per requirement 2/3's
    "item / item_hierarchy-1 / ... / top" escalation.
 
    level 0 is always the item itself (key identifies the concrete Item row).
    level 1..k are TaxonomyNode ancestors, finest to coarsest, IF a product
    hierarchy is configured and this item is mapped into it.
 
    If get_product_hierarchy_levels() returns [] (no taxonomy / no nodes),
    or this specific item has no mapping into the taxonomy, the chain is
    just [item] — the item-hierarchy dimension is skipped for this item,
    per product decision (warn, don't error).
    """
    from mysite.models import Item
 
    # Single-item convenience wrapper — for batch runs (10K+ items) call
    # get_item_hierarchy_chains_bulk directly instead; this does one query
    # per call and does not scale.
    return get_item_hierarchy_chains_bulk(client_id, [item_id])[item_id]
 
 
def get_item_primary_node_map(client_id: int, item_ids: list[int] | None = None) -> dict[int, int]:
    """
    Bulk {item_id -> leaf TaxonomyNode id} for the client's configured
    planning_producthierarchy taxonomy, via ItemTaxonomyNode. An item can map to
    multiple nodes (even within one taxonomy); preference order is
    is_primary=True first, then lowest `order`. One query total, not one
    per item — required at 10K-item scale.
    """
    from mysite.models import ItemTaxonomyNode, Taxonomy
    from mysite.models.demand.forecast import ForecastingConfig
 
    slug = ForecastingConfig.get_for_client_id(client_id).planning_producthierarchy or 'gpc'
    taxonomy = (
        Taxonomy.objects.filter(Q(client_id=client_id) | Q(client=None), slug=slug)
        .order_by('-client_id').first()
    )
    if taxonomy is None:
        return {}

    qs = ItemTaxonomyNode.objects.filter(node__taxonomy=taxonomy)
    if item_ids is not None:
        qs = qs.filter(item_id__in=item_ids)
    qs = qs.order_by('item_id', '-is_primary', 'order')
 
    result: dict[int, int] = {}
    for row in qs.values('item_id', 'node_id'):
        result.setdefault(row['item_id'], row['node_id'])  # first hit per item wins (ordering above)
    return result
 
 
def get_item_hierarchy_chains_bulk(client_id: int, item_ids: list[int]) -> dict[int, list[dict]]:
    """
    Bulk version of get_item_hierarchy_chain — one pass over the client's
    product-hierarchy ancestor map (small: bounded by taxonomy node count,
    not item count) instead of one query per item.
 
    Returns {item_id -> chain}, chain = [{'level':0,'grain_prefix':'item',
    'item_id':...}, {'level':1,'grain_prefix':'taxon','node_id':...}, ...],
    finest to coarsest. Items with no taxonomy mapping get a length-1 chain
    (item-only) — same "hierarchy dimension not required" degradation as
    the single-item version, just computed once for everyone.
    """
    chains: dict[int, list[dict]] = {
        iid: [{'level': 0, 'grain_prefix': 'item', 'item_id': iid}] for iid in item_ids
    }
 
    prod_levels = get_product_hierarchy_levels(client_id)
    if not prod_levels:
        return chains
 
    node_map = get_item_primary_node_map(client_id, item_ids)
    ancestor_map = get_product_hierarchy_ancestor_map(client_id)  # {node_id: [root...parent]}
 
    unmapped = [iid for iid in item_ids if iid not in node_map]
    if unmapped:
        logger.warning(
            f'get_item_hierarchy_chains_bulk: {len(unmapped)} of {len(item_ids)} items have no '
            f'ItemTaxonomyNode mapping into the configured taxonomy (client_id={client_id}). '
            f'These items skip item-hierarchy roll-up (item-only chain).'
        )
 
    for iid in item_ids:
        leaf_node = node_map.get(iid)
        if leaf_node is None:
            continue
        climb = list(reversed(ancestor_map.get(leaf_node, [])))  # finest ancestor first, root last
        for depth_idx, node_id in enumerate(climb, start=1):
            chains[iid].append({'level': depth_idx, 'grain_prefix': 'taxon', 'node_id': node_id})
 
    return chains
 

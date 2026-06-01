from __future__ import annotations
from collections import defaultdict


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


def get_product_hierarchy_levels(client_id: int) -> list[dict]:
    """
    Return the product taxonomy levels for the 'product_planning' taxonomy,
    ordered from leaf (SKU) to root (highest category).

    Returns list of dicts ordered from FINEST to COARSEST:
        [
            {'depth': 3, 'level_label': 'SKU',       'node_ids': [...]},
            {'depth': 2, 'level_label': 'Brand',      'node_ids': [...]},
            {'depth': 1, 'level_label': 'Sub-cat',    'node_ids': [...]},
            {'depth': 0, 'level_label': 'Category',   'node_ids': [...]},
        ]

    The leaf level (SKUs) is excluded from Part B evaluation — Part B starts
    one level above the leaf.
    """
    from mysite.models import TaxonomyNode, Taxonomy

    try:
        taxonomy = Taxonomy.objects.get(
            client_id=client_id, slug='product_planning'
        )
    except Taxonomy.DoesNotExist:
        return []

    nodes = list(
        TaxonomyNode.objects
        .filter(taxonomy=taxonomy)
        .values('id', 'name', 'parent_id', 'depth')
        .order_by('depth')
    )

    if not nodes:
        return []

    max_depth = max(n['depth'] for n in nodes)
    by_depth: dict[int, list] = defaultdict(list)
    for n in nodes:
        by_depth[n['depth']].append(n)

    # Return from leaf-1 up to root (skip leaf level — those are the items)
    levels = []
    for depth in range(max_depth - 1, -1, -1):
        group = by_depth.get(depth, [])
        if not group:
            continue
        label = group[0].get('level_label') or f'Level {depth}'
        levels.append({
            'depth':      depth,
            'level_label': label,
            'node_ids':   [n['id'] for n in group],
            'node_names': [n['name'] for n in group],
        })

    return levels
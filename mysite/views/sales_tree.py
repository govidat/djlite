"""
htmx endpoints powering the sales-hierarchy tree filter widget.

Mirrors mysite/views/taxonomy_tree.py (same lazy-load pattern) but for
SalesNode: roots are parentless nodes, children come from the parent FK
(not path-string matching), and checkboxes submit `sales_node_ids`.

Three views:
  - sales_tree_panel:    initial render for the filter sidebar. Branches
                         leading to an already-selected node render
                         open/eager; everything else renders collapsed
                         and lazy.
  - sales_tree_children: htmx endpoint, returns one node's direct
                         children. Called once per node, the first time
                         it's expanded.
"""
from django.shortcuts import render, get_object_or_404

from mysite.models.demand.hierarchy import SalesNode
from utils.taxonomy_filters import parse_node_ids_param


def _selected_ids_from_request(request):
    raw = parse_node_ids_param(request, param_name='sales_node_ids')
    return {int(v) for v in raw if v.strip().isdigit()}


def _ancestor_ids_to_expand(client, selected_ids):
    """
    For each selected node, parse its materialized path ('1/4/12/') to
    resolve every ancestor node id, so the tree can render those
    branches open instead of collapsed-and-lazy.
    """
    if not selected_ids:
        return set()

    selected_nodes = SalesNode.objects.filter(
        client=client, pk__in=selected_ids, is_active=True
    )
    expand_ids = set()
    for node in selected_nodes:
        ancestor_pks = [int(p) for p in node.path.split('/') if p][:-1]
        expand_ids.update(ancestor_pks)
        expand_ids.add(node.id)
    return expand_ids


def _direct_children(client, parent):
    """Immediate children only (parent FK, not all descendants)."""
    return list(
        SalesNode.objects
        .filter(client=client, parent_id=parent.id, is_active=True)
        .order_by('path')
    )


def _selected_paths(client, selected_ids):
    """
    Materialized paths ('1/4/12') for the currently selected node ids.
    Lets any rendered node decide whether it is selected (itself or an
    ancestor is chosen — a chosen parent auto-ticks its whole subtree)
    or partially selected (a descendant is chosen but not itself).
    """
    if not selected_ids:
        return []
    return list(
        SalesNode.objects
        .filter(client=client, pk__in=selected_ids, is_active=True)
        .values_list('path', flat=True)
    )


def _selection_state(node, selected_paths):
    """
    ('selected' | 'partial' | '') for a node given chosen paths.

    SalesNode.path is materialized with a trailing slash ('3/', '3/4/').

    - selected: the node itself was chosen, or an ancestor was chosen
      (a chosen parent covers its whole subtree, so every rendered
      descendant of it shows as checked).
    - partial:  no ancestor chosen, but some descendant was chosen — the
      node's subtree is only partially covered.
    """
    if not selected_paths:
        return ''
    for p in selected_paths:
        if p == node.path:
            return 'selected'
    for p in selected_paths:
        if node.path.startswith(p):
            return 'selected'
    if any(p.startswith(node.path) for p in selected_paths):
        return 'partial'
    return ''


def _node_dict(client, node, expand_ids, selected_paths):
    has_children = SalesNode.objects.filter(
        client=client, parent_id=node.id, is_active=True
    ).exists()
    state = _selection_state(node, selected_paths)
    return {
        'id': node.id,
        'code': node.code,
        'name': node.name,
        'level_label': node.level_label,
        'has_children': has_children,
        'is_selected': state == 'selected',
        'is_partial': state == 'partial',
        'is_expanded': node.id in expand_ids,
        'children': [],
    }


def _build_eager_subtree(client, node, expand_ids, selected_paths):
    """
    Recursively build a node dict, eagerly including children only for
    nodes on the path to a currently-selected node. Everything else
    stops at one level (children stay empty, fetched later via the
    lazy htmx endpoint on first expand).
    """
    node_dict = _node_dict(client, node, expand_ids, selected_paths)
    if node.id in expand_ids:
        for child in _direct_children(client, node):
            node_dict['children'].append(
                _build_eager_subtree(client, child, expand_ids, selected_paths)
            )
    return node_dict


def sales_tree_panel(request, client_code=None):
    """
    GET /{client_code}/demand/sales-tree/
    Query params: sales_node_ids=1,6,20 (currently selected)

    Renders the sales hierarchy as a single tree group, roots lazily
    expandable, except branches leading to an already-selected node,
    which render open.
    """
    selected_ids = _selected_ids_from_request(request)
    expand_ids = _ancestor_ids_to_expand(request.client, selected_ids)
    selected_paths = _selected_paths(request.client, selected_ids)

    roots = (
        SalesNode.objects
        .filter(client=request.client, is_active=True, parent__isnull=True)
        .order_by('path')
    )

    groups = [{
        'name': 'Sales Organization',
        'roots': [
            _build_eager_subtree(
                request.client, root, expand_ids, selected_paths
            )
            for root in roots
        ],
    }]

    context = {
        'client_code': client_code,
        'taxonomy_groups': groups,
        'selected_ids': selected_ids,
        'checkbox_name': 'sales_node_ids',
        'label_mode': 'code_name',
        'tree_kind': 'sales',
    }
    return render(request, 'taxonomy_tree/partials/taxonomy_tree_panel.html', context)


def sales_tree_children(request, client_code=None, node_id=None):
    """
    GET /{client_code}/demand/sales-tree/{node_id}/children/
    Query params: sales_node_ids=1,6,20 (currently selected)

    htmx lazy-load endpoint: returns one node's direct children as
    rendered <li> partials. hx-trigger="click once" on the client
    means this fires exactly once per node, the first time it's opened.
    """
    parent = get_object_or_404(SalesNode, pk=node_id, client=request.client)
    selected_ids = _selected_ids_from_request(request)
    expand_ids = _ancestor_ids_to_expand(request.client, selected_ids)
    selected_paths = _selected_paths(request.client, selected_ids)

    # Children on the path to a currently-selected node are built eagerly
    # (their own children rendered too) so a selected deep node stays fully
    # visible after lazy expansion; everything else stays one level deep.
    nodes = [
        _build_eager_subtree(
            request.client, child, expand_ids, selected_paths
        )
        if child.id in expand_ids
        else _node_dict(request.client, child, expand_ids, selected_paths)
        for child in _direct_children(request.client, parent)
    ]

    return render(
        request,
        'taxonomy_tree/partials/taxonomy_tree_children.html',
        {
            'client_code': client_code,
            'nodes': nodes,
            'checkbox_name': 'sales_node_ids',
            'label_mode': 'code_name',
            'tree_kind': 'sales',
        },
    )

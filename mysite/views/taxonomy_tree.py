"""
htmx endpoints powering the recursive taxonomy tree filter widget.

Two views:
  - taxonomy_tree_panel:    initial render for the filter sidebar.
                             Renders one root group per taxonomy. Any
                             branch leading to an already-selected node
                             is rendered open/eager (so a submitted
                             filter stays visible after the filter bar
                             partial reloads); everything else renders
                             collapsed and lazy.
  - taxonomy_tree_children:  htmx endpoint, returns one node's direct
                             children. Called once per node, the first
                             time it's expanded.

NOTE: intentionally no @login_required here. This view is shared between
version_aggregates (login-gated page) and catalogue (guest-accessible).
request.client is resolved from the client_id URL segment the same way
for both, independent of auth state, so this exposes no more than
catalogue's own view already does for the same taxonomy data.
"""
from django.shortcuts import render, get_object_or_404

from mysite.models.catalogue import TaxonomyNode
from utils.taxonomy_filters import parse_node_ids_param


def _selected_ids_from_request(request):
    """
    Thin wrapper: parse_node_ids_param handles both param shapes
    (repeated or comma-joined); this just converts to the int set the
    rest of this module works with.
    """
    raw = parse_node_ids_param(request)
    return {int(v) for v in raw if v.strip().isdigit()}


def _ancestor_ids_to_expand(client, selected_ids):
    """
    For each selected node, walk its path segments and resolve every
    ancestor node id, so the tree can render those branches open
    instead of collapsed-and-lazy.
    """
    if not selected_ids:
        return set()

    selected_nodes = TaxonomyNode.objects.filter(client=client, pk__in=selected_ids)
    expand_ids = set()
    for node in selected_nodes:
        segments = node.path.split('.')
        for i in range(1, len(segments)):
            ancestor_path = '.'.join(segments[:i])
            ancestor_id = (
                TaxonomyNode.objects
                .filter(client=client, taxonomy_id=node.taxonomy_id, path=ancestor_path)
                .values_list('id', flat=True)
                .first()
            )
            if ancestor_id:
                expand_ids.add(ancestor_id)
        expand_ids.add(node.id)
    return expand_ids


def _direct_children(client, parent):
    """Immediate children only (depth-scoped, not all descendants)."""
    return list(
        TaxonomyNode.objects
        .filter(
            client=client,
            taxonomy_id=parent.taxonomy_id,
            depth=parent.depth + 1,
            path__startswith=f"{parent.path}.",
        )
        .order_by('name')
    )


def _node_dict(client, node, selected_ids, expand_ids):
    has_children = TaxonomyNode.objects.filter(
        client=client,
        taxonomy_id=node.taxonomy_id,
        path__startswith=f"{node.path}.",
    ).exists()
    return {
        'id': node.id,
        'name': node.name,
        'depth': node.depth,
        'taxonomy_id': node.taxonomy_id,
        'has_children': has_children,
        'is_selected': node.id in selected_ids,
        'is_expanded': node.id in expand_ids,
        'children': [],
    }


def _build_eager_subtree(client, node, selected_ids, expand_ids):
    """
    Recursively build a node dict, eagerly including children only for
    nodes on the path to a currently-selected node. Everything else
    stops at one level (children stay empty, fetched later via the
    lazy htmx endpoint on first expand).
    """
    node_dict = _node_dict(client, node, selected_ids, expand_ids)
    if node.id in expand_ids:
        for child in _direct_children(client, node):
            node_dict['children'].append(
                _build_eager_subtree(client, child, selected_ids, expand_ids)
            )
    return node_dict


def taxonomy_tree_panel(request, client_id=None):
    """
    GET /{client_id}/demand/taxonomy-tree/
    Query params: taxonomy_node_ids=1,6,20 (currently selected)

    Renders the full multi-taxonomy tree: one group per taxonomy
    (Category, Brand, ...), root nodes lazily expandable, except
    branches leading to an already-selected node, which render open.
    """
    selected_ids = _selected_ids_from_request(request)
    expand_ids = _ancestor_ids_to_expand(request.client, selected_ids)

    roots = (
        TaxonomyNode.objects
        .filter(client=request.client, is_active=True, depth=0)
        .select_related('taxonomy')
        .order_by('taxonomy__name', 'name')
    )

    groups = {}
    for root in roots:
        group = groups.setdefault(
            root.taxonomy_id, {'name': root.taxonomy.name, 'roots': []}
        )
        group['roots'].append(
            _build_eager_subtree(request.client, root, selected_ids, expand_ids)
        )

    context = {
        'client_id': client_id,
        'taxonomy_groups': list(groups.values()),
        'selected_ids': selected_ids,
    }
    return render(request, 'taxonomy_tree/partials/taxonomy_tree_panel.html', context)


def taxonomy_tree_children(request, client_id=None, node_id=None):
    """
    GET /{client_id}/demand/taxonomy-tree/{node_id}/children/
    Query params: taxonomy_node_ids=1,6,20 (currently selected)

    htmx lazy-load endpoint: returns one node's direct children as
    rendered <li> partials. hx-trigger="click once" on the client
    means this fires exactly once per node, the first time it's opened.
    """
    parent = get_object_or_404(TaxonomyNode, pk=node_id, client=request.client)
    selected_ids = _selected_ids_from_request(request)
    expand_ids = _ancestor_ids_to_expand(request.client, selected_ids)

    nodes = [
        _node_dict(request.client, child, selected_ids, expand_ids)
        for child in _direct_children(request.client, parent)
    ]

    return render(
        request,
        'taxonomy_tree/partials/taxonomy_tree_children.html',
        {'client_id': client_id, 'nodes': nodes},
    )

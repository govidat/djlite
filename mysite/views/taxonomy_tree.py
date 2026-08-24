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

    selected_nodes = TaxonomyNode.objects.filter(
        client=client, pk__in=selected_ids, is_active=True
    )
    expand_ids = set()
    for node in selected_nodes:
        segments = node.path.split('.')
        for i in range(1, len(segments)):
            ancestor_path = '.'.join(segments[:i])
            ancestor_id = (
                TaxonomyNode.objects
                .filter(
                    client=client, taxonomy_id=node.taxonomy_id,
                    path=ancestor_path, is_active=True,
                )
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
            is_active=True,
        )
        .order_by('name')
    )


def _selected_paths_by_taxonomy(client, selected_ids):
    """
    Map taxonomy_id -> list of materialized paths for the currently
    selected node ids. Used to decide, for any rendered node, whether it
    is selected (itself or any ancestor is chosen — so a chosen parent
    auto-ticks its whole subtree) or partially selected (some descendant
    is chosen but not itself).
    """
    if not selected_ids:
        return {}
    paths = {}
    for node in (
        TaxonomyNode.objects
        .filter(client=client, pk__in=selected_ids, is_active=True)
    ):
        paths.setdefault(node.taxonomy_id, []).append(node.path)
    return paths


def _selection_state(node, selected_paths):
    """
    ('selected' | 'partial' | '') for a node given chosen paths.

    - selected: the node itself was chosen, or an ancestor was chosen
      (a chosen parent covers its whole subtree, so every rendered
      descendant of it shows as checked).
    - partial:  no ancestor chosen, but some descendant was chosen — the
      node's subtree is only partially covered.
    """
    paths = (selected_paths or {}).get(node.taxonomy_id, [])
    if not paths:
        return ''
    prefix = node.path + '.'
    for p in paths:
        if p == node.path:
            return 'selected'
    for p in paths:
        if node.path.startswith(p + '.'):
            return 'selected'
    if any(p.startswith(prefix) for p in paths):
        return 'partial'
    return ''


def _node_dict(client, node, expand_ids, selected_paths):
    has_children = TaxonomyNode.objects.filter(
        client=client,
        taxonomy_id=node.taxonomy_id,
        path__startswith=f"{node.path}.",
        is_active=True,
    ).exists()
    state = _selection_state(node, selected_paths)
    return {
        'id': node.id,
        'name': node.name,
        'depth': node.depth,
        'taxonomy_id': node.taxonomy_id,
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


def taxonomy_tree_panel(request, client_id=None):
    """
    GET /{client_id}/demand/taxonomy-tree/
    Query params: taxonomy_node_ids=1,6,20 (currently selected)
                 taxonomy_slug=gs1-gpc (optional; when present, restrict
                 the tree to that single taxonomy instead of all of them)

    Renders the full multi-taxonomy tree: one group per taxonomy
    (Category, Brand, ...), root nodes lazily expandable, except
    branches leading to an already-selected node, which render open.
    """
    selected_ids = _selected_ids_from_request(request)
    expand_ids = _ancestor_ids_to_expand(request.client, selected_ids)
    selected_paths = _selected_paths_by_taxonomy(request.client, selected_ids)

    roots = (
        TaxonomyNode.objects
        .filter(client=request.client, is_active=True, depth=0)
        .select_related('taxonomy')
        .order_by('taxonomy__name', 'name')
    )

    taxonomy_slug = request.GET.get('taxonomy_slug', '').strip()
    if taxonomy_slug:
        roots = roots.filter(taxonomy__slug=taxonomy_slug)

    groups = {}
    for root in roots:
        group = groups.setdefault(
            root.taxonomy_id, {'name': root.taxonomy.name, 'roots': []}
        )
        group['roots'].append(
            _build_eager_subtree(
                request.client, root, expand_ids, selected_paths
            )
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
    selected_paths = _selected_paths_by_taxonomy(request.client, selected_ids)

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
        {'client_id': client_id, 'nodes': nodes},
    )

"""
Reusable taxonomy -> item_id resolution.

Use this anywhere a taxonomy filter needs to turn one or more selected
TaxonomyNode ids into the set of item_ids to filter a queryset by
(catalogue, version_aggregates, or any future call site).

KEY INVARIANT
-------------
TaxonomyNode.path is only unique *within* a single taxonomy
(client, taxonomy_id). Two different taxonomies (e.g. "Category" and
"Brand") legitimately both number their roots starting at "001" — so
every descendant lookup MUST be scoped by taxonomy_id, never by path
alone. This was the root cause of the version_aggregates bug where
selecting the "Bosch" brand root (path="001", depth=0) matched every
node across every taxonomy, since path__startswith="001" is a prefix
of everything.

Path matching also anchors on `path == X` OR `path startswith "X."`
(trailing separator), not a bare `startswith`, so a node like "001.2"
is never wrongly treated as an ancestor of an unrelated "001.20".
"""
import logging
from collections import defaultdict

from django.db.models import Q

from mysite.models.catalogue import TaxonomyNode, ItemTaxonomyNode

logger = logging.getLogger(__name__)

PATH_SEP = "."  # adjust if your TaxonomyNode.path uses a different separator


def parse_node_ids_param(request, param_name='taxonomy_node_ids'):
    """
    Returns a clean list of id strings for `param_name`, accepting either:
      - repeated params:      ?taxonomy_node_ids=6&taxonomy_node_ids=20
        (how the checkbox tree submits, via applyFilters()'s
        params.append(...) for each checked box)
      - one comma-joined param: ?taxonomy_node_ids=6,20
        (how server-rendered links build it, e.g. pagination links that
        interpolate the already-comma-joined `filters.taxonomy_node_ids`)

    Every call site that reads taxonomy_node_ids from a request should
    go through this, rather than calling request.GET.getlist(...)
    directly — that only handles the first shape, and silently mis-parses
    the second into a single bogus id like "6,20" that matches nothing.
    """
    raw = request.GET.getlist(param_name)
    if len(raw) == 1 and ',' in raw[0]:
        raw = raw[0].split(',')
    return [v for v in raw if v.strip()]


class TaxonomyFilterError(Exception):
    """Raised when a taxonomy_node_id doesn't resolve for this client."""


def _descendant_node_ids(node):
    """Node ids for `node` plus all its descendants, scoped to its own taxonomy."""
    prefix = f"{node.path}{PATH_SEP}"
    return (
        TaxonomyNode.objects
        .filter(client_id=node.client_id, taxonomy_id=node.taxonomy_id)
        .filter(Q(path=node.path) | Q(path__startswith=prefix))
        .values_list('id', flat=True)
    )


def resolve_item_ids_for_taxonomy_node(client, taxonomy_node_id):
    """
    item_ids for one selected node + all its descendants, scoped to its taxonomy.

    Returns [] (not None) if the node is valid but has no items mapped —
    callers should treat that as "filter matched nothing" (qs.none()),
    not "no filter applied".

    Raises TaxonomyFilterError if the node doesn't exist for this client.
    Callers must NOT silently swallow this — fail closed (qs.none()),
    otherwise a stale/bad node id looks identical to "no filter selected".
    """
    try:
        node = TaxonomyNode.objects.get(pk=taxonomy_node_id, client=client)
    except TaxonomyNode.DoesNotExist as exc:
        raise TaxonomyFilterError(
            f'taxonomy_node_id={taxonomy_node_id!r} not found for client'
        ) from exc

    descendant_ids = list(_descendant_node_ids(node))
    return list(
        ItemTaxonomyNode.objects
        .filter(node_id__in=descendant_ids)
        .values_list('item__item_id', flat=True)
        .distinct()
    )


def resolve_item_ids_for_multiple_nodes(client, taxonomy_node_ids):
    """
    Multi-select resolution across possibly-mixed taxonomies:

      - nodes selected within the SAME taxonomy are UNIONed
        e.g. picking "Brake Pads" and "Oil Filters" -> items in either.
      - selections across DIFFERENT taxonomies are INTERSECTED
        e.g. picking a Brand node AND a Category node -> items in both.

    This matches how the tree-based multi-select filter is meant to
    behave: check boxes across taxonomies to narrow down (AND), check
    multiple boxes within one taxonomy to broaden (OR).

    Returns:
        None  -> no valid nodes selected; caller should apply NO filter.
        list  -> item_ids to filter by (may be [] -> caller uses qs.none()).
    """
    node_ids = [nid for nid in taxonomy_node_ids if nid]
    if not node_ids:
        return None

    nodes = list(TaxonomyNode.objects.filter(client=client, pk__in=node_ids))
    found_ids = {n.pk for n in nodes}
    missing = {int(n) for n in node_ids} - found_ids
    if missing:
        logger.warning(
            f'resolve_item_ids_for_multiple_nodes: unknown node ids {missing} '
            f'for client={client!r}'
        )

    if not nodes:
        return None

    by_taxonomy = defaultdict(list)
    for node in nodes:
        by_taxonomy[node.taxonomy_id].append(node)

    result = None
    for _taxonomy_id, nodes_in_taxonomy in by_taxonomy.items():
        union_ids = set()
        for node in nodes_in_taxonomy:
            descendant_ids = list(_descendant_node_ids(node))
            item_ids = ItemTaxonomyNode.objects.filter(
                node_id__in=descendant_ids
            ).values_list('item__item_id', flat=True)
            union_ids |= set(item_ids)
        result = union_ids if result is None else (result & union_ids)

    return list(result)

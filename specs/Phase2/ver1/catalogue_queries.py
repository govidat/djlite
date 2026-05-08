# utils/catalogue_queries.py
"""
Query logic for the Generic Item Catalogue.
Handles: global/client merge, hierarchy filters,
faceted search, pagination.
Designed to integrate with fetch_clientstatic pattern.
"""

from django.db.models import Q, Prefetch
from django.core.cache import cache
from django.core.paginator import Paginator

from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, Item, ItemTaxonomyNode, ItemImage
)


# ── 1. Taxonomy resolution: global + client merge ────────────────────

def get_resolved_taxonomies(client):
    """
    Returns active taxonomies for a client, with client-specific
    taxonomies overriding global taxonomies of the same slug.

    Priority: client-specific > global fallback.
    """
    # Fetch both global and client taxonomies in one query
    qs = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        is_active=True
    ).order_by('slug', 'client')   # client rows come after global rows

    # Override: if slug exists at client level, suppress global
    seen   = {}
    result = []
    for taxonomy in qs:
        slug = taxonomy.slug
        if slug not in seen:
            seen[slug] = taxonomy
        else:
            # Client-specific overrides global (client is not None)
            if taxonomy.client is not None:
                seen[slug] = taxonomy

    return list(seen.values())


def get_taxonomy_tree(client, taxonomy_slug):
    """
    Returns the full node tree for a taxonomy as a nested dict list.
    Uses materialized path ordering for efficient flat→tree conversion.
    Result is cached per client+taxonomy.
    """
    cache_key = f"taxonomy_tree:{client.client_id}:{taxonomy_slug}"
    cached    = cache.get(cache_key)
    if cached:
        return cached

    # Resolve which taxonomy to use (client > global)
    taxonomy = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        slug=taxonomy_slug,
        is_active=True
    ).order_by('-client').first()   # client-specific first

    if not taxonomy:
        return []

    nodes = TaxonomyNode.objects.filter(
        taxonomy=taxonomy,
        is_active=True
    ).order_by('path')

    tree = _build_tree(list(nodes))

    cache.set(cache_key, tree, timeout=3600)
    return tree


def _build_tree(nodes):
    """Convert flat materialized-path list to nested dict tree."""
    node_map = {}
    roots    = []

    for node in nodes:
        entry = {
            'id':       node.id,
            'slug':     node.slug,
            'name':     node.name,   # modeltranslation resolves active language
            'depth':    node.depth,
            'path':     node.path,
            'children': [],
        }
        node_map[node.id] = entry

        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id]['children'].append(entry)
        else:
            roots.append(entry)

    return roots


# ── 2. Item queryset: global + client merge with filters ─────────────

def get_item_queryset(client, filters=None):
    """
    Returns a queryset of active Items for a client.
    Merges global items (client=None) with client-specific items.
    Client-specific item with same item_id overrides global item.

    filters dict (all optional):
      {
        'node_ids':    [1, 2, 3],    # TaxonomyNode PKs (AND logic)
        'taxonomy_slug': 'category', # filter by specific taxonomy
        'search':      'keyword',
        'attributes':  {'color': 'red'},  # JSONB attribute filters
        'status':      'active',
      }
    """
    filters = filters or {}

    # Base queryset — global + client items
    qs = Item.objects.filter(
        Q(client=None) | Q(client=client),
        status='active',
    ).select_related(
        'client', 
        'product_detail',
        'song_detail',
        'document_detail',
        'service_detail')
    .prefetch_related(
        Prefetch(
            'images',
            queryset=ItemImage.objects.filter(is_active=True).order_by('order')
                     if hasattr(ItemImage, 'is_active')
                     else ItemImage.objects.order_by('order'),
            to_attr='prefetched_images'
        ),
        Prefetch(
            'taxonomy_mappings',
            queryset=ItemTaxonomyNode.objects.select_related(
                'node', 'node__taxonomy'
            ),
            to_attr='prefetched_taxonomy_mappings'
        ),
    )

    # ── Hierarchy / node filter ───────────────────────────────────────
    node_ids = filters.get('node_ids', [])
    if node_ids:
        # AND logic: item must be in ALL selected nodes (or their subtrees)
        # For each selected node, expand to include all descendants
        expanded_node_ids = _expand_node_ids(node_ids)

        for node_id_set in expanded_node_ids:
            qs = qs.filter(
                taxonomy_mappings__node_id__in=node_id_set
            )

    # ── Taxonomy type filter ──────────────────────────────────────────
    taxonomy_slug = filters.get('taxonomy_slug')
    if taxonomy_slug:
        qs = qs.filter(
            taxonomy_mappings__node__taxonomy__slug=taxonomy_slug
        )

    # ── Text search ───────────────────────────────────────────────────
    search = filters.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(item_id__icontains=search)
        )

    # ── JSONB attribute filters ───────────────────────────────────────
    attribute_filters = filters.get('attributes', {})
    for key, value in attribute_filters.items():
        qs = qs.filter(**{f'attributes__{key}': value})

    # ── Status override ───────────────────────────────────────────────
    status = filters.get('status')
    if status:
        qs = qs.filter(status=status)

    # Deduplicate (joins can produce duplicates)
    qs = qs.distinct()

    # Override: suppress global items that have a client-specific version
    qs = _apply_client_override(qs, client)

    return qs.order_by('order', 'item_id')


def _expand_node_ids(node_id_list):
    """
    For each node_id, fetch itself + all descendant node IDs.
    Returns a list of sets — one set per originally selected node.
    Used for AND logic across multiple selections.

    For simple OR within one taxonomy: pass all node_ids as one group.
    """
    # Group node_ids — for now treat as one OR group per call
    # (Caller can split into multiple calls for AND across taxonomies)
    nodes = TaxonomyNode.objects.filter(id__in=node_id_list)
    expanded = set(node_id_list)

    for node in nodes:
        prefix = node.get_descendants_path_prefix()
        descendant_ids = TaxonomyNode.objects.filter(
            taxonomy=node.taxonomy,
            path__startswith=prefix
        ).values_list('id', flat=True)
        expanded.update(descendant_ids)

    return [expanded]   # single OR group — all expanded IDs


def _apply_client_override(qs, client):
    """
    If a client has an item with the same item_id as a global item,
    suppress the global item.
    Returns the filtered queryset.
    """
    # Get item_ids that exist at client level
    client_item_ids = Item.objects.filter(
        client=client,
        status='active'
    ).values_list('item_id', flat=True)

    if not client_item_ids:
        return qs

    # Exclude global items whose item_id is overridden by client
    qs = qs.exclude(
        client=None,
        item_id__in=client_item_ids
    )
    return qs


# ── 3. Paginator helper ───────────────────────────────────────────────

def paginate_items(qs, page_number=1, per_page=24):
    """
    Returns a Page object from Django's Paginator.
    per_page=24 works for 3-col and 4-col grids.
    """
    paginator = Paginator(qs, per_page)
    return paginator.get_page(page_number)


# ── 4. Facet counts ───────────────────────────────────────────────────

def get_facet_counts(client, base_qs, taxonomy_slug):
    """
    Returns node_id → item count for building filter sidebar.
    Only counts items already in the base queryset (respects active filters).
    """
    counts = (
        ItemTaxonomyNode.objects
        .filter(
            item__in=base_qs,
            node__taxonomy__slug=taxonomy_slug,
            node__is_active=True,
        )
        .values('node_id', 'node__slug', 'node__name')
        .annotate(count=models.Count('item', distinct=True))
        .order_by('node__path')
    )
    return {row['node_id']: row['count'] for row in counts}


# ── 5. Integration with fetch_clientstatic ────────────────────────────

def build_catalogue_payload(client, filters=None, page_number=1, per_page=24):
    """
    Builds the catalogue dict to be passed to templates.
    Can be called from a view directly (not cached — filters change per request).

    Returns:
    {
        'items':       [serialised item dicts],
        'taxonomies':  [resolved taxonomy trees],
        'pagination':  {page, num_pages, has_next, has_prev, ...},
        'filters':     {active filters},
    }
    """
    qs     = get_item_queryset(client, filters)
    page   = paginate_items(qs, page_number, per_page)
    items  = [_serialize_item(item) for item in page.object_list]

    # Build taxonomy trees for filter sidebar
    resolved_taxonomies = get_resolved_taxonomies(client)
    taxonomy_trees = []
    for taxonomy in resolved_taxonomies:
        tree = get_taxonomy_tree(client, taxonomy.slug)
        taxonomy_trees.append({
            'slug':  taxonomy.slug,
            'name':  taxonomy.name,
            'tree':  tree,
            'counts': get_facet_counts(client, qs, taxonomy.slug),
        })

    return {
        'items':      items,
        'taxonomies': taxonomy_trees,
        'pagination': {
            'page':         page.number,
            'num_pages':    page.paginator.num_pages,
            'has_next':     page.has_next(),
            'has_prev':     page.has_previous(),
            'next_page':    page.next_page_number() if page.has_next() else None,
            'prev_page':    page.previous_page_number() if page.has_previous() else None,
            'total_count':  page.paginator.count,
            'per_page':     per_page,
        },
        'filters':    filters or {},
    }


def _serialize_item(item):
    domain_obj = item.get_domain_object()

    # Price resolution: sub-model first, then attributes JSONB fallback
    price = None
    currency = 'INR'
    sku = ''

    if hasattr(domain_obj, 'price'):
        price    = domain_obj.price
        currency = getattr(domain_obj, 'currency', 'INR')
    else:
        price    = item.attributes.get('price')
        currency = item.attributes.get('currency', 'INR')

    if hasattr(domain_obj, 'sku'):
        sku = domain_obj.sku

    return {
        'id':          item.id,
        'item_id':     item.item_id,
        'domain':      item.domain,
        'name':        item.name,
        'description': item.description,
        'image_url':   item.image_url,
        'image_alt':   item.image_alt,
        'price':       price,
        'currency':    currency,
        'sku':         sku,
        'attributes':  item.attributes,
        # domain object serialised separately for templates that need it
        'domain_data': _serialize_domain(domain_obj),
    }

def _serialize_domain(domain_obj):
    if not domain_obj:
        return {}
    # Generic field dump — exclude internal Django fields
    from utils.common_functions import serialize_model
    return serialize_model(domain_obj, exclude={'id', 'item_id'})
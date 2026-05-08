# utils/catalogue_queries_v2.py
"""
Query logic for the revised Generic Item Catalogue.
Key additions over v1:
  - Global/client merge with proper override chain
  - Attribute inheritance resolution (node hierarchy → global item → item)
  - Faceted filter using structured ItemAttributeValue (not JSONB only)
  - Taxonomy resolution: client nodes > global nodes of same slug
"""

from django.db.models import Q, Prefetch, Count, OuterRef, Subquery
from django.core.cache import cache
from django.core.paginator import Paginator

from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItem, GlobalItemAttributeValue,
    Item, ItemTaxonomyNode, ItemAttributeValue,
    ItemImage, ItemVariant,
)


# ── 1. Taxonomy resolution ────────────────────────────────────────────

def get_resolved_taxonomies(client):
    """
    Returns active taxonomies for a client.
    Client-specific taxonomy overrides global taxonomy of the same slug.
    Returns list ordered by order field.
    """
    qs = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        is_active=True
    ).order_by('slug', '-client_id')  # client rows sort before None

    seen   = {}
    result = []
    for taxonomy in qs:
        slug = taxonomy.slug
        # Client-specific wins
        if slug not in seen or taxonomy.client is not None:
            seen[slug] = taxonomy

    # Sort by order
    return sorted(seen.values(), key=lambda t: t.order)


def get_taxonomy_tree(client, taxonomy_slug, include_counts=False, base_qs=None):
    """
    Returns nested tree dict for a taxonomy.
    Merges global nodes + client nodes. Client nodes at same path override global.
    Cached per client+slug (invalidated by signal on TaxonomyNode save).

    If include_counts=True, annotates each node with item count from base_qs.
    """
    cache_key = f"taxonomy_tree:{client.client_id}:{taxonomy_slug}"

    if not include_counts:
        cached = cache.get(cache_key)
        if cached:
            return cached

    # Resolve taxonomy (client > global)
    taxonomy = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        slug=taxonomy_slug,
        is_active=True
    ).order_by('-client_id').first()  # client-specific first

    if not taxonomy:
        return []

    # Fetch all nodes: global + client
    nodes = TaxonomyNode.objects.filter(
        taxonomy=taxonomy,
        is_active=True
    ).filter(
        Q(client=None) | Q(client=client)
    ).prefetch_related(
        'attribute_types__predefined_values'
    ).order_by('path')

    # Build node list, client node overrides global node at same slug
    node_map_by_slug = {}
    ordered_nodes    = []
    for node in nodes:
        key = node.slug
        if key not in node_map_by_slug or node.client is not None:
            node_map_by_slug[key] = node
    # Rebuild ordered list from deduped map
    ordered_nodes = sorted(node_map_by_slug.values(), key=lambda n: n.path)

    # Build counts dict if requested
    counts = {}
    if include_counts and base_qs is not None:
        count_qs = (
            ItemTaxonomyNode.objects
            .filter(item__in=base_qs, node__in=ordered_nodes)
            .values('node_id')
            .annotate(count=Count('item', distinct=True))
        )
        counts = {row['node_id']: row['count'] for row in count_qs}

    tree = _build_tree(ordered_nodes, counts)

    if not include_counts:
        cache.set(cache_key, tree, timeout=3600)

    return tree


def _build_tree(nodes, counts=None):
    """Convert flat materialized-path list to nested dict tree."""
    counts    = counts or {}
    node_map  = {}
    roots     = []

    for node in nodes:
        # Build attribute types for this node
        attr_types = []
        for at in node.attribute_types.all():
            attr_types.append({
                'id':           at.id,
                'slug':         at.slug,
                'name':         at.name,
                'field_type':   at.field_type,
                'is_filterable': at.is_filterable,
                'values': [
                    {'id': v.id, 'slug': v.slug, 'name': v.name}
                    for v in at.predefined_values.all()
                ],
            })

        entry = {
            'id':           node.id,
            'slug':         node.slug,
            'name':         node.name,
            'depth':        node.depth,
            'path':         node.path,
            'gpc_code':     node.gpc_code,
            'is_global':    node.client is None,
            'attr_types':   attr_types,
            'count':        counts.get(node.id, 0),
            'children':     [],
        }
        node_map[node.id] = entry

        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id]['children'].append(entry)
        else:
            roots.append(entry)

    return roots


# ── 2. Attribute type resolution for filter sidebar ───────────────────

def get_filterable_attribute_types(client, taxonomy_slug, active_node_ids=None):
    """
    Returns all filterable NodeAttributeTypes for the selected taxonomy,
    optionally scoped to selected nodes and their ancestors.
    Used to build the attribute filter section of the sidebar.
    """
    qs = NodeAttributeType.objects.filter(
        Q(client=None) | Q(client=client),
        is_filterable=True,
        node__taxonomy__slug=taxonomy_slug,
    ).filter(
        Q(node__client=None) | Q(node__client=client)
    ).select_related('node').prefetch_related('predefined_values').order_by(
        'node__depth', 'order'
    )

    if active_node_ids:
        # Only show attr types from selected nodes + their ancestors
        selected_nodes = TaxonomyNode.objects.filter(id__in=active_node_ids)
        relevant_paths = set()
        for node in selected_nodes:
            relevant_paths.add(node.path)
            relevant_paths.update(node.get_ancestor_paths())
        qs = qs.filter(node__path__in=relevant_paths)

    return qs


# ── 3. Item queryset with global/client merge ─────────────────────────

def get_item_queryset(client, filters=None):
    """
    Returns Item queryset for a client.

    Merge logic (priority order, highest to lowest):
      1. Client-specific items (client=X)
      2. Shared items (client=None) NOT overridden by client item
         (same item_id exists at client level → suppress shared version)
      3. Derived items: client items linked to a GlobalItem reference

    filters dict:
      node_ids:        [int]  — TaxonomyNode PKs (OR within taxonomy, AND across)
      attr_values:     {attribute_type_id: [predefined_value_id, ...]}
      attr_text:       {attribute_type_slug: 'value'}
      search:          str
      domain:          str
      status:          str (default 'active')
    """
    filters = filters or {}
    status  = filters.get('status', 'active')

    # Base queryset — client + shared items
    qs = Item.objects.filter(
        Q(client=client) | Q(client=None),
        status=status,
    ).select_related(
        'client',
        'global_item',
        'product_detail',
        'song_detail',
        'document_detail',
        'service_detail',
    ).prefetch_related(
        Prefetch(
            'images',
            queryset=ItemImage.objects.filter(is_primary=True).order_by('order'),
            to_attr='prefetched_primary_images'
        ),
        Prefetch(
            'taxonomy_mappings',
            queryset=ItemTaxonomyNode.objects.select_related(
                'node', 'node__taxonomy'
            ),
            to_attr='prefetched_taxonomy_mappings'
        ),
        Prefetch(
            'attribute_values',
            queryset=ItemAttributeValue.objects.select_related(
                'attribute_type', 'predefined_value'
            ),
            to_attr='prefetched_attribute_values'
        ),
    )

    # ── Filter: taxonomy node (OR within same taxonomy, AND across) ───
    node_ids = filters.get('node_ids', [])
    if node_ids:
        expanded = _expand_node_ids_grouped(node_ids)
        for id_group in expanded:
            qs = qs.filter(taxonomy_mappings__node_id__in=id_group)

    # ── Filter: attribute values (structured) ─────────────────────────
    attr_values = filters.get('attr_values', {})
    for attr_type_id, value_ids in attr_values.items():
        if value_ids:
            qs = qs.filter(
                Q(attribute_values__attribute_type_id=attr_type_id,
                  attribute_values__predefined_value_id__in=value_ids) |
                Q(global_item__attribute_values__attribute_type_id=attr_type_id,
                  global_item__attribute_values__predefined_value_id__in=value_ids)
            )

    # ── Filter: free-text attribute values ────────────────────────────
    attr_text = filters.get('attr_text', {})
    for attr_slug, value in attr_text.items():
        if value:
            qs = qs.filter(
                Q(attribute_values__attribute_type__slug=attr_slug,
                  attribute_values__value_text__icontains=value) |
                Q(attributes__contains={attr_slug: value})
            )

    # ── Filter: domain ────────────────────────────────────────────────
    domain = filters.get('domain')
    if domain:
        qs = qs.filter(domain=domain)

    # ── Filter: text search ───────────────────────────────────────────
    search = filters.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(item_id__icontains=search) |
            Q(global_item__name__icontains=search) |
            #Q(global_item__brand__icontains=search) |
            Q(product_detail__sku__icontains=search)
        )

    # Deduplicate from joins
    qs = qs.distinct()

    # Suppress shared items overridden by client-specific items
    qs = _apply_client_override(qs, client)

    return qs.order_by('order', 'item_id')


def _expand_node_ids_grouped(node_id_list):
    """
    Groups node_ids by taxonomy, expands each to include descendants.
    Returns list of id sets — one per taxonomy (AND logic across taxonomies).
    """
    nodes    = TaxonomyNode.objects.filter(id__in=node_id_list).select_related('taxonomy')
    by_tax   = {}
    for node in nodes:
        by_tax.setdefault(node.taxonomy_id, []).append(node)

    groups = []
    for taxonomy_id, tax_nodes in by_tax.items():
        expanded = set(n.id for n in tax_nodes)
        for node in tax_nodes:
            prefix = node.get_descendant_path_prefix()
            descendant_ids = TaxonomyNode.objects.filter(
                taxonomy_id=taxonomy_id,
                path__startswith=prefix
            ).values_list('id', flat=True)
            expanded.update(descendant_ids)
        groups.append(expanded)

    return groups


def _apply_client_override(qs, client):
    """
    Suppress shared (client=None) items whose item_id exists at client level.
    This ensures client-specific version is always shown, never both.
    """
    client_item_ids = Item.objects.filter(
        client=client, status='active'
    ).values_list('item_id', flat=True)

    if not client_item_ids:
        return qs

    return qs.exclude(client=None, item_id__in=client_item_ids)


# ── 4. Serialisation ──────────────────────────────────────────────────

def _resolve_price(item):
    """Resolve price from sub-model → global_item → attributes JSONB."""
    domain_obj = item.get_domain_object()
    if domain_obj and hasattr(domain_obj, 'price') and domain_obj.price is not None:
        return str(domain_obj.price), getattr(domain_obj, 'currency', 'INR')
    if item.global_item:
        gi_attrs = item.global_item.attributes
        if 'price' in gi_attrs:
            return str(gi_attrs['price']), gi_attrs.get('currency', 'INR')
    attrs = item.resolved_attributes()
    return str(attrs.get('price', '')), attrs.get('currency', 'INR')


def _resolve_sku(item):
    domain_obj = item.get_domain_object()
    if domain_obj and hasattr(domain_obj, 'sku'):
        return domain_obj.sku
    return item.resolved_attributes().get('sku', '')


def serialize_item(item):
    """Serialise an Item to a template-ready dict."""
    primary_images = getattr(item, 'prefetched_primary_images', [])
    image_url  = primary_images[0].image_url if primary_images else item.resolved_image_url()
    image_alt  = primary_images[0].alt if primary_images else item.image_alt

    price, currency = _resolve_price(item)

    # Attribute values (from prefetch)
    attr_values = {}
    for av in getattr(item, 'prefetched_attribute_values', []):
        attr_values[av.attribute_type.slug] = av.resolved_value()

    # Global item attribute values as base (overridden above)
    if item.global_item:
        for av in item.global_item.attribute_values.all():
            if av.attribute_type.slug not in attr_values:
                attr_values[av.attribute_type.slug] = av.resolved_value()

    return {
        'id':           item.id,
        'item_id':      item.item_id,
        'domain':       item.domain,
        'name':         item.resolved_name(),
        'description':  item.resolved_description(),
        #'brand':        item.resolved_brand(),
        'image_url':    image_url,
        'image_alt':    image_alt,
        'price':        price,
        'currency':     currency,
        'sku':          _resolve_sku(item),
        'is_global':    item.client is None,
        'has_global_ref': item.global_item_id is not None,
        'gtin':         item.gtin or (item.global_item.gtin if item.global_item else ''),
        'gpc_brick_code': item.gpc_brick_code,
        'attr_values':  attr_values,  # for filter badge display
        'attributes':   item.resolved_attributes(),
    }


# ── 5. Full payload builder ───────────────────────────────────────────

def build_catalogue_payload(client, filters=None, page_number=1, per_page=24):
    """
    Builds the full catalogue context dict for templates.
    Not cached (filter-dependent). Taxonomy trees are cached separately.
    """
    filters  = filters or {}
    qs       = get_item_queryset(client, filters)
    paginator = Paginator(qs, per_page)
    page      = paginator.get_page(page_number)

    items = [serialize_item(item) for item in page.object_list]

    # Taxonomy trees with counts
    resolved_taxonomies = get_resolved_taxonomies(client)
    taxonomy_trees = []
    for taxonomy in resolved_taxonomies:
        tree = get_taxonomy_tree(
            client=client,
            taxonomy_slug=taxonomy.slug,
            include_counts=True,
            base_qs=qs,
        )
        # Filterable attribute types for selected nodes
        active_node_ids = filters.get('node_ids', [])
        attr_types = []
        if active_node_ids:
            attr_type_qs = get_filterable_attribute_types(
                client, taxonomy.slug, active_node_ids
            )
            attr_types = [
                {
                    'id':         at.id,
                    'slug':       at.slug,
                    'name':       at.name,
                    'field_type': at.field_type,
                    'values': [
                        {'id': v.id, 'slug': v.slug, 'name': v.name}
                        for v in at.predefined_values.all()
                    ],
                }
                for at in attr_type_qs
            ]

        taxonomy_trees.append({
            'slug':      taxonomy.slug,
            'name':      taxonomy.name,
            'tree':      tree,
            'attr_types': attr_types,
        })

    return {
        'items':      items,
        'taxonomies': taxonomy_trees,
        'pagination': {
            'page':        page.number,
            'num_pages':   paginator.num_pages,
            'has_next':    page.has_next(),
            'has_prev':    page.has_previous(),
            'next_page':   page.next_page_number() if page.has_next() else None,
            'prev_page':   page.previous_page_number() if page.has_previous() else None,
            'total_count': paginator.count,
            'per_page':    per_page,
        },
        'filters': filters,
    }


# ── 6. Global Item helpers (for admin dropdowns) ──────────────────────

def get_global_items_for_client(client, domain=None, search=None):
    """
    Returns GlobalItems available for a client to reference.
    Used in admin dropdown when creating a client Item.
    """
    qs = GlobalItem.objects.filter(status='active')
    if domain:
        qs = qs.filter(domain=domain)
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(global_item_id__icontains=search) |
            #Q(brand__icontains=search) |
            Q(gtin__icontains=search)
        )
    return qs.order_by('global_item_id')


def get_global_nodes_for_client(client, taxonomy_slug=None):
    """
    Returns global TaxonomyNodes available for a client to reference.
    Used when client admin builds content using global taxonomy nodes.
    """
    qs = TaxonomyNode.objects.filter(client=None, is_active=True)
    if taxonomy_slug:
        qs = qs.filter(taxonomy__slug=taxonomy_slug)
    return qs.select_related('taxonomy').order_by('path')

# utils/catalogue_queries.py
"""
Generic Item Catalogue — Query Layer (Optimised)

Key improvements over previous version:
1. GlobalItemAttributeValue N+1 fixed — bulk prefetch, not per-item loop
2. ItemMedia removed from catalogue queryset — fetched only in item_detail
3. Brand facet uses taxonomy tree (already fetched) — no extra query
4. price_stats uses separate lightweight query — not the full qs
5. Client template resolution added to payload
"""

import logging
from django.db.models import Q, Prefetch, Count, Min, Max
from django.core.cache import cache
from django.core.paginator import Paginator

from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItem, GlobalItemAttributeValue,
    Item, ItemTaxonomyNode, ItemAttributeValue,
    ItemVariant,
    # ItemMedia intentionally NOT imported here
    # — fetched only in item_detail view
)
import os
from django.template.loader import get_template
from django.template import TemplateDoesNotExist

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# 1. TAXONOMY RESOLUTION
# ══════════════════════════════════════════════════════════════════════

def get_resolved_taxonomies(client):
    """
    Returns active taxonomies for a client, client-specific overriding global.
    Ordered by taxonomy.order.
    """
    qs = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        is_active=True
    ).order_by('slug', '-client_id')

    seen = {}
    for taxonomy in qs:
        slug = taxonomy.slug
        if slug not in seen or taxonomy.client is not None:
            seen[slug] = taxonomy

    return sorted(seen.values(), key=lambda t: t.order)


def get_taxonomy_tree(client, taxonomy_slug, include_counts=False, base_qs=None):
    """
    Returns nested tree dict. Cached when include_counts=False.
    When include_counts=True, counts are computed from base_qs.
    """
    cache_key = f"taxonomy_tree:{client.client_id}:{taxonomy_slug}"

    if not include_counts:
        cached = cache.get(cache_key)
        if cached:
            return cached

    taxonomy = Taxonomy.objects.filter(
        Q(client=None) | Q(client=client),
        slug=taxonomy_slug,
        is_active=True
    ).order_by('-client_id').first()

    if not taxonomy:
        return []

    nodes = TaxonomyNode.objects.filter(
        taxonomy=taxonomy,
        is_active=True
    ).filter(
        Q(client=None) | Q(client=client)
    ).prefetch_related(
        'attribute_types__predefined_values'
    ).order_by('path')

    # Client node overrides global node of same slug
    node_map_by_slug = {}
    for node in nodes:
        key = node.slug
        if key not in node_map_by_slug or node.client is not None:
            node_map_by_slug[key] = node
    ordered_nodes = sorted(node_map_by_slug.values(), key=lambda n: n.path)

    # Counts — one query for all nodes at once
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
    """Convert flat ordered list to nested dict tree."""
    counts   = counts or {}
    node_map = {}
    roots    = []

    for node in nodes:
        attr_types = []
        for at in node.attribute_types.all():
            attr_types.append({
                'id':            at.id,
                'slug':          at.slug,
                'name':          at.name,
                'field_type':    at.field_type,
                'is_filterable': at.is_filterable,
                'values': [
                    {'id': v.id, 'slug': v.slug, 'name': v.name}
                    for v in at.predefined_values.all()
                ],
            })

        entry = {
            'id':        node.id,
            'slug':      node.slug,
            'name':      node.name,
            'depth':     node.depth,
            'path':      node.path,
            'gpc_code':  node.gpc_code,
            'is_global': node.client is None,
            'attr_types': attr_types,
            'count':     counts.get(node.id, 0),
            'children':  [],
        }
        node_map[node.id] = entry

        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id]['children'].append(entry)
        else:
            roots.append(entry)

    return roots


def get_filterable_attribute_types(client, taxonomy_slug, active_node_ids=None):
    """
    Returns filterable NodeAttributeTypes for a taxonomy.
    Scoped to selected nodes + ancestors if active_node_ids provided.
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
        selected_nodes = TaxonomyNode.objects.filter(id__in=active_node_ids)
        relevant_paths = set()
        for node in selected_nodes:
            relevant_paths.add(node.path)
            relevant_paths.update(node.get_ancestor_paths())
        qs = qs.filter(node__path__in=relevant_paths)

    return qs


# ══════════════════════════════════════════════════════════════════════
# 2. ITEM QUERYSET
# ══════════════════════════════════════════════════════════════════════
def get_base_item_ids(client, status='active'):
    """
    Cache the base set of item IDs for a client.
    This is the expensive part — 6-table JOIN with subquery.
    Filters are applied after, against this cached ID list.
    TTL: short (5 minutes) since stock/status can change.
    """
    cache_key = f"catalogue_base_ids:{client.client_id}:{status}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # The expensive query — client override logic + 6 LEFT OUTER JOINs
    client_item_ids = set(
        Item.objects.filter(client=client, status=status)
        .values_list('item_id', flat=True)
    )
    base_ids = list(
        Item.objects.filter(
            Q(client=client) | Q(client=None),
            status=status,
        ).exclude(
            client=None,
            item_id__in=client_item_ids
        ).values_list('id', flat=True)
    )

    cache.set(cache_key, base_ids, timeout=300)  # 5 minutes
    return base_ids

def get_item_queryset(client, filters=None):
    """
    Returns Item queryset for catalogue listing.

    Deliberately excludes ItemMedia — media is large and only
    needed for item_detail. Only primary image URL is resolved
    from Item.image_url / GlobalItem.image_url.

    GlobalItemAttributeValue is prefetched in bulk here
    (fixes N+1 seen in SQL log).
    """
    filters = filters or {}
    #status  = filters.get('status', 'active')
    #qs = Item.objects.filter(
    #    Q(client=client) | Q(client=None),
    #    status=status,    
    qs = Item.objects.filter(
        id__in=get_base_item_ids(client)    
    ).select_related(
        'client',
        'global_item',
        'product_detail',
        'song_detail',
        'document_detail',
        'service_detail',
    ).prefetch_related(
        # ── ItemTaxonomyNode with node + taxonomy ─────────────────
        Prefetch(
            'taxonomy_mappings',
            queryset=ItemTaxonomyNode.objects.select_related(
                'node', 'node__taxonomy'
            ).order_by('node__taxonomy__order', 'node__depth'),
            to_attr='prefetched_taxonomy_mappings'
        ),
        # ── Item-level attribute values ────────────────────────────
        Prefetch(
            'attribute_values',
            queryset=ItemAttributeValue.objects.select_related(
                'attribute_type', 'predefined_value'
            ).order_by('attribute_type__order'),
            to_attr='prefetched_attribute_values'
        ),
        # ── GlobalItem attribute values (bulk — fixes N+1) ─────────
        # Accessed via item.global_item.prefetched_global_attr_values
        Prefetch(
            'global_item__attribute_values',
            queryset=GlobalItemAttributeValue.objects.select_related(
                'attribute_type', 'predefined_value'
            ).order_by('attribute_type__order'),
            to_attr='prefetched_global_attr_values'
        ),
        # ── Primary media only (image for card display) ────────────
        # Full media list is NOT prefetched here — only for item_detail
        #Prefetch(
        #    'medias',
        #    queryset=__import__(
        #        'mysite.models.catalogue', fromlist=['ItemMedia']
        #    ).ItemMedia.objects.filter(
        #        is_primary=True, media_type='image'
        #    ).order_by('order'),
        #    to_attr='prefetched_primary_image'
        #),
    )

    # ── Taxonomy node filters ─────────────────────────────────────
    node_ids = filters.get('node_ids', [])
    if node_ids:
        expanded = _expand_node_ids_grouped(node_ids)
        for id_group in expanded:
            qs = qs.filter(
                Q(taxonomy_mappings__node_id__in=id_group) |
                Q(global_item__taxonomy_mappings__node_id__in=id_group)
            ).distinct()

    # ── Structured attribute value filters ────────────────────────
    attr_values = filters.get('attr_values', {})
    for attr_type_id, value_ids in attr_values.items():
        if value_ids:
            qs = qs.filter(
                Q(attribute_values__attribute_type_id=attr_type_id,
                  attribute_values__predefined_value_id__in=value_ids) |
                Q(global_item__attribute_values__attribute_type_id=attr_type_id,
                  global_item__attribute_values__predefined_value_id__in=value_ids)
            ).distinct()

    # ── Domain sub-model field filters ────────────────────────────
    # Price range
    price_min = filters.get('price_min')
    price_max = filters.get('price_max')
    if price_min is not None:
        qs = qs.filter(product_detail__price__gte=price_min)
    if price_max is not None:
        qs = qs.filter(product_detail__price__lte=price_max)

    # In stock
    if filters.get('in_stock'):
        qs = qs.filter(product_detail__stock_quantity__gt=0)

    # Song filters
    if filters.get('genre'):
        qs = qs.filter(song_detail__genre__iexact=filters['genre'])

    # Document filters
    if filters.get('format'):
        qs = qs.filter(document_detail__format__iexact=filters['format'])
    if filters.get('is_free') is not None:
        qs = qs.filter(document_detail__is_free=filters['is_free'])

    # ── Text search ───────────────────────────────────────────────
    search = filters.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(item_id__icontains=search) |
            Q(global_item__name__icontains=search) |
            Q(product_detail__sku__icontains=search)
        )

    # ── Brand filter (via taxonomy node) ─────────────────────────
    brands = filters.get('brands', [])
    if brands:
        qs = qs.filter(
            Q(taxonomy_mappings__node__name__in=brands,
              taxonomy_mappings__node__taxonomy__slug='brand') |
            Q(global_item__taxonomy_mappings__node__name__in=brands,
              global_item__taxonomy_mappings__node__taxonomy__slug='brand')
        ).distinct()

    qs = qs.distinct()
    qs = _apply_client_override(qs, client)

    return qs.order_by('order', 'item_id')

 
def _expand_node_ids_grouped(node_id_list):
    """
    Groups node_ids by taxonomy, expands each to include descendants.
    Returns list of id sets — AND logic across taxonomies, OR within.
    """
    nodes  = TaxonomyNode.objects.filter(id__in=node_id_list).select_related('taxonomy')
    by_tax = {}
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
    """Suppress shared items whose item_id exists at client level."""
    client_item_ids = Item.objects.filter(
        client=client, status='active'
    ).values_list('item_id', flat=True)

    if not client_item_ids:
        return qs

    return qs.exclude(client=None, item_id__in=client_item_ids)


# ══════════════════════════════════════════════════════════════════════
# 3. SERIALISATION
# ══════════════════════════════════════════════════════════════════════

def _resolve_price(item):
    domain_obj = item.get_domain_object()
    if domain_obj and hasattr(domain_obj, 'price') and domain_obj.price is not None:
        return str(domain_obj.price), getattr(domain_obj, 'currency', 'INR')
    if item.global_item:
        gi_attrs = item.global_item.attributes
        if 'price' in gi_attrs:
            return str(gi_attrs['price']), gi_attrs.get('currency', 'INR')
    return '', 'INR'


def _resolve_sku(item):
    domain_obj = item.get_domain_object()
    if domain_obj and hasattr(domain_obj, 'sku'):
        return domain_obj.sku or ''
    return ''


def _resolve_stock(item):
    domain_obj = item.get_domain_object()
    if domain_obj and hasattr(domain_obj, 'stock_quantity'):
        return domain_obj.stock_quantity
    return None


def serialize_item(item):
    """
    Serialise Item to template-ready dict for catalogue listing.
    Uses prefetched data — no additional DB queries.

    GlobalItemAttributeValue N+1 fix:
    Uses item.global_item.prefetched_global_attr_values (prefetched in bulk)
    instead of item.global_item.attribute_values.all() (triggers per-item query).
    """
    """
    ItemMedia is only used in Item Detail to reduce the volume
    # Primary image: prefetched_primary_image → resolved_image_url()
    primary_images = getattr(item, 'prefetched_primary_image', [])
    image_url = (
        primary_images[0].media_url if primary_images
        else item.resolved_image_url()
    )
    image_alt = (
        primary_images[0].alt if primary_images
        else item.image_alt
    )
    """
    image_url = item.resolved_image_url()
    image_alt = item.image_alt or item.resolved_name()
    
    price, currency = _resolve_price(item)

    # Attribute values — item level overrides global level
    # Uses prefetched data on both item and global_item
    attr_values = {}

    # Global base (use prefetched list, not .all())
    if item.global_item:
        global_avs = getattr(
            item.global_item, 'prefetched_global_attr_values', None
        )
        if global_avs is None:
            # Fallback if prefetch wasn't set up (shouldn't happen)
            global_avs = item.global_item.attribute_values.select_related(
                'attribute_type', 'predefined_value'
            ).all()
        for av in global_avs:
            attr_values[av.attribute_type.slug] = av.resolved_value()

    # Item overrides (use prefetched list)
    for av in getattr(item, 'prefetched_attribute_values', []):
        attr_values[av.attribute_type.slug] = av.resolved_value()

    # Domain-specific fields for display in card
    domain_obj = item.get_domain_object()
    domain_data = {}
    if domain_obj:
        if hasattr(domain_obj, 'duration_s') and domain_obj.duration_s:
            mins = domain_obj.duration_s // 60
            secs = domain_obj.duration_s % 60
            domain_data['duration'] = f"{mins}:{secs:02d}"
        if hasattr(domain_obj, 'genre') and domain_obj.genre:
            domain_data['genre'] = domain_obj.genre
        if hasattr(domain_obj, 'format') and domain_obj.format:
            domain_data['format'] = domain_obj.format
        if hasattr(domain_obj, 'is_free'):
            domain_data['is_free'] = domain_obj.is_free

    return {
        'id':           item.id,
        'item_id':      item.item_id,
        'domain':       item.domain,
        'name':         item.resolved_name(),
        'description':  item.resolved_description(),
        'image_url':    image_url,
        'image_alt':    image_alt,
        'price':        price,
        'currency':     currency,
        'sku':          _resolve_sku(item),
        'stock':        _resolve_stock(item),
        'is_global':    item.client is None,
        'has_global_ref': item.global_item_id is not None,
        'gtin':         item.gtin or (item.global_item.gtin if item.global_item else ''),
        'gpc_brick_code': item.gpc_brick_code,
        'attr_values':  attr_values,
        'attributes':   item.resolved_attributes(),
        'domain_data':  domain_data,   # domain-specific display fields
    }


# ══════════════════════════════════════════════════════════════════════
# 4. PAYLOAD BUILDER
# ══════════════════════════════════════════════════════════════════════

def build_catalogue_payload(client, filters=None, page_number=1, per_page=24):
    """
    Builds full catalogue context dict for templates.

    Query budget (optimised from SQL log analysis):
      1. Item fetch with select_related + prefetch_related  (1 query + ~5 prefetch)
      2. Paginator COUNT                                    (1 query)
      3. Taxonomy trees (cached)                           (0-2 queries)
      4. Node counts (per taxonomy)                        (1 query each)
      5. Attr types (per taxonomy)                         (1 query each)
      6. Price stats                                       (1 query)
      7. Brand nodes from tree                             (0 — reuses tree data)
      8. Client template resolution                        (0 — filesystem check)

    GlobalItemAttributeValue N+1 eliminated by prefetch in get_item_queryset.
    """
    filters   = filters or {}
    qs        = get_item_queryset(client, filters)
    paginator = Paginator(qs, per_page)
    page      = paginator.get_page(page_number)

    items = [serialize_item(item) for item in page.object_list]

    # Taxonomy trees with counts and attribute types
    resolved_taxonomies = get_resolved_taxonomies(client)
    taxonomy_trees = []
    for taxonomy in resolved_taxonomies:
        tree = get_taxonomy_tree(
            client=client,
            taxonomy_slug=taxonomy.slug,
            include_counts=True,
            base_qs=qs,
        )
        active_node_ids = filters.get('node_ids', [])
        attr_type_qs = get_filterable_attribute_types(
            client, taxonomy.slug,
            active_node_ids if active_node_ids else None
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
            'slug':       taxonomy.slug,
            'name':       taxonomy.name,
            'tree':       tree,
            'attr_types': attr_types,
        })

    # Brand facets — extract from taxonomy tree (no extra query)
    # Brand taxonomy tree is already built above; walk it for leaf nodes
    brands_list = _extract_brand_facets(taxonomy_trees, qs)

    # Price stats — lightweight separate query on ProductItem only
    price_stats_raw = qs.filter(
        product_detail__price__isnull=False
    ).aggregate(
        price_min=Min('product_detail__price'),
        price_max=Max('product_detail__price'),
    )
    price_stats = {
        'min':        float(price_stats_raw['price_min'] or 0),
        'max':        float(price_stats_raw['price_max'] or 0),
        'active_min': filters.get('price_min'),
        'active_max': filters.get('price_max'),
    }

    # Domain-level filter options (for client-customisable sidebar)
    domain_filters = _build_domain_filters(qs, filters)

    # Client template resolution
    template_info = _resolve_client_templates(client)

    return {
        'items':          items,
        'taxonomies':     taxonomy_trees,
        'brands':         brands_list,
        'price_stats':    price_stats,
        'domain_filters': domain_filters,
        'template_info':  template_info,
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


def _extract_brand_facets(taxonomy_trees, base_qs):
    """
    Extract brand node facets from the already-built taxonomy tree.
    Avoids a separate DB query — reuses count data in the tree.
    """
    brand_taxonomy = next(
        (t for t in taxonomy_trees if t['slug'] == 'brand'),
        None
    )
    if not brand_taxonomy:
        return []

    # Flatten tree to find all nodes with counts > 0
    def flatten_tree(nodes):
        result = []
        for node in nodes:
            if node['count'] > 0:
                result.append({
                    'id':    node['id'],
                    'name':  node['name'],
                    'depth': node['depth'],
                    'count': node['count'],
                })
            result.extend(flatten_tree(node.get('children', [])))
        return result

    return sorted(
        flatten_tree(brand_taxonomy['tree']),
        key=lambda b: (b['depth'], b['name'])
    )


def _build_domain_filters(qs, filters):
    """
    Build domain-specific filter options for client-customisable sidebar.
    Each domain returns available filter values from the current queryset.

    These are passed to templates as catalogue.domain_filters and can
    be selectively shown by client-specific sidebar templates.
    """
    domain_filters = {}

    # Genre options (for Song domain)
    genres = (
        qs.filter(song_detail__genre__isnull=False)
        .exclude(song_detail__genre='')
        .values_list('song_detail__genre', flat=True)
        .distinct()
        .order_by('song_detail__genre')
    )
    if genres:
        domain_filters['genres'] = list(genres)

    # Format options (for Document domain)
    formats = (
        qs.filter(document_detail__format__isnull=False)
        .exclude(document_detail__format='')
        .values_list('document_detail__format', flat=True)
        .distinct()
        .order_by('document_detail__format')
    )
    if formats:
        domain_filters['formats'] = list(formats)

    # Free/paid (for Document domain)
    has_documents = qs.filter(domain='document').exists()
    if has_documents:
        domain_filters['has_free_documents'] = True

    return domain_filters


def _resolve_client_templates(client):
    cache_key = f"client_templates:{client.client_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    from mysite.models.page import ClientTemplate
    templates = ClientTemplate.objects.filter(
        client=client, is_active=True
    ).values('template_key', 'language_code')

    # Build the resolution dict
    result = _build_template_resolution(client, templates)

    cache.set(cache_key, result, timeout=3600)
    return result


def _resolve_client_templates(client):
    """
    Resolves which templates to use for this client's catalogue.

    Priority:
      1. Client-specific: templates/catalogue/{client_id}/filter_sidebar.html
      2. Default:         templates/catalogue/partials/filter_sidebar.html

    Returns a dict of template paths for use in views/templates.
    No DB query — purely filesystem resolution.
    """
    cache_key = f"client_templates:{client.client_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    client_id = client.client_id

    def resolve(template_name):
        client_path = f"catalogue/{client_id}/{template_name}"
        default_path = f"catalogue/partials/{template_name}"
        try:
            get_template(client_path)
            return client_path
        except TemplateDoesNotExist:
            return default_path

    result = {
        'filter_sidebar': resolve('filter_sidebar.html'),
        'items_list':     resolve('items_list.html'),
        'item_card':      resolve('item_card.html'),
        'pagination':     resolve('pagination.html'),
    }
    cache.set(cache_key, result, timeout=3600)
    return result    




# ══════════════════════════════════════════════════════════════════════
# 5. GLOBAL ITEM HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_global_items_for_client(client, domain=None, search=None):
    """Returns GlobalItems for admin dropdown when creating a client Item."""
    qs = GlobalItem.objects.filter(status='active')
    if domain:
        qs = qs.filter(domain=domain)
    if search:
        qs = qs.filter(
            Q(name__icontains=search) |
            Q(global_item_id__icontains=search) |
            Q(gtin__icontains=search)
        )
    return qs.order_by('global_item_id')


def get_global_nodes_for_client(client, taxonomy_slug=None):
    """Returns global TaxonomyNodes for admin use."""
    qs = TaxonomyNode.objects.filter(client=None, is_active=True)
    if taxonomy_slug:
        qs = qs.filter(taxonomy__slug=taxonomy_slug)
    return qs.select_related('taxonomy').order_by('path')
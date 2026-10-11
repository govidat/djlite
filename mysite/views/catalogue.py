# mysite/views/catalogue.py
"""
Catalogue views — supports both Track A (raw HTML) and Track B (component tree).
HTMX-powered filtering and pagination.
"""

from django.shortcuts import render, get_object_or_404
from django.http import Http404

from utils.catalogue_queries import build_catalogue_payload
from utils.i18n import translated_fields
from mysite.models.catalogue import Item, ItemVariant, ItemMedia, ItemAttributeValue, GlobalItemMedia, ItemTaxonomyNode

import logging
from django.db.models import Q, Prefetch, Min, Max
from django.utils.translation import get_language
 
 
logger = logging.getLogger(__name__)


"""
Practical rule
Use queryset utilities for:
.only()
.select_related()
.prefetch_related()
translation field loading
Use model resolvers for:
inheritance
fallback
merging
derived values
display logic
Recommended next step

Add these model methods gradually:

resolved_medias()
resolved_primary_image()
resolved_taxonomy_chains()
resolved_price()
resolved_attr_values()

Correct relationship
prefetched_medias

is:

a queryset optimization mechanism
data loading
performance infrastructure
resolved_medias()

is:

business logic
merge/inheritance/fallback logic
uses already-loaded data
Think of it this way

Your view should NOT know HOW media is fetched.

Your view should only say:

all_medias = item.resolved_medias()

Then inside the model:

medias = getattr(self, 'prefetched_medias', None)

If prefetch exists:

use it
zero extra queries

If prefetch does NOT exist:

fallback gracefully to DB query
"""

def _parse_filters(request):
    """
    Extract and normalise all filter params from GET request.
    Returns a filters dict ready for get_item_queryset().
    """
    # Node (taxonomy) filters
    node_ids_raw = request.GET.getlist('node')
    node_ids = [int(n) for n in node_ids_raw if n.isdigit()]
 
    # Structured attribute value filters: ?attr_val_3=7&attr_val_3=8
    attr_values = {}
    for key in request.GET.keys():
        if key.startswith('attr_val_'):
            try:
                attr_type_id = int(key[9:])
                value_ids = [
                    int(v) for v in request.GET.getlist(key)
                    if v.isdigit()
                ]
                if value_ids:
                    attr_values[attr_type_id] = value_ids
            except (ValueError, TypeError):
                pass
 
    # Price range filters
    price_min = request.GET.get('price_min', '').strip()
    price_max = request.GET.get('price_max', '').strip()
    try:
        price_min = float(price_min) if price_min else None
    except ValueError:
        price_min = None
    try:
        price_max = float(price_max) if price_max else None
    except ValueError:
        price_max = None
 
    # In-stock filter
    in_stock = request.GET.get('in_stock', '') == '1'
 
    filters = {
        'node_ids':    node_ids,
        'search':      request.GET.get('q', '').strip(),
        #'brands':      request.GET.getlist('brand'),
        'attr_values': attr_values,
        'attributes':  {},          # JSONB overflow (reserved)
        'price_min':   price_min,
        'price_max':   price_max,
        'in_stock':    in_stock,
    }
 
    logger.debug(f"Catalogue filters: {filters}")
    return filters
 
"""
def _parse_filters(request):
    node_ids_raw = request.GET.getlist('node')
    node_ids = [int(n) for n in node_ids_raw if n.isdigit()]

    # ── Fix: use getlist for multi-value attribute filters ────────
    attr_values = {}
    for key in request.GET.keys():
        if key.startswith('attr_val_'):
            try:
                attr_type_id = int(key[9:])
                value_ids = [
                    int(v) for v in request.GET.getlist(key)
                    if v.isdigit()
                ]
                if value_ids:
                    attr_values[attr_type_id] = value_ids
            except (ValueError, TypeError):
                pass
          
    # ← ADD TEMPORARILY
    print(f"DEBUG filters: node_ids={node_ids}, attr_values={attr_values}")

    return {
        'node_ids':    node_ids,
        'search':      request.GET.get('q', ''),
        #'brands':      request.GET.getlist('brand'),
        'attr_values': attr_values,
        'attributes':  {},
    }
"""

# ── A. Full catalogue page ────────────────────────────────────────────
 
def catalogue_page(request, client_code, page_code='catalogue'):

    #Full page render for the catalogue.
    #Supports both Track A (PageContent HTML blob) and
    #Track B (component tree via fetch_clientstatic).
    #HTMX requests return partials only.

    client_obj = request.client
    if not client_obj:
        raise Http404("Client not found.")
 
    filters     = _parse_filters(request)
    page_number = int(request.GET.get('page', 1))
    per_page    = int(request.GET.get('per_page', 24))
 
    payload = build_catalogue_payload(
        client=client_obj,
        filters=filters,
        page_number=page_number,
        per_page=per_page,
    )
 
    # Check for PageContent Track A blob
    from mysite.models.page import PageContent
    raw_html = (
        PageContent.objects
        .filter(
            page__client=client_obj,
            page__page_code=page_code
        )
        .values_list('htmlblob', flat=True)
        .first()
    )
 
    context = {
        'catalogue': payload,
        'raw_html':  raw_html,
        'page_code':   page_code,
    }
 
    if request.headers.get('HX-Request'):
        return render(request, 'catalogue/partials/items_list.html', context)
 
    if raw_html:
        return render(request, 'catalogue/page_catalogue_html.html', context)
 
    return render(request, 'catalogue/page_catalogue.html', context)
 
 

"""
# ── A. Full catalogue page ────────────────────────────────────────────

def catalogue_page(request, client_code, page_code='catalogue'):
    
    #Full page render for the catalogue.
    #Supports both Track A (PageContent HTML blob) and
    #Track B (component tree via fetch_clientstatic).
    #HTMX requests return partials only.
    
    client_obj = request.client
    if not client_obj:
        raise Http404("Client not found.")

    filters     = _parse_filters(request)
    page_number = int(request.GET.get('page', 1))
    per_page    = int(request.GET.get('per_page', 24))

    payload = build_catalogue_payload(
        client=client_obj,
        filters=filters,
        page_number=page_number,
        per_page=per_page,
    )

    # Check for PageContent Track A blob
    from mysite.models.page import PageContent
    raw_html = (
        PageContent.objects
        .filter(
            page__client=client_obj,
            page__page_code=page_code
        )
        .values_list('htmlblob', flat=True)
        .first()
    )

    context = {
        'catalogue':  payload,
        'raw_html':   raw_html,
        'page_code':    page_code,
        # 'client', 'theme' come from context processor
    }

    # HTMX partial response — return only the items list
    if request.headers.get('HX-Request'):
        return render(request, 'catalogue/partials/items_list.html', context)

    # Full page
    if raw_html:
        # Track A — raw HTML wrapper with catalogue data injected
        return render(request, 'catalogue/page_catalogue_html.html', context)

    # Track B — component tree page
    return render(request, 'catalogue/page_catalogue.html', context)
"""

# ── B. HTMX filter endpoint ──────────────────────────────────────────

def catalogue_filter(request, client_code):
    
    #HTMX endpoint — returns items list partial after filter change.
    #Called by hx-get on filter checkboxes.
    
    client_obj = request.client
    if not client_obj:
        raise Http404("Client not found.")

    filters     = _parse_filters(request)
    page_number = int(request.GET.get('page', 1))
    per_page    = int(request.GET.get('per_page', 24))

    payload = build_catalogue_payload(
        client=client_obj,
        filters=filters,
        page_number=page_number,
        per_page=per_page,
    )

    return render(request, 'catalogue/partials/items_list.html', {
        'catalogue': payload,
    })


# ── C. Item detail page ───────────────────────────────────────────────

 
def item_detail(request, client_code, item_code):
    """
    Detail page for a single item.
    Resolves all display fields through the GlobalItem derivation chain.
    Phase 3: add variant selection + add-to-cart here.
    Item detail view.
 
    Design principle: the Item model carries the resolution logic.
    The view's job is:
      1. Fetch the item with the right prefetches
      2. Call model methods to resolve display values
      3. Pass resolved values to template
 
    No resolution logic lives in the view.

    """
    client_obj = request.client
    if not client_obj:
        raise Http404("Client not found.")
 
    active_lang   = get_language() or 'en'
    client_lang   = 'en'  # fallback — replace with client.language_list[0] if available
    
    if hasattr(client_obj, 'default_language') and client_obj.default_language:
        client_lang = client_obj.default_language

    #if hasattr(client_obj, 'language_list') and client_obj.language_list:
    #    client_lang = client_obj.language_list[0]

    # ── Single fetch with all prefetches ─────────────────────────────
    item = get_object_or_404(
        Item.objects.filter(
            Q(client=client_obj) | Q(client=None)
        ).select_related(
            'client',
            'global_item',
            'product_detail',
            'song_detail',
            'document_detail',
            'service_detail',
        ).prefetch_related(
            # All item media — used by resolved_medias()
            Prefetch(
                'medias',
                queryset=ItemMedia.objects.order_by('order'),
                to_attr='prefetched_medias'
            ),
            # Global media — used by resolved_medias() when inherit_global_media=True
            Prefetch(
                'global_item__medias',
                queryset=GlobalItemMedia.objects.order_by('order'),
                to_attr='prefetched_global_medias'
            ),
            # Variants
            Prefetch(
                'variants',
                queryset=ItemVariant.objects.filter(
                    is_active=True
                ).order_by('variant_code'),
                to_attr='prefetched_variants'
            ),
            # Item attribute values
            Prefetch(
                'attribute_values',
                queryset=ItemAttributeValue.objects.select_related(
                    'attribute_type', 'predefined_value'
                ).order_by('attribute_type__order'),
                to_attr='prefetched_attribute_values'
            ),
            # Global item attribute values
            Prefetch(
                'global_item__attribute_values',
                queryset=__import__(
                    'mysite.models.catalogue',
                    fromlist=['GlobalItemAttributeValue']
                ).GlobalItemAttributeValue.objects.select_related(
                    'attribute_type', 'predefined_value'
                ).order_by('attribute_type__order'),
                to_attr='prefetched_global_attr_values'
            ),
            # Taxonomy mappings with parent chain for breadcrumb
            Prefetch(
                'taxonomy_mappings',
                queryset=ItemTaxonomyNode.objects.select_related(
                    'node',
                    'node__taxonomy',
                    'node__parent',
                    'node__parent__parent',
                ).order_by('node__taxonomy__order', 'node__depth'),
                to_attr='prefetched_taxonomy_mappings'
            ),
        ),
        item_code=item_code
    )


    # ── All resolution delegated to model methods ─────────────────────
 
    # Text fields — 5-level i18n priority
    name             = _resolve_field(item, 'name', active_lang, client_lang)
    description      = _resolve_field(item, 'description', active_lang, client_lang)
    care_instructions = _resolve_field(item, 'care_instructions', active_lang, client_lang)
    # Media — model method handles inherit_global_media flag
    all_medias = item.resolved_medias()
 
    # Domain sub-model
    domain_obj = item.get_domain_object()
 
    # Commerce fields from domain sub-model
    price, compare_price, currency, sku, stock = _resolve_commerce(item, domain_obj)
 
    # Attribute values — prefetch data used, no extra queries
    attr_values = _resolve_attr_values(item)
 
    # Physical dimensions
    dimensions = _resolve_dimensions(item)
 
    # Taxonomy chains for classification display
    taxonomy_chains = _build_taxonomy_chains(
        getattr(item, 'prefetched_taxonomy_mappings', [])
    )
 
    # If item has no taxonomy mappings, fall back to GlobalItem's
    if not taxonomy_chains and item.global_item:
        global_mappings = list(
            item.global_item.taxonomy_mappings.select_related(
                'node', 'node__taxonomy',
                'node__parent', 'node__parent__parent',
            ).order_by('node__taxonomy__order', 'node__depth')
        )
        taxonomy_chains = _build_taxonomy_chains_global(global_mappings)
 
    # Split media by type for template tabs
    images = [m for m in all_medias if m.media_type == 'image']
    audios = [m for m in all_medias if m.media_type == 'audio']
    videos = [m for m in all_medias if m.media_type == 'video']
    pdfs   = [m for m in all_medias if m.media_type == 'pdf']
    texts  = [m for m in all_medias if m.media_type == 'text']
 
    # Primary image
    image_url = item.resolved_image_url()
    image_alt = (
        item.image_alt
        or (item.global_item.image_alt if item.global_item else '')
        or name
    )
 
    context = {
        'item':              item,
        'variants':          getattr(item, 'prefetched_variants', []),
        # Media
        'all_medias':        all_medias,
        'images':            images,
        'audios':            audios,
        'videos':            videos,
        'pdfs':              pdfs,
        'texts':             texts,
        'image_url':         image_url,
        'image_alt':         image_alt,
        # Resolved text
        'name':              name,
        'description':       description,
        'care_instructions': care_instructions,
        # Commerce
        'price':             price,
        'compare_price':     compare_price,
        'currency':          currency,
        'sku':               sku,
        'stock':             stock,
        # Identification
        'gtin':              item.gtin or (item.global_item.gtin if item.global_item else ''),
        'gpc_brick_code':    item.gpc_brick_code,
        'barcode':           item.resolved_barcode(),
        'country_of_origin': item.resolved_country_of_origin(),
        # Attributes
        'attr_values':       attr_values,
        'attributes':        item.resolved_attributes(),
        'dimensions':        dimensions,
        # Taxonomy
        'taxonomy_chains':   taxonomy_chains,
        # Sub-model
        'domain_obj':        domain_obj,
    }
 
    logger.debug(
        f"item_detail: item={item_code}, "
        f"name={context['name']}, "
        f"price={price}, sku={sku}, "
        f"images={len(images)}, audios={len(audios)}, videos={len(videos)}, "
        f"attr_values={list(attr_values.keys())}, "
        f"taxonomy_chains={[t['taxonomy_name'] for t in taxonomy_chains]}"
    )

    return render(request, 'catalogue/item_detail_wrapper.html', context)
 


# ── Taxonomy chain builders ───────────────────────────────────────────
 
def _build_taxonomy_chains(mappings):
    """
    Build a list of {taxonomy_name, nodes, chain} dicts from
    prefetched ItemTaxonomyNode mappings.
 
    For each taxonomy, finds the deepest node and walks up
    via parent FK to build the full ancestor chain.
 
    Returns: [
      {'taxonomy_name': 'GS1 GPC',
       'nodes': [node_obj, ...],          # deepest first
       'chain': 'Seg > Fam > Class > Brick'},
      ...
    ]
    """
    if not mappings:
        return []
 
    # Group by taxonomy
    by_taxonomy = {}
    for mapping in mappings:
        node     = mapping.node
        tax_name = node.taxonomy.name
        tax_order = node.taxonomy.order
        key = (tax_order, tax_name)
        by_taxonomy.setdefault(key, []).append(node)
 
    result = []
    for (tax_order, tax_name), nodes in sorted(by_taxonomy.items()):
        # Find the deepest node (highest depth = most specific)
        deepest = max(nodes, key=lambda n: n.depth)
 
        # Walk up the parent chain
        chain_nodes = []
        current = deepest
        while current:
            chain_nodes.insert(0, current)   # prepend — root first
            current = getattr(current, 'parent', None)
 
        # Build display string
        chain_str = ' › '.join(n.name for n in chain_nodes)
 
        result.append({
            'taxonomy_name': tax_name,
            'nodes':         chain_nodes,
            'chain':         chain_str,
        })
 
    return result
 
 
def _build_taxonomy_chains_global(global_mappings):
    """
    Same as _build_taxonomy_chains but for GlobalItemTaxonomyNode mappings.
    Used as fallback when Item has no ItemTaxonomyNode records.
    """
    if not global_mappings:
        return []
 
    by_taxonomy = {}
    for mapping in global_mappings:
        node     = mapping.node
        tax_name = node.taxonomy.name
        tax_order = node.taxonomy.order
        key = (tax_order, tax_name)
        by_taxonomy.setdefault(key, []).append(node)
 
    result = []
    for (tax_order, tax_name), nodes in sorted(by_taxonomy.items()):
        deepest   = max(nodes, key=lambda n: n.depth)
        chain_nodes = []
        current = deepest
        while current:
            chain_nodes.insert(0, current)
            current = getattr(current, 'parent', None)
        chain_str = ' › '.join(n.name for n in chain_nodes)
        result.append({
            'taxonomy_name': tax_name,
            'nodes':         chain_nodes,
            'chain':         chain_str,
        })
 
    return result
 
# ── Private helpers ───────────────────────────────────────────────────
# These are thin — they call model methods or do simple dict-building.
# No resolution logic here; that belongs in the model.
 
def _resolve_field(item, field, active_lang, client_lang):
    """
    5-level priority:
    1. Item field in active language
    2. Item field in client base language
    3. GlobalItem field in active language
    4. GlobalItem field in client base language
    5. Empty string
    """
    # 1
    val = getattr(item, f'{field}_{active_lang}', None)
    if val:
        return val
    # 2
    if active_lang != client_lang:
        val = getattr(item, f'{field}_{client_lang}', None)
        if val:
            return val
    # 3
    if item.global_item:
        val = getattr(item.global_item, f'{field}_{active_lang}', None)
        if val:
            return val
        # 4
        if active_lang != client_lang:
            val = getattr(item.global_item, f'{field}_{client_lang}', None)
            if val:
                return val
    # 5
    return ''
 
 
def _resolve_commerce(item, domain_obj):
    """Returns (price, compare_price, currency, sku, stock)."""
    price         = None
    compare_price = None
    currency      = 'INR'
    sku           = ''
    stock         = None
 
    if domain_obj:
        if hasattr(domain_obj, 'price') and domain_obj.price is not None:
            price    = domain_obj.price
            currency = getattr(domain_obj, 'currency', 'INR')
        if hasattr(domain_obj, 'compare_price'):
            compare_price = domain_obj.compare_price
        if hasattr(domain_obj, 'sku'):
            sku = domain_obj.sku or ''
        if hasattr(domain_obj, 'stock_quantity'):
            stock = domain_obj.stock_quantity
 
    return price, compare_price, currency, sku, stock
 
 
def _resolve_attr_values(item):
    """
    Build attr_values dict using prefetched data only — no extra queries.
    GlobalItem values as base, Item values override.
    """
    attr_values = {}
 
    # Global base (prefetched)
    if item.global_item:
        for av in getattr(item.global_item, 'prefetched_global_attr_values', []):
            attr_values[av.attribute_type.name] = av.resolved_value()
 
    # Item overrides (prefetched)
    for av in getattr(item, 'prefetched_attribute_values', []):
        attr_values[av.attribute_type.name] = av.resolved_value()
 
    return attr_values
 
 
def _resolve_dimensions(item):
    """Build physical dimensions dict from resolved Item fields."""
    dims = {}
    w = item.resolved_weight_g()
    if w:
        dims['Weight'] = f"{w} g"
    l = item.resolved_length_mm()
    wd = item.resolved_width_mm()
    h = item.resolved_height_mm()
    if any([l, wd, h]):
        dims['Dimensions (L×W×H)'] = f"{l} × {wd} × {h} mm"
    return dims



# mysite/views/catalogue.py
"""
Catalogue views — supports both Track A (raw HTML) and Track B (component tree).
HTMX-powered filtering and pagination.
"""

from django.shortcuts import render, get_object_or_404
from django.http import Http404

from utils.catalogue_queries import build_catalogue_payload
from mysite.models.catalogue import Item, ItemVariant, ItemMedia
#from utils.common_functions import fetch_clientstatic
from django.db.models import Q, Prefetch
#from mysite.models.catalogue import ItemVariant

def _parse_filters(request):
    node_ids_raw = request.GET.getlist('node')
    node_ids = [int(n) for n in node_ids_raw if n.isdigit()]

    attr_values = {}
    for key, value in request.GET.items():
        if key.startswith('attr_val_') and value:
            try:
                attr_type_id = int(key[9:])
                attr_values.setdefault(attr_type_id, []).append(int(value))
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
def _parse_filters(request):
    
    #Extract and normalise filter params from GET request.
    #Returns a filters dict ready for get_item_queryset().
    
    node_ids_raw = request.GET.getlist('node')   # ?node=1&node=2&node=5
    node_ids     = []
    for n in node_ids_raw:
        try:
            node_ids.append(int(n))
        except (ValueError, TypeError):
            pass

    # JSONB attribute filters: ?attr_color=red&attr_size=xl
    attributes = {}
    for key, value in request.GET.items():
        if key.startswith('attr_') and value:
            attr_key = key[5:]   # strip 'attr_' prefix
            attributes[attr_key] = value

    print(f"DEBUG GET params: {dict(request.GET)}")
    print(f"DEBUG attr_values parsed: {attributes}")

    return {
        'node_ids':      node_ids,
        'taxonomy_slug': request.GET.get('taxonomy', ''),
        'search':        request.GET.get('q', ''),
        'attributes':    attributes,
    }
"""

# ── A. Full catalogue page ────────────────────────────────────────────

def catalogue_page(request, client_id, page_id='catalogue'):
    """
    Full page render for the catalogue.
    Supports both Track A (PageContent HTML blob) and
    Track B (component tree via fetch_clientstatic).
    HTMX requests return partials only.
    """
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
            page__page_id=page_id
        )
        .values_list('htmlblob', flat=True)
        .first()
    )
    """
    from mysite.models.page import Page
    from mysite.models.page import PageContent
    from django.utils.translation import get_language

    active_lang = get_language() or 'en'
    raw_html    = None

    try:
        page_obj = Page.objects.get(client=client_obj, page_id=page_id)
        contents = {
            c['language_code']: c['html']
            for c in PageContent.objects.filter(page=page_obj).values(
                'language_code', 'html'
            )
        }
        raw_html = (
            contents.get(active_lang)
            or contents.get('en')
            or (list(contents.values())[0] if contents else None)
        )
    except Page.DoesNotExist:
        pass
    """
    context = {
        'catalogue':  payload,
        'raw_html':   raw_html,
        'page_id':    page_id,
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


# ── B. HTMX filter endpoint ──────────────────────────────────────────

def catalogue_filter(request, client_id):
    """
    HTMX endpoint — returns items list partial after filter change.
    Called by hx-get on filter checkboxes.
    """
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

def item_detail(request, client_id, item_id):
    """
    Detail page for a single item.
    Phase 3: add variant selection + add-to-cart here.
    """
    client_obj = request.client
    if not client_obj:
        raise Http404("Client not found.")

    item = get_object_or_404(
        Item.objects.filter(
            Q(client=client_obj)
        ).prefetch_related(
            Prefetch(
                'medias',
                queryset=ItemMedia.objects.order_by('order'),
                to_attr='prefetched_medias'
            ),            
            Prefetch(
                'variants',
                queryset=ItemVariant.objects.filter(
                    is_active=True
                ).order_by('variant_id'),
                to_attr='prefetched_variants'
            ),
            'taxonomy_mappings__node__taxonomy',
        ).select_related(
            'client',
            'global_item',
        ),
        item_id=item_id
    )

    return render(request, 'catalogue/item_detail.html', {
        'item': item,
        'variants': getattr(item, 'prefetched_variants', []),
    })

    """
    item = get_object_or_404(
        Item.objects.filter(
            Q(client=client_obj) | Q(client=None)
        ).prefetch_related(
            #Prefetch(
            #    'images',
            #    queryset=ItemImage.objects.order_by('order'),
            #    to_attr='prefetched_images'
            #),
            Prefetch(
                'variants',
                queryset=ItemVariant.objects.filter(is_active=True).order_by('variant_id'),
                to_attr='prefetched_variants'
            ),
            'taxonomy_mappings__node__taxonomy',
        ).select_related('client'),
        item_id=item_id
    )

    return render(request, 'catalogue/item_detail.html', {
        'item':     item,
        'images':   getattr(item, 'prefetched_images', []),
        'variants': getattr(item, 'prefetched_variants', []),
        # 'client', 'theme' from context processor
    })
    """
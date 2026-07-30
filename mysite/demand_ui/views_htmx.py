from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage
from mysite.models.demand.forecast import ForecastOverride, ForecastVersion, OverrideSplitWeight, ForecastLine
from mysite.api.demand.views import _build_affected_lines_qs   # reuse the helper

#from mysite.models import Item
from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
#from mysite.models import PlanningLocation, PlanningCustomer
#from mysite.models import PlanningLocation, PlanningCustomer, Item
import logging
logger = logging.getLogger(__name__)
from django.db import models

@login_required
def override_key_field(request, pk, client_id=None):

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    level = request.GET.get('override_level', 'sku')
    if level not in ('sku', 'location', 'customer', 'total'):
        level = 'sku'

    context = {'level': level, 'version': version}

    try:
        if level == 'sku':
            context['items'] = (
                ForecastLine.objects
                .filter(version=version)
                .select_related('item')
                .values_list('item__item_id', 'item__name')
                .distinct()
                .order_by('item__item_id')
            )
        elif level == 'location':
            context['locations'] = (
                PlanningLocation.objects
                .filter(client=request.client)
                .order_by('code')
            )
        elif level == 'customer':
            context['customers'] = (
                PlanningCustomer.objects
                .filter(client=request.client)
                .order_by('code')
            )
    except Exception as exc:
        logger.exception(f'override_key_field: failed to load choices for level={level}: {exc}')
        context['load_error'] = True

    return render(request, f'demand/partials/override_key_{level}.html', context)
"""
@login_required
def override_key_field(request, pk, client_id=None):

    level = request.GET.get('override_level', 'sku')
    if level not in ('sku', 'location', 'customer', 'total'):
        level = 'sku'

    context = {'level': level}

    if level == 'sku':
        context['items'] = Item.objects.filter(client=request.client).order_by('item_id')[:500]
    elif level == 'location':
        context['locations'] = PlanningLocation.objects.filter(client=request.client).order_by('code')
    elif level == 'customer':
        context['customers'] = PlanningCustomer.objects.filter(client=request.client).order_by('code')

    return render(request, f'demand/partials/override_key_{level}.html', context)
"""

"""
@login_required
def override_key_field(request, pk, client_id=None):
    
    #HTMX partial: renders the appropriate override_key input widget
    #based on the selected override_level.
    #Called when the level <select> changes in the override form.
        
    level = request.GET.get('override_level', 'sku')
    if level not in ('sku', 'location', 'customer', 'total'):
        level = 'sku'
    return render(request, f'demand/partials/override_key_{level}.html', {
        'level': level,
    })
"""
"""
@login_required
def override_key_field(request, client_id=None):

    level = request.GET.get('override_level', 'sku')
    return render(request, f'demand/partials/override_key_{level}.html', {
        'level': level,
    })
"""

@login_required
def override_value_inputs(request, pk, client_id=None):
    """
    HTMX partial: renders the active override value input (qty / pct / value)
    based on the selected mode tab.
    """    
    mode = request.GET.get('mode', 'qty')
    if mode not in ('qty', 'pct', 'value'):
        mode = 'qty'
    return render(request, f'demand/partials/override_value_{mode}.html', {
        'mode': mode,
    })
 
"""
@login_required
def override_value_inputs(request, client_id=None):

    mode = request.GET.get('mode', 'qty')
    return render(request, f'demand/partials/override_value_{mode}.html', {
        'mode': mode,
    })
"""
#from django.core.paginator import Paginator, EmptyPage
#from mysite.models.demand.forecast import ForecastOverride, ForecastVersion
#from mysite.api.demand.views import _build_affected_lines_qs   # reuse the helper

 
@login_required
def override_propagation(request, override_id, client_id=None):
    """
    HTMX partial: renders the propagation panel for one override.
    Loaded when the planner clicks 🔍 on an override badge.
    """
    override = get_object_or_404(
        ForecastOverride,
        pk=override_id,
        version__client=request.client,
    )
    version = override.version

    qs      = _build_affected_lines_qs(override, version)
    page_size = 50
    page_num  = int(request.GET.get('page', 1))
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    if version.client.is_distribution_channel_enabled():
        show_channel = qs.values('distribution_channel').distinct().count() > 1
    else:
        show_channel = False

    return render(request, 'demand/partials/override_propagation.html', {
        'override': override,
        'version':  version,
        'page':     page,
        'count':    paginator.count,
        'show_channel': show_channel,
    })

@login_required
def encode_override_key(request, pk, client_id=None):
    """
    Receives form fields named override_key_{field} and returns a hidden input
    containing the JSON-encoded override_key.  Called via HTMX on blur/change.
    """
    import json
    from django.http import HttpResponse

    key = {}
    for k, v in request.POST.items():
        if k.startswith('override_key_') and v:
            field = k[len('override_key_'):]
            key[field] = v

    # Also pick up the direct field names sent by the select dropdowns
    # (item_id, location_code, customer_code) since they don't use the
    # override_key_ prefix
    for direct_field in ('item_id', 'location_code', 'customer_code'):
        val = request.GET.get(direct_field) or request.POST.get(direct_field)
        if val:
            key[direct_field] = val

    encoded = json.dumps(key)
    return HttpResponse(
        f'<input type="hidden" id="override-key-hidden" '
        f'name="override_key" value=\'{encoded}\'>',
        content_type='text/html',
    )

#from django.contrib.auth.decorators import login_required
#from django.shortcuts import get_object_or_404, render
#from mysite.models.demand.forecast import ForecastVersion


@login_required
def approval_panel(request, pk, client_id=None):
    """
    HTMX partial: renders the approval panel for a forecast version.
    Called after a successful approve/reject/lock action to refresh the panel.
    Also loaded on page-load via {% include %} in the version detail template.
    """
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_panel.html', {
        'version': version,
    })


@login_required
def approval_reject_form(request, pk, client_id=None):
    """HTMX partial: reject-with-note modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_rejected_note.html', {
        'version': version,
    })


@login_required
def approval_copy_form(request, pk, client_id=None):
    """HTMX partial: copy-to-new-draft modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_copy_form.html', {
        'version': version,
    })

@login_required
def override_split_weights(request, pk, override_id, client_id=None):
    """
    GET  — render the split weight editor partial
    PUT  — handled by the API (api/demand/urls.py already has this route)
    """
    
    override = get_object_or_404(
        ForecastOverride,
        pk=override_id, version_id=pk, version__client=request.client,
    )
    weights = OverrideSplitWeight.objects.filter(override=override).order_by('child_key')
    return render(request, 'demand/partials/split_weight_editor.html', {
        'override': override,
        'weights': weights,
    })

@login_required
def item_search(request, pk=None, client_id=None):
    from mysite.models.catalogue import Item
    from django.db import models as db_models
    from django.http import JsonResponse

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    items = (
        Item.objects
        .filter(client=request.client)
        .filter(
            db_models.Q(item_id__icontains=q) | db_models.Q(name__icontains=q)
        )
        .order_by('item_id')
        .values('item_id', 'name')[:20]
    )
    return JsonResponse({'results': list(items)})
"""
@login_required
def item_search(request, pk=None, client_id=None):
    from mysite.models.catalogue import Item
    from django.http import JsonResponse

    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})

    items = (
        Item.objects
        .filter(client=request.client)
        .filter(
            models.Q(item_id__icontains=q) | models.Q(name__icontains=q)
        )
        .order_by('item_id')
        .values('item_id', 'name')[:20]
    )
    return JsonResponse({'results': list(items)})
"""
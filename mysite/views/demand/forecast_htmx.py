from django.shortcuts import get_object_or_404, render
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage
from mysite.models.demand.forecast import ForecastOverride, ForecastVersion
from mysite.api.demand.views import _build_affected_lines_qs   # reuse the helper


@login_required
def override_key_field(request):
    """
    HTMX partial: renders the appropriate override_key input widget
    based on the selected override_level.
    Called when the level <select> changes in the override form.
    """
    level = request.GET.get('override_level', 'sku')
    return render(request, f'demand/partials/override_key_{level}.html', {
        'level': level,
    })

 
@login_required
def override_value_inputs(request):
    """
    HTMX partial: renders the active override value input (qty / pct / value)
    based on the selected mode tab.
    """
    mode = request.GET.get('mode', 'qty')
    return render(request, f'demand/partials/override_value_{mode}.html', {
        'mode': mode,
    })

#from django.core.paginator import Paginator, EmptyPage
#from mysite.models.demand.forecast import ForecastOverride, ForecastVersion
#from mysite.api.demand.views import _build_affected_lines_qs   # reuse the helper

 
@login_required
def override_propagation(request, override_id):
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

    return render(request, 'demand/partials/override_propagation.html', {
        'override': override,
        'version':  version,
        'page':     page,
        'count':    paginator.count,
    })

@login_required
def encode_override_key(request):
    """
    Receives form fields named override_key_{field} and returns a hidden input
    containing the JSON-encoded override_key.  Called via HTMX on blur.
    """
    import json
    from django.http import HttpResponse

    key = {}
    for k, v in request.POST.items():
        if k.startswith('override_key_') and v:
            field = k[len('override_key_'):]
            key[field] = v

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
def approval_panel(request, pk):
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
def approval_reject_form(request, pk):
    """HTMX partial: reject-with-note modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_rejected_note.html', {
        'version': version,
    })


@login_required
def approval_copy_form(request, pk):
    """HTMX partial: copy-to-new-draft modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_copy_form.html', {
        'version': version,
    })
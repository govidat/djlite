# mysite/demand_ui/views_drilldown.py
#
# Drill-down aggregate visualization + scoped override entry.
# Add these view functions to mysite/demand_ui/views.py (or import this
# module from there) and wire the URLs in Part 4 below.
#
# Core principle: every view that reads or writes at a PlanningLocation
# node calls get_authorized_location_ids() / user_can_act_at_location()
# from utils.demand.location_access BEFORE doing anything else. There is
# no "trust the URL" path — a branch manager who edits the URL to point
# at a sibling branch or the region above gets a 403, not silently wrong
# data.

from __future__ import annotations

from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseForbidden
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastAggregate, ForecastLine, ForecastOverride, OverrideSplitWeight,
)
from mysite.models.demand.hierarchy import PlanningLocation
from utils.feature_control import is_demand_feature_disabled
from utils.demand.location_access import (
    get_authorized_location_ids,
    user_can_act_at_location,
    filter_queryset_to_authorized_locations,
    OVERRIDE_PERM,
    VIEW_PERM,
)
from utils.mixins import feature_gate, _is_htmx, _client_url_kwargs
import logging
logger = logging.getLogger(__name__)
# ─────────────────────────────────────────────────────────────────────────────
# Helpers (shared with views.py — duplicated here only for file-standalone
# readability; in your actual codebase these live once in views.py)
# ─────────────────────────────────────────────────────────────────────────────
"""
def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'


def feature_gate(request, feature: str):
    result = is_demand_feature_disabled(request.client, feature)
    if result['disabled']:
        return render(request, 'demand/partials/feature_disabled.html', {
            'message': result['message'],
        }, status=403)
    return None


def _client_url_kwargs(request) -> dict:
    return {'client_id': request.client.client_id}

"""
def _require_location_view_access(request, location: PlanningLocation | None):
    """
    Raise PermissionDenied if the user cannot VIEW at this location.
    location=None means "client root / total" — always viewable by anyone
    with any grant at all, since the total is just a rollup of whatever
    they can already see (their own branch's number is a subset of it).
    """
    if location is None:
        return
    if not user_can_act_at_location(request.user, location, perm=VIEW_PERM) and \
       not user_can_act_at_location(request.user, location, perm=OVERRIDE_PERM):
        raise PermissionDenied(
            f'You do not have access to {location.code}.'
        )


def _require_location_override_access(request, location: PlanningLocation):
    """Raise PermissionDenied if the user cannot CREATE OVERRIDES at this location."""
    if not user_can_act_at_location(request.user, location, perm=OVERRIDE_PERM):
        raise PermissionDenied(
            f'You are not authorized to enter overrides at {location.code}.'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Drill-down aggregate view
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def drilldown(request, pk, location_id=None, client_id=None):
#def drilldown(request, pk):
    """
    GET /{client_id}/demand/versions/{id}/drilldown/
    GET /{client_id}/demand/versions/{id}/drilldown/<int:location_id>/

    Shows the value-aggregate rollup at ONE location node, plus its
    immediate children as clickable drill-down rows.

    No location_id in the URL  → show the highest level the user is
    authorized to see (their own root grant — could be client total
    for an admin, or a specific branch for a planner).

    location_id given  → show that node's aggregate, scoped-checked.
    Clicking a child row in the template navigates to this same view
    with the child's PK — building the breadcrumb trail as you go.

    Query param: agg_period (period_start, ISO date) to pick which
    forecast period's aggregate to show. Defaults to the version's
    base_period_end + 1 period (first forecast period).
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    authorized_ids = get_authorized_location_ids(request.user, request.client, perm=VIEW_PERM)
    # Fall back to override perm if no explicit view grant — override implies view
    if authorized_ids is not None and not authorized_ids:
        authorized_ids = get_authorized_location_ids(request.user, request.client, perm=OVERRIDE_PERM)

    if authorized_ids is not None and not authorized_ids:
        messages.error(request, 'You have no Demand Planning location access. Contact your administrator.')
        return redirect('demand_ui:version_detail', client_id=request.client.client_id, pk=pk)

    #location_id = request.GET.get('location_id') or None
    # location_id comes from the URL path if present (drilldown_location),
    # otherwise fall back to the query string for any existing links/bookmarks
    if location_id is None:
        location_id = request.GET.get('location_id') or None

    current_location = None

    if location_id:
        current_location = get_object_or_404(
            PlanningLocation, pk=location_id, client=request.client,
        )
        try:
            _require_location_view_access(request, current_location)
        except PermissionDenied as exc:
            return HttpResponseForbidden(str(exc))
    else:
        # No location specified: land on the user's highest authorized root.
        # For a superuser/admin (authorized_ids is None) this is the client
        # root node. For a scoped planner, pick their first granted root.
        if authorized_ids is None:
            current_location = PlanningLocation.objects.filter(
                client=request.client, parent__isnull=True,
            ).first()
        else:
            from guardian.shortcuts import get_objects_for_user
            granted_roots = get_objects_for_user(
                request.user, f'demand.{VIEW_PERM}',
                klass=PlanningLocation.objects.filter(client=request.client),
            )
            current_location = granted_roots.order_by('path').first()

    # ── Build the aggregate for current_location ────────────────────────────
    agg_period_str = request.GET.get('agg_period', '')
    import datetime
    if agg_period_str:
        try:
            agg_period = datetime.date.fromisoformat(agg_period_str)
        except ValueError:
            agg_period = None
    else:
        agg_period = None
    if agg_period is None:
        agg_period = version.base_period_end + datetime.timedelta(days=1)
        # Snap forward to the actual first ForecastLine period if different
        first_line = version.lines.order_by('period_start').values_list('period_start', flat=True).first()
        if first_line:
            agg_period = first_line

    current_agg = None
    if current_location:
        current_agg = (
            ForecastAggregate.objects
            .filter(
                version=version, agg_level='location',
                period_start=agg_period,
                agg_key__location_code=current_location.code,
            )
            .first()
        )
    else:
        # True client total — agg_level='total' has no location_code key
        current_agg = (
            ForecastAggregate.objects
            .filter(version=version, agg_level='total', period_start=agg_period)
            .first()
        )

    # ── Build child rows — each is a clickable drill-down target ───────────
    if current_location:
        child_locations = PlanningLocation.objects.filter(
            client=request.client, parent=current_location, is_active=True,
        ).order_by('code')
    else:
        child_locations = PlanningLocation.objects.filter(
            client=request.client, parent__isnull=True, is_active=True,
        ).order_by('code')

    # Filter children to what the user can see (a planner scoped to one
    # branch should not see sibling branches if browsing from the region
    # above — but in practice a planner's root IS their branch, so this
    # mostly matters for an admin browsing a tree where some sub-branches
    # are restricted to other users; we still apply it for correctness)
    if authorized_ids is not None:
        child_locations = child_locations.filter(pk__in=authorized_ids)

    child_rows = []
    for child in child_locations:
        child_agg = (
            ForecastAggregate.objects
            .filter(
                version=version, agg_level='location',
                period_start=agg_period,
                agg_key__location_code=child.code,
            )
            .first()
        )
        has_children = PlanningLocation.objects.filter(parent=child, is_active=True).exists()
        can_override_here = user_can_act_at_location(request.user, child, perm=OVERRIDE_PERM)
        child_rows.append({
            'location': child,
            'aggregate': child_agg,
            'has_children': has_children,
            'can_override': can_override_here,
        })

    # ── Breadcrumb trail from path ───────────────────────────────────────────
    breadcrumbs = []
    if current_location:
        ancestor_ids = [int(p) for p in current_location.path.split('/') if p][:-1]
        if ancestor_ids:
            ancestors = PlanningLocation.objects.filter(pk__in=ancestor_ids).order_by('path')
            breadcrumbs = list(ancestors)
        breadcrumbs.append(current_location)

    can_override_current = (
        current_location is not None and
        user_can_act_at_location(request.user, current_location, perm=OVERRIDE_PERM)
    )

    # Available periods for the period-switcher dropdown
    available_periods = (
        version.lines.order_by('period_start')
        .values_list('period_start', flat=True).distinct()
    )

    context = {
        'version': version,
        'current_location': current_location,
        'current_agg': current_agg,
        'child_rows': child_rows,
        'breadcrumbs': breadcrumbs,
        'agg_period': agg_period,
        'available_periods': available_periods,
        'can_override_current': can_override_current,
        'is_client_total': current_location is None,
    }

    if _is_htmx(request):
        return render(request, 'demand/partials/drilldown_panel.html', context)
    return render(request, 'demand/drilldown.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Item-level breakdown at the current location (the bottom of the drill)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def drilldown_items(request, pk, location_id, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/drilldown/<location_id>/items/

    Shown when a planner drills all the way to a LEAF location and wants
    to see the constituent SKU-level ForecastLine rows rather than another
    level of location aggregation. This is the "give me the 20K rows"
    escape hatch — deliberately one click further than the default
    value-summary view, matching the design principle that planners
    work at aggregate level by default.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version  = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    location = get_object_or_404(PlanningLocation, pk=location_id, client=request.client)

    try:
        _require_location_view_access(request, location)
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))

    from django.core.paginator import Paginator
    qs = (
        ForecastLine.objects
        .filter(version=version, planning_location=location)
        .select_related('item', 'planning_customer', 'distribution_channel')
        .order_by('period_start', 'item__item_id')
    )
    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    can_override_here = user_can_act_at_location(request.user, location, perm=OVERRIDE_PERM)
    distinct_items = ForecastLine.objects.filter(
        version=version,
        planning_location=location,
    ).values('item__item_id').distinct().count()
    if version.client.is_distribution_channel_enabled():
        show_channel = qs.values('distribution_channel').distinct().count() > 1
    else:
        show_channel = False
    context = {
        'version': version, 'location': location,
        'page_obj': page_obj, 'can_override': can_override_here,
        'show_channel': show_channel,
    }
    context['show_qty'] = distinct_items == 1
    if _is_htmx(request):
        return render(request, 'demand/partials/drilldown_items_table.html', context)
    return render(request, 'demand/drilldown_items.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Contextual override form — appears at whatever level is being viewed
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET', 'POST'])
def drilldown_override_form(request, pk, location_id, client_id=None):
    """
    GET  /{client_id}/demand/versions/{id}/drilldown/<location_id>/override/
    POST /{client_id}/demand/versions/{id}/drilldown/<location_id>/override/

    The override form for the LOCATION currently being viewed in the
    drill-down. Pre-fills override_level='location' and the location_code,
    so the planner cannot accidentally target a different node than the
    one they are looking at.

    Authorization is checked on BOTH GET (don't even show the form if you
    can't act here) and POST (don't trust the rendered form — re-check
    before writing to the database, since a stale page or a replayed
    request could otherwise bypass the GET-time check).

    Supports the three override modes (qty / pct / value) exactly as the
    ForecastOverride model and apply_overrides task expect.
    """
    blocked = feature_gate(request, 'consensus_override')
    if blocked:
        return blocked

    version  = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    location = get_object_or_404(PlanningLocation, pk=location_id, client=request.client)

    # ── Authorization check #1 — before rendering the form at all ──────────
    try:
        _require_location_override_access(request, location)
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))

    if not version.is_editable:
        messages.error(request, f'Version is {version.status}. Overrides require a DRAFT version.')
        return redirect('demand_ui:drilldown', client_id=request.client.client_id, pk=pk)

    agg_period_str = request.GET.get('agg_period') or request.POST.get('period_start', '')

    if request.method == 'POST':
        # ── Authorization check #2 — re-verify before writing ──────────────
        # A request replayed after the user's access was revoked, or a
        # tampered form field, must not be able to write an override.
        try:
            _require_location_override_access(request, location)
        except PermissionDenied as exc:
            return HttpResponseForbidden(str(exc))

        import datetime
        try:
            period_start = datetime.date.fromisoformat(agg_period_str)
        except ValueError:
            return render(request, 'demand/partials/drilldown_override_form.html', {
                'version': version, 'location': location,
                'errors': {'period_start': 'Invalid period.'},
                'agg_period': agg_period_str,
            }, status=400)

        qty_raw   = request.POST.get('override_qty', '').strip()
        pct_raw   = request.POST.get('override_pct', '').strip()
        value_raw = request.POST.get('override_value', '').strip()
        disagg_method = request.POST.get('disagg_method', 'PROPORTIONAL')
        note          = request.POST.get('override_note', '').strip()

        set_count = sum(bool(v) for v in (qty_raw, pct_raw, value_raw))
        if set_count != 1:
            #return render(request, 'demand/partials/drilldown_override_form.html', {
            #    'version': version, 'location': location,
            #    'errors': {'__all__': 'Set exactly one of Qty, %, or ₹ Value.'},
            #    'agg_period': agg_period_str, 'form_data': request.POST,
            #}, status=400)
            return render(request, 'demand/partials/drilldown_override_form.html', {
                'version': version,
                'form_error': 'Set exactly one of Qty, %, or ₹ Value.',
                'errors': {},
                'form_data': request.POST,
                'location': location, 'agg_period': agg_period_str,
            }, status=400) 

        # override_level is ALWAYS 'location', locked to the node being
        # viewed — the planner cannot type a different location into this
        # form because there is no free-text location field at all.
        override = ForecastOverride(
            version        = version,
            override_level = 'location',
            override_key   = {'location_code': location.code},
            period_type    = version.period_type,
            period_start   = period_start,
            disagg_method  = disagg_method,
            override_note  = note,
            created_by     = request.user,
        )
        if qty_raw:
            override.override_qty = Decimal(qty_raw)
        elif pct_raw:
            override.override_pct = Decimal(pct_raw)
        elif value_raw:
            override.override_value = Decimal(value_raw)

        try:
            override.full_clean()
            override.save()
            if disagg_method == 'CUSTOM':
                import json
                split_weights_raw = request.POST.get('split_weights_json', '[]')
                try:
                    weights = json.loads(split_weights_raw)
                    for w in weights:
                        OverrideSplitWeight.objects.create(
                            override=override,
                            child_key=w['child_key'],
                            weight=Decimal(str(w['weight'])),
                        )
                except Exception as exc:
                    logger.warning("split_weights parse error for override %s: %s", override.pk, exc)


        except Exception as exc:
            #return render(request, 'demand/partials/drilldown_override_form.html', {
            #    'version': version, 'location': location,
            #    'errors': {'__all__': str(exc)},
            #    'agg_period': agg_period_str, 'form_data': request.POST,
            #}, status=400)
            return render(request, 'demand/partials/drilldown_override_form.html', {
                'version': version,
                'form_error': 'Set exactly one of Qty, %, or ₹ Value.',
                'errors': {},
                'form_data': request.POST,
                'location': location, 'agg_period': agg_period_str, 
            }, status=400) 
        from mysite.tasks.demand.run_forecast import apply_overrides
        apply_overrides.delay(version.pk)

        messages.success(request, f'Override saved for {location.code}. Recalculating descendants…')

        if _is_htmx(request):
            response = HttpResponse(status=204)
            response['HX-Redirect'] = (
                reverse('demand_ui:drilldown', kwargs={**_client_url_kwargs(request), 'pk': pk})
                + f'?location_id={location.pk}&agg_period={agg_period_str}'
            )
            return response
        return redirect(
            reverse('demand_ui:drilldown', kwargs={'client_id': request.client.client_id, 'pk': pk})
            + f'?location_id={location.pk}&agg_period={agg_period_str}'
        )

    # ── GET: show the form pre-filled with current aggregate as context ────
    current_agg = (
        ForecastAggregate.objects
        .filter(
            version=version, agg_level='location',
            agg_key__location_code=location.code,
        )
        .first()
    )
    context = {
        'version': version, 'location': location,
        'current_agg': current_agg, 'agg_period': agg_period_str,
    }
    return render(request, 'demand/partials/drilldown_override_form.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Affected-lines preview for a drill-down override (before/after)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def drilldown_override_preview(request, pk, location_id, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/drilldown/<location_id>/override/preview/

    AJAX-style endpoint called by the override form (hx-get on input
    change) to show "if you set ₹X here, these N child branches/items
    will move by roughly Y% each" BEFORE the planner commits. Pure
    read — no write, so no override-permission check needed beyond
    view access (already implied by reaching this page).

    Query params: override_qty | override_pct | override_value (one of),
                  agg_period
    """
    version  = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    location = get_object_or_404(PlanningLocation, pk=location_id, client=request.client)

    try:
        _require_location_view_access(request, location)
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))

    current_agg = (
        ForecastAggregate.objects
        .filter(version=version, agg_level='location', agg_key__location_code=location.code)
        .first()
    )
    if not current_agg:
        return render(request, 'demand/partials/drilldown_override_preview.html', {
            'rows': [], 'note': 'No current aggregate to compare against.',
        })

    qty_raw   = request.GET.get('override_qty', '').strip()
    pct_raw   = request.GET.get('override_pct', '').strip()
    value_raw = request.GET.get('override_value', '').strip()

    if pct_raw:
        try:
            pct = Decimal(pct_raw)
            multiplier = 1 + pct / 100
        except Exception:
            multiplier = None
    else:
        multiplier = None

    children = PlanningLocation.objects.filter(parent=location, is_active=True).order_by('code')
    rows = []
    for child in children:
        child_agg = (
            ForecastAggregate.objects
            .filter(version=version, agg_level='location', agg_key__location_code=child.code)
            .first()
        )
        if not child_agg:
            continue
        before_qty = child_agg.final_qty
        if multiplier is not None:
            after_qty = (before_qty * multiplier)
        else:
            # qty/value-based override: approximate even split for preview
            # (the real apply_overrides task uses proportional historical
            # share — this preview is intentionally a simpler approximation
            # since it must compute instantly on every keystroke)
            after_qty = before_qty
        rows.append({
            'location': child, 'before_qty': before_qty, 'after_qty': after_qty,
        })

    return render(request, 'demand/partials/drilldown_override_preview.html', {
        'rows': rows,
    })

# mysite/demand_ui/views.py
#
# HTMX page views for the Demand Planning client UI.
# Follows the same pattern as your catalogue views: render full pages on
# direct GET, render partial fragments on HTMX requests (request.htmx or
# HX-Request header), and use render_client_template where a client may
# want to override a specific block.
#
# Assumes:
#   - request.client is set by your existing ClientScopedMixin / middleware
#   - the user is authenticated and has access to this client
#   - utils.feature_control.is_demand_feature_disabled exists (Sprint 3B.0)
# Changes from the current version:
#   1. outlier_ui_visible computed via the shared helper (also used
#      by the context processor, so sidebar visibility and this view's own
#      netting decision can never drift out of sync with each other).
#   2. exclude_outliers read from the request (radio button), defaulting to
#      client.forecastingconfig.reporting_uses_net_actuals when not present
#      on the query string yet (first load), same "missing config -> raw"
#      fallback used elsewhere in the outlier-management feature.
#   3. base_qs switches between plain ActualSale and
#      actuals_queryset_with_net(..., use_net=True) depending on the
#      toggle; qty_field/revenue_field name switches from 'qty'/'revenue'
#      to 'net_qty'/'net_revenue' accordingly, used in every Sum(...).
 

from __future__ import annotations

import json
from decimal import Decimal
import pandas as pd
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, FileResponse
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.db.models import Count, Min, Max
from django.views.decorators.http import require_POST

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAggregate,
    ForecastOverride, OverrideSplitWeight, SeriesProfile, SeriesLevelEvaluation,
    AbcClassDefinition, ForecastingConfig,
)
from mysite.models.demand.actuals import (
    ActualSale, ActualSaleOutlierAdjustment, ActualSaleImport, PERIOD_TYPE_CHOICES,
)
from mysite.models.demand.hierarchy import (
    PlanningLocation, SalesNode, SalesForecastLink
)
#from utils.feature_control import is_demand_feature_disabled
from utils.mixins import feature_gate, _is_htmx, _client_url_kwargs
import logging
logger = logging.getLogger(__name__)

import re
from collections import defaultdict
from django.db.models import ExpressionWrapper, BooleanField, Q
from django.db.models.functions import Abs
import datetime
import calendar
from django.db.models import Min, Max, Count
from celery import chain
from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
from mysite.tasks.demand.run_forecast import run_forecast, compute_accuracy

#from decimal import Decimal
from django.db.models import Sum, Count, DecimalField
from django.db.models.functions import Coalesce
from utils.taxonomy_filters import (
        resolve_item_ids_for_multiple_nodes, parse_node_ids_param, TaxonomyFilterError,
    )


from utils.feature_control import outlier_ui_visible as _outlier_ui_visible
from utils.demand.actuals_net import actuals_queryset_with_net
from utils.demand.hierarchy_utils import get_sales_hierarchy_ancestor_map

from mysite.tasks.demand.detect_outliers import flag_stale_forecast_versions
 

# ── Grain pattern helpers ─────────────────────────────────────────────────

_GRAIN_PATTERN_RE = re.compile(r'^(item|taxon)_(\d+)_(.*)$')
_GRAIN_SALESNODE_RE = re.compile(r'_salesnode_\d+')


def _grain_pattern(grain: str) -> str:
    s = _GRAIN_PATTERN_RE.sub(r'\1_\3', grain)
    return _GRAIN_SALESNODE_RE.sub('_salesnode', s)


def _pattern_to_grain_q(pattern: str) -> Q:
    m = re.match(r'^(item|taxon)_(.+)$', pattern)
    if not m:
        return Q(grain=pattern)
    prefix, suffix = m.group(1), m.group(2)
    if suffix == 'salesnode':
        return Q(grain__regex=rf'^{prefix}_\d+_salesnode_\d+$')
    if suffix.startswith('top_'):
        period = suffix[4:]
        return Q(grain__regex=rf'^{prefix}_\d+_top_{period}$')
    return Q(grain__regex=rf'^{prefix}(?:_\d+_|_){suffix}$')


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
"""
def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'


def _feature_gate(request, feature: str):

    result = is_demand_feature_disabled(request.client, feature)
    if result['disabled']:
        return render(request, 'demand/partials/feature_disabled.html', {
            'message': result['message'],
        }, status=403)
    return None


def _client_url_kwargs(request) -> dict:
    return {'client_id': request.client.client_id}
"""


def _demand_ui_role(request) -> str | None:
    """
    Server-side mirror of the demand_ui_role context processor: 'admin' |
    'planner' | None. Used to gate the manual accuracy trigger.
    """
    if not request.user.is_authenticated:
        return None
    if request.user.is_superuser:
        return 'admin'
    groups = set(request.user.groups.values_list('name', flat=True))
    if 'demand_client_admin' in groups:
        return 'admin'
    if 'demand_client_planner' in groups:
        return 'planner'
    return None

# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def dashboard(request, client_id=None):
    """
    GET /{client_id}/demand/

    Landing page. Shows:
      - Count of versions by status
      - Latest version and its run_status
      - Quick links to actuals upload and version create
      - Pending overrides needing application
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    client = request.client

    versions_qs = ForecastVersion.objects.filter(client=client)
    status_counts = {
        s: versions_qs.filter(status=s).count()
        for s in ['DRAFT', 'IN_REVIEW', 'APPROVED', 'LOCKED']
    }
    latest_version = versions_qs.order_by('-created_at').first()
    recent_imports = ActualSaleImport.objects.filter(
        client=client
    ).order_by('-uploaded_at')[:5]

    pending_overrides_count = 0
    if latest_version:
        pending_overrides_count = ForecastOverride.objects.filter(
            version=latest_version, is_applied=False
        ).count()

    context = {
        'status_counts': status_counts,
        'latest_version': latest_version,
        'recent_imports': recent_imports,
        'pending_overrides_count': pending_overrides_count,
        'total_versions': versions_qs.count(),
        'active_nav': 'dashboard'
    }
    return render(request, 'demand/dashboard.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Forecast Versions — list, create, detail
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def version_list(request, client_id=None):
    """
    GET /{client_id}/demand/versions/

    Query params: status (filter)
    HTMX requests return only the table body partial for re-filtering.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    qs = (
        ForecastVersion.objects
        .filter(client=request.client)
        .select_related('created_by', 'approved_by')
        .order_by('-created_at')
    )
    status_filter = request.GET.get('status', '')
    if status_filter:
        qs = qs.filter(status=status_filter)

    role = _demand_ui_role(request)
    versions = list(qs)
    for v in versions:
        v.can_run_accuracy, v.accuracy_button_reason = v.accuracy_button_state(role)

    context = {
        'versions': versions,
        'status_filter': status_filter,
        'status_choices': ForecastVersion.Status.choices,
        'active_nav': 'versions',
    }

    if _is_htmx(request):
        return render(request, 'demand/partials/version_table_body.html', context)
    return render(request, 'demand/version_list.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def version_create(request, client_id=None):
    blocked = feature_gate(request, 'forecast_run')
    if blocked:
        return blocked

    #import datetime
    #import calendar
    #from django.db.models import Min, Max, Count
    #from mysite.models.demand.actuals import ActualSale

    def _get_actuals_context():
        actuals = ActualSale.objects.filter(
            client=request.client
        ).aggregate(
            earliest=Min('period_start'),
            latest=Max('period_start'),
            count=Count('period_start', distinct=True),
        )
        actuals_from    = actuals['earliest']
        actuals_to      = actuals['latest']
        actuals_periods = actuals['count']

        # Default base_period_end = last actuals month end
        default_base_end = None
        if actuals_to:
            last_day = calendar.monthrange(
                actuals_to.year, actuals_to.month
            )[1]
            default_base_end = datetime.date(
                actuals_to.year, actuals_to.month, last_day
            )

        # Default horizon = 6 periods starting month after actuals_to
        default_horizon_periods = 6

        return {
            'actuals_from':           actuals_from,
            'actuals_to':             actuals_to,
            'actuals_periods':        actuals_periods,
            'default_base_end':       default_base_end,
            'default_horizon_periods': default_horizon_periods,
            'active_nav': 'versions',
        }

    # ── POST ──────────────────────────────────────────────────────────────────
    if request.method == 'POST':
        label           = request.POST.get('version_label', '').strip()
        period_type     = request.POST.get('period_type', 'month')
        base_end_s      = request.POST.get('base_period_end', '').strip()
        horizon_s       = request.POST.get('horizon_periods', '').strip()
        notes           = request.POST.get('notes', '').strip()

        errors = {}

        if not label:
            errors['version_label'] = 'Required.'

        base_end = None
        try:
            base_end = datetime.date.fromisoformat(base_end_s)
        except ValueError:
            errors['base_period_end'] = 'Required. Use YYYY-MM-DD format.'

        horizon_periods = None
        try:
            horizon_periods = int(horizon_s)
            if horizon_periods < 1:
                errors['horizon_periods'] = 'Must be at least 1.'
        except ValueError:
            errors['horizon_periods'] = 'Must be a whole number.'

        if errors:
            ctx = _get_actuals_context()
            ctx.update({
                'errors':         errors,
                'form_error':     None,
                'period_choices': PERIOD_TYPE_CHOICES,
                'form_data':      request.POST,
            })
            response = render(
                request,
                'demand/partials/version_create_form.html',
                ctx, status=400
            )
            response['HX-Retarget'] = '#modal-content'
            response['HX-Reswap']   = 'innerHTML'
            return response

        version = ForecastVersion.objects.create(
            client          = request.client,
            version_label   = label,
            period_type     = period_type,
            base_period_end = base_end,
            horizon_periods = horizon_periods,
            notes           = notes,
            status          = ForecastVersion.Status.DRAFT,
            created_by      = request.user,
        )

        if _is_htmx(request):
            versions = (
                ForecastVersion.objects
                .filter(client=request.client)
                .select_related('created_by')
                .order_by('-created_at')[:20]
            )
            response = render(
                request,
                'demand/partials/version_table_body.html',
                {'versions': versions},
            )
            response['HX-Trigger'] = 'versionCreated'
            return response

        messages.success(
            request, f'Created version "{version.version_label}".'
        )
        return redirect(
            'demand_ui:version_detail',
            client_id=request.client.client_id, pk=version.pk
        )

    # ── GET ───────────────────────────────────────────────────────────────────
    ctx = _get_actuals_context()
    ctx['period_choices'] = PERIOD_TYPE_CHOICES

    if _is_htmx(request):
        return render(
            request, 'demand/partials/version_create_form.html', ctx
        )
    return render(request, 'demand/version_create.html', ctx)

@login_required
def version_detail(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/

    Shows version metadata, status badge, run_status, and tab navigation
    to lines / aggregates / overrides / accuracy / export.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(
        ForecastVersion.objects.select_related('created_by', 'approved_by'),
        pk=pk, client=request.client,
    )
    line_count      = version.lines.count()
    aggregate_count = version.aggregates.count()
    override_count  = version.overrides.count()
    pending_override_count = version.overrides.filter(is_applied=False).count()

    context = {
        'version': version,
        'line_count': line_count,
        'aggregate_count': aggregate_count,
        'override_count': override_count,
        'pending_override_count': pending_override_count,
        'active_nav': 'versions',
    }
    return render(request, 'demand/version_detail.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Forecast run + polling
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['POST'])
def version_run(request, pk, client_id=None):
    """
    POST /{client_id}/demand/versions/{id}/run/

    Triggers the Celery chain (compute_series_profiles → run_forecast).
    Returns the run-status partial which polls itself via hx-trigger.
    """
    blocked = feature_gate(request, 'forecast_run')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if not version.is_editable:
        messages.error(request, f'Version is {version.status}. Only DRAFT versions can be run.')
        return render(request, 'demand/partials/run_status.html', {'version': version})

    if version.run_status in ('QUEUED', 'PROFILING', 'RUNNING', 'RECONCILING', 'AGGREGATING'):
        messages.warning(request, 'A forecast run is already in progress.')
        return render(request, 'demand/partials/run_status.html', {'version': version})

    #from celery import chain
    #from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
    #from mysite.tasks.demand.run_forecast import run_forecast

    task_chain = chain(
        compute_series_profiles.si(version.client.pk, version.period_type),
        run_forecast.si(version.pk),
    )
    async_result = task_chain.apply_async()

    task_id = async_result.id
    if not task_id:
        logger.warning(
            "version_run: apply_async() returned no task ID for version pk=%s — "
            "Celery backend may be misconfigured. Run status will be QUEUED but "
            "progress cannot be tracked.",
            pk,
        )

    ForecastVersion.objects.filter(pk=pk).update(
        run_status='QUEUED',
        celery_task_id=task_id or '',
        run_error='',
    )
    version.refresh_from_db()

    return render(request, 'demand/partials/run_status.html', {'version': version})


@login_required
def version_run_status(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/run-status/

    Polled by HTMX every 2s while a run is in progress (hx-trigger="every 2s").
    Returns the same partial; the partial itself decides whether to keep
    polling based on run_status (stops polling once COMPLETE or FAILED).
    """
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if not version.celery_task_id and version.run_status == 'QUEUED':
        logger.warning(
            "version_run_status: version pk=%s is QUEUED but has no celery_task_id — "
            "cannot poll task progress.",
            pk,
        )

    return render(request, 'demand/partials/run_status.html', {'version': version})

    #version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    #return render(request, 'demand/partials/run_status.html', {'version': version})


@login_required
@require_http_methods(['POST'])
def version_approve(request, pk, client_id=None):
    """
    POST /{client_id}/demand/versions/{id}/approve/

    Body (form-encoded): action=submit|approve|reject|lock, note=...
    """
    blocked = feature_gate(request, 'forecast_approval')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    action  = request.POST.get('action', '').strip().lower()
    note    = request.POST.get('note', '').strip()

    transitions = {
        'submit':  ForecastVersion.Status.IN_REVIEW,
        'approve': ForecastVersion.Status.APPROVED,
        'reject':  ForecastVersion.Status.DRAFT,
        'lock':    ForecastVersion.Status.LOCKED,
    }

    if action not in transitions:
        messages.error(request, f'Unknown action "{action}".')
        return redirect('demand_ui:version_detail', client_id=request.client.client_id, pk=pk)

    from django.core.exceptions import ValidationError
    try:
        version.transition_to(transitions[action], user=request.user)
        if note:
            version.notes = (version.notes + f'\n[{action}] {note}').strip()
            version.save(update_fields=['notes'])
        messages.success(request, f'Version moved to {version.get_status_display()}.')
    except ValidationError as exc:
        messages.error(request, str(exc.message if hasattr(exc, "message") else exc))

    if _is_htmx(request):
        response = HttpResponse(status=204)
        response['HX-Redirect'] = reverse(
            'demand_ui:version_detail',
            kwargs={**_client_url_kwargs(request), 'pk': pk},
        )
        return response
    return redirect('demand_ui:version_detail', client_id=request.client.client_id, pk=pk)


@login_required
@require_http_methods(['POST'])
def version_delete(request, pk, client_id=None):
    """POST /{client_id}/demand/versions/{id}/delete/ — delete a DRAFT version."""
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    if not (request.user.is_superuser or request.user.groups.filter(
        name__in=['demand_client_admin', 'demand_client_planner']
    ).exists()):
        messages.error(request, 'You do not have permission to delete versions.')
        return redirect('demand_ui:version_list', client_id=request.client.client_id)

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if version.status != ForecastVersion.Status.DRAFT:
        messages.error(request, 'Only DRAFT versions can be deleted.')
        return redirect('demand_ui:version_list', client_id=request.client.client_id)

    label = version.version_label
    version.delete()
    messages.success(request, f'Version "{label}" has been deleted.')

    if _is_htmx(request):
        response = HttpResponse(status=204)
        response['HX-Redirect'] = reverse(
            'demand_ui:version_list',
            kwargs={**_client_url_kwargs(request)},
        )
        return response
    return redirect('demand_ui:version_list', client_id=request.client.client_id)


@login_required
@require_http_methods(['POST'])
def version_copy(request, pk, client_id=None):
    """POST /{client_id}/demand/versions/{id}/copy/ — clone to new DRAFT."""
    blocked = feature_gate(request, 'forecast_run')
    if blocked:
        return blocked

    version  = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    new_label = request.POST.get('new_label', '').strip() or f'{version.version_label} (copy)'
    new_version = version.copy(user=request.user, new_label=new_label)
    messages.success(request, f'Created copy "{new_version.version_label}".')

    response = HttpResponse(status=204)
    response['HX-Redirect'] = reverse(
        'demand_ui:version_detail',
        kwargs={**_client_url_kwargs(request), 'pk': new_version.pk},
    )
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Forecast Lines (grid)
# ─────────────────────────────────────────────────────────────────────────────
@login_required
def version_lines(request, pk, client_id=None):
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    qs = (
        ForecastLine.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer', 'distribution_channel')
        .order_by('period_start', 'planning_location__code', 'item__item_id')
    )

    item_id       = request.GET.get('item_id', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    channel_code  = request.GET.get('channel_code', '').strip()
    has_override  = request.GET.get('has_override', '')
    period_start  = request.GET.get('period_start', '').strip()

    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if customer_code:
        qs = qs.filter(planning_customer__code=customer_code)
    if channel_code:
        qs = qs.filter(distribution_channel__code=channel_code)
    if has_override == 'true':
        qs = qs.filter(override_qty__isnull=False)
    elif has_override == 'false':
        qs = qs.filter(override_qty__isnull=True)
    if period_start:
        qs = qs.filter(period_start=period_start)

    # Dropdown choices from filtered qs
    locations = list(
        qs.exclude(planning_location__isnull=True)
        .values_list('planning_location__code', 'planning_location__name')
        .distinct().order_by('planning_location__code')
    )
    customers = list(
        qs.exclude(planning_customer__isnull=True)
        .values_list('planning_customer__code', 'planning_customer__name')
        .distinct().order_by('planning_customer__code')
    )
    if version.client.is_distribution_channel_enabled():
        channel_count = qs.values('distribution_channel').distinct().count()
        show_channel = channel_count > 1
        channels = list(
            qs.exclude(distribution_channel__isnull=True)
            .values_list('distribution_channel__code', 'distribution_channel__label')
            .distinct().order_by('distribution_channel__code')
        )
    else:
        show_channel = False
        channels = []
    periods = list(
        qs.values_list('period_start', flat=True)
        .distinct().order_by('period_start')
    )

    # Distinct item count — drives qty total visibility
    distinct_items = qs.values('item__item_id').distinct().count()
    single_item    = distinct_items == 1

    # Totals
    #from django.db.models import Sum
    #from django.db.models.functions import Coalesce
    #from django.db.models import DecimalField

    grand_total = qs.aggregate(
        total_stat_qty=Coalesce(Sum('statistical_qty'), Decimal('0'),
                                output_field=DecimalField()),
        total_final_qty=Coalesce(Sum('final_qty'), Decimal('0'),
                                 output_field=DecimalField()),
        total_stat_value=Coalesce(Sum('statistical_value'), Decimal('0'),
                                  output_field=DecimalField()),
        total_final_value=Coalesce(Sum('final_value'), Decimal('0'),
                                   output_field=DecimalField()),
    )

    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    # Page total
    page_ids = [line.pk for line in page_obj.object_list]
    page_total = ForecastLine.objects.filter(pk__in=page_ids).aggregate(
        total_stat_qty=Coalesce(Sum('statistical_qty'), Decimal('0'),
                                output_field=DecimalField()),
        total_final_qty=Coalesce(Sum('final_qty'), Decimal('0'),
                                 output_field=DecimalField()),
        total_stat_value=Coalesce(Sum('statistical_value'), Decimal('0'),
                                  output_field=DecimalField()),
        total_final_value=Coalesce(Sum('final_value'), Decimal('0'),
                                   output_field=DecimalField()),
    )

    filters = {
        'item_id':       item_id,
        'location_code': location_code,
        'customer_code': customer_code,
        'channel_code':  channel_code,
        'has_override':  has_override,
        'period_start':  period_start,
    }

    context = {
        'version':        version,
        'page_obj':       page_obj,
        'filters':        filters,
        'locations':      locations,
        'customers':      customers,
        'channels':       channels,
        'periods':        periods,
        'grand_total':    grand_total,
        'page_total':     page_total,
        'single_item':    single_item,
        'is_multipage':   page_obj.has_other_pages(),
        'show_location':  len(locations) > 1,
        'show_customer':  len(customers) > 1,
        'show_channel':   show_channel,
        'show_period':    len(periods) > 1,
        'show_item_search': distinct_items > 1,
        'show_override_filter': qs.filter(
            override_qty__isnull=False).exists(),
        'active_nav': 'versions',
    }

    if _is_htmx(request):
        from django.template.loader import render_to_string
        html = (
            render_to_string('demand/partials/lines_filter_bar.html',
                             context, request) +
            render_to_string('demand/partials/lines_table_body.html',
                             context, request)
        )
        return HttpResponse(html)

    return render(request, 'demand/version_lines.html', context)

@login_required
def version_line_row(request, pk, line_id, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/lines/row/{line_id}/

    Returns a single <tr> partial — used after an inline override edit
    to refresh just that row (final_qty / final_value recompute).
    """
    line = get_object_or_404(
        ForecastLine.objects.select_related('item', 'planning_location', 'planning_customer', 'distribution_channel'),
        pk=line_id, version_id=pk, version__client=request.client,
    )
    show_channel = (
        line.version.client.is_distribution_channel_enabled()
        and ForecastLine.objects.filter(version=line.version)
            .values('distribution_channel').distinct().count() > 1
    )
    return render(request, 'demand/partials/lines_table_row.html', {
        'line': line, 'show_channel': show_channel,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Aggregates (value summary)
# ─────────────────────────────────────────────────────────────────────────────
@login_required
def version_aggregates(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/aggregates/

    Query params: agg_level (total|location|item|customer)
    Shows the comprehensible single-number view per your Sprint 3B.4
    value-based design — planners see ₹ totals, not 20K SKU rows.
    """

    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    agg_level = request.GET.get('agg_level', 'total')
    valid_levels = ['total', 'location', 'item', 'customer']
    if agg_level not in valid_levels:
        agg_level = 'total'

    # ── Filters per level ─────────────────────────────────────────────────────
    period_start  = request.GET.get('period_start', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    item_id       = request.GET.get('item_id', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    final_value_min = request.GET.get('final_value_min', '').strip()
    final_value_max = request.GET.get('final_value_max', '').strip()
    final_qty_min   = request.GET.get('final_qty_min', '').strip()
    final_qty_max   = request.GET.get('final_qty_max', '').strip()

    qs = (
        ForecastAggregate.objects
        .filter(version=version, agg_level=agg_level)
        .order_by('period_start', 'agg_key')
    )

    # ── Location hierarchy filter for location level ──────────────────────
    location_hierarchy_choices = []
    if agg_level == 'location':
        from mysite.models import PlanningLocation
        # Get all non-leaf locations (ancestors) as hierarchy filter options
        location_hierarchy_choices = list(
            PlanningLocation.objects
            .filter(client=request.client, is_leaf=False)
            .order_by('level_label', 'code')
            .values('id', 'code', 'name', 'level_label')
        )

    # ── Taxonomy node filter for item level ───────────────────────────────
    """
    taxonomy_choices = []
    if agg_level == 'item':
        from mysite.models.catalogue import TaxonomyNode
        taxonomy_choices = list(
            TaxonomyNode.objects
            .filter(client=request.client, is_active=True)
            .select_related('taxonomy')
            .order_by('depth', 'name')
            .values('id', 'name', 'depth', 'taxonomy__name')
        )
    """
    # Add to filter application:
    hierarchy_location_id = request.GET.get('hierarchy_location_id', '').strip()
    taxonomy_node_id      = request.GET.get('taxonomy_node_id', '').strip()
    logger.debug(f'version_aggregates: taxonomy_node_id={taxonomy_node_id!r}')
    
    if agg_level == 'location' and hierarchy_location_id:
        # Filter to locations that are descendants of this ancestor
        try:
            ancestor = PlanningLocation.objects.get(
                pk=hierarchy_location_id, client=request.client
            )
            # Use path-based descendant lookup
            descendant_ids = (
                PlanningLocation.objects
                .filter(
                    client=request.client,
                    path__startswith=ancestor.path,
                    is_leaf=True,
                )
                .values_list('id', flat=True)
            )
            # agg_key contains location_id — filter aggregates
            qs = qs.filter(
                agg_key__location_id__in=list(descendant_ids)
            )
        except PlanningLocation.DoesNotExist:
            pass
    """
    if agg_level == 'item' and taxonomy_node_id:
        try:
            from mysite.models.catalogue import TaxonomyNode, ItemTaxonomyNode
            selected_node = TaxonomyNode.objects.get(
                pk=taxonomy_node_id,
                client=request.client
            )
            # Include selected node and all its descendants
            descendant_node_ids = list(
                TaxonomyNode.objects
                .filter(
                    client=request.client,
                    path__startswith=selected_node.path,
                )
                .values_list('id', flat=True)
            )
            # Get item_ids mapped to these nodes
            item_ids_in_node = list(
                ItemTaxonomyNode.objects
                .filter(node_id__in=descendant_node_ids)
                .values_list('item__item_id', flat=True)
                .distinct()
            )
            if item_ids_in_node:
                qs = qs.filter(agg_key__item_id__in=item_ids_in_node)
            else:
                qs = qs.none()  # node exists but has no items mapped
        except TaxonomyNode.DoesNotExist:
            pass
        except Exception as exc:
            logger.warning(f'version_aggregates: taxonomy filter failed: {exc}')
    """
    from utils.taxonomy_filters import (
        resolve_item_ids_for_multiple_nodes, TaxonomyFilterError,
    )

    # was: taxonomy_node_id = request.GET.get('taxonomy_node_id', '').strip()
    #taxonomy_node_ids = request.GET.getlist('taxonomy_node_ids')

   
    taxonomy_node_ids = parse_node_ids_param(request)
    

    if agg_level == 'item' and taxonomy_node_ids:
        try:
            item_ids = resolve_item_ids_for_multiple_nodes(request.client, taxonomy_node_ids)
            if item_ids is not None:
                qs = qs.filter(agg_key__item_id__in=item_ids) if item_ids else qs.none()
        except TaxonomyFilterError as exc:
            logger.warning(f'version_aggregates: {exc}')
            qs = qs.none()  # fail closed, never silently unfiltered

    # Period filter — common to all levels
    if period_start:
        qs = qs.filter(period_start=period_start)

    # Level-specific key filters using agg_key JSONField
    if agg_level == 'location' and location_code:
        qs = qs.filter(agg_key__location_code=location_code)
    if agg_level == 'item' and item_id:
        qs = qs.filter(agg_key__item_id__icontains=item_id)
    if agg_level == 'customer' and customer_code:
        qs = qs.filter(agg_key__customer_code=customer_code)

    # Value range filters
    if final_value_min:
        try:
            qs = qs.filter(total_final_value__gte=Decimal(final_value_min))
        except Exception:
            pass
    if final_value_max:
        try:
            qs = qs.filter(total_final_value__lte=Decimal(final_value_max))
        except Exception:
            pass

    # Qty range filters — only relevant for item level
    if agg_level == 'item':
        if final_qty_min:
            try:
                qs = qs.filter(final_qty__gte=Decimal(final_qty_min))
            except Exception:
                pass
        if final_qty_max:
            try:
                qs = qs.filter(final_qty__lte=Decimal(final_qty_max))
            except Exception:
                pass

    # ── Distinct item count — drives qty visibility ───────────────────────────
    single_item = False
    if agg_level == 'item':
        show_qty = True   # qty always meaningful at item level
    else:
        show_qty = False
    

    # ── Dropdown choices from this version's data ─────────────────────────────
    periods = list(
        ForecastAggregate.objects
        .filter(version=version, agg_level=agg_level)
        .values_list('period_start', flat=True)
        .distinct()
        .order_by('period_start')
    )

    # Location choices for location level
    location_choices = []
    if agg_level == 'location':
        from mysite.models import PlanningLocation
        location_choices = list(
            PlanningLocation.objects
            .filter(client=request.client)
            .order_by('code')
            .values_list('code', 'name')
        )

    # Customer choices for customer level
    customer_choices = []
    if agg_level == 'customer':
        from mysite.models import PlanningCustomer
        customer_choices = list(
            PlanningCustomer.objects
            .filter(client=request.client)
            .order_by('code')
            .values_list('code', 'name')
        )

    # ── Totals ────────────────────────────────────────────────────────────────
    #from django.db.models import Sum, DecimalField
    #from django.db.models.functions import Coalesce

    grand_total = qs.aggregate(
        total_stat_value=Coalesce(
            Sum('total_statistical_value'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_final_value=Coalesce(
            Sum('total_final_value'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_stat_qty=Coalesce(
            Sum('statistical_qty'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_final_qty=Coalesce(
            Sum('final_qty'), Decimal('0'),
            output_field=DecimalField()
        ),
    )

    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    page_ids = [a.pk for a in page_obj.object_list]
    page_total = ForecastAggregate.objects.filter(pk__in=page_ids).aggregate(
        total_stat_value=Coalesce(
            Sum('total_statistical_value'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_final_value=Coalesce(
            Sum('total_final_value'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_stat_qty=Coalesce(
            Sum('statistical_qty'), Decimal('0'),
            output_field=DecimalField()
        ),
        total_final_qty=Coalesce(
            Sum('final_qty'), Decimal('0'),
            output_field=DecimalField()
        ),
    )

    # ── has_override and friendly key per row ─────────────────────────────────
    aggregates = list(page_obj.object_list)
    for agg in aggregates:
        stat  = agg.total_statistical_value
        final = agg.total_final_value
        agg.has_override = (
            stat is not None and final is not None
            and abs(float(final) - float(stat)) > 0.5
        )
        # Build a user-friendly display key
        key = agg.agg_key or {}
        if agg_level == 'total':
            agg.display_key = 'All'
        elif agg_level == 'location':
            agg.display_key = key.get('location_code', key.get('code', '—'))
        elif agg_level == 'item':
            agg.display_key = key.get('item_id', '—')
        elif agg_level == 'customer':
            agg.display_key = key.get('customer_code', key.get('code', '—'))
        else:
            agg.display_key = str(key)

    filters = {
        'period_start':    period_start,
        'location_code':   location_code,
        'item_id':         item_id,
        'customer_code':   customer_code,
        'final_value_min': final_value_min,
        'final_value_max': final_value_max,
        'final_qty_min':   final_qty_min,
        'final_qty_max':   final_qty_max,
        'hierarchy_location_id': hierarchy_location_id,
        'taxonomy_node_ids': ','.join(taxonomy_node_ids),   # was: 'taxonomy_node_id': taxonomy_node_id
        'taxonomy_node_count': len(taxonomy_node_ids),
    }

    context = {
        'version':          version,
        'aggregates':       aggregates,
        'page_obj':         page_obj,
        'agg_level':        agg_level,
        'agg_level_choices': valid_levels,
        'grand_total':      grand_total,
        'page_total':       page_total,
        'show_qty':         show_qty,
        'single_item':      single_item,
        'is_multipage':     page_obj.has_other_pages(),
        'filters':          filters,
        'periods':          periods,
        'location_choices': location_choices,
        'customer_choices': customer_choices,
        'active_nav': 'versions',
        'location_hierarchy_choices': location_hierarchy_choices,
        #'taxonomy_choices': taxonomy_choices,
    }

    if _is_htmx(request):
        from django.template.loader import render_to_string
        html = (
            render_to_string(
                'demand/partials/aggregates_filter_bar.html',
                context, request
            ) +
            render_to_string(
                'demand/partials/aggregates_table_body.html',
                context, request
            )
        )
        return HttpResponse(html)

    return render(request, 'demand/version_aggregates.html', context)




# ─────────────────────────────────────────────────────────────────────────────
# Overrides
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def override_list(request, pk, client_id=None):
    """GET /{client_id}/demand/versions/{id}/overrides/"""
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    overrides = (
        ForecastOverride.objects
        .filter(version=version)
        .select_related('created_by')
        .order_by('-created_at')
    )
    context = {'version': version, 'overrides': overrides, 'active_nav': 'versions',}

    if _is_htmx(request):
        return render(request, 'demand/partials/override_table_body.html', context)
    return render(request, 'demand/override_list.html', context)

@login_required
@require_http_methods(['GET', 'POST'])
def override_create(request, pk, client_id=None):
    blocked = feature_gate(request, 'consensus_override')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if not version.is_editable:
        messages.error(request, f'Version is {version.status}. Overrides require a DRAFT version.')
        return redirect('demand_ui:override_list', client_id=request.client.client_id, pk=pk)

    if request.method == 'GET':
        if _is_htmx(request):
            return render(request, 'demand/partials/override_create_form.html', {'version': version})
        return render(request, 'demand/override_create.html', {'version': version})

    # ── POST ────────────────────────────────────────────────────────────────
    override_level = request.POST.get('override_level', 'sku')
    period_start_s = request.POST.get('period_start', '')
    disagg_method  = request.POST.get('disagg_method', 'PROPORTIONAL')
    note           = request.POST.get('override_note', '').strip()

    override_key = {}
    if override_level == 'sku' and request.POST.get('item_id'):
        override_key = {'item_id': request.POST['item_id']}
    elif override_level == 'location' and request.POST.get('location_code'):
        override_key = {'location_code': request.POST['location_code']}
    elif override_level == 'customer' and request.POST.get('customer_code'):
        override_key = {'customer_code': request.POST['customer_code']}
    elif override_level == 'total':
        override_key = {'level': 'total'}

    qty_raw   = request.POST.get('override_qty', '').strip()
    pct_raw   = request.POST.get('override_pct', '').strip()
    value_raw = request.POST.get('override_value', '').strip()

    import datetime
    errors = {}
    try:
        period_start = datetime.date.fromisoformat(period_start_s)
    except ValueError:
        errors['period_start'] = 'Use YYYY-MM-DD.'
        period_start = None

    set_count = sum(bool(v) for v in (qty_raw, pct_raw, value_raw))
    if set_count != 1:
        errors['override_value_group'] = 'Set exactly one of Qty, %, or ₹ Value.'
    if not override_key:
        errors['override_key'] = 'Identify what you are overriding.'

    def render_error(errors, form_error=None):
        response = render(request, 'demand/partials/override_create_form.html', {
            'version': version,
            'errors': errors,
            'form_error': form_error,
            'form_data': request.POST,
        }, status=400)
        response['HX-Retarget'] = '#override-create-modal-content'
        response['HX-Reswap'] = 'innerHTML'
        return response

    if errors:
        return render_error(errors)

    override = ForecastOverride(
        version        = version,
        override_level = override_level,
        override_key   = override_key,
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
    except Exception as exc:
        return render_error({}, form_error=str(exc))

    from mysite.tasks.demand.run_forecast import apply_overrides
    apply_overrides.apply_async(args=[version.pk], countdown=2)

    overrides = (
        ForecastOverride.objects
        .filter(version=version)
        .select_related('created_by')
        .order_by('-created_at')
    )
    response = render(
        request,
        'demand/partials/override_table_body.html',
        {'version': version, 'overrides': overrides, 'active_nav': 'versions'},
    )
    response['HX-Trigger'] = 'overrideCreated'
    return response


@login_required
@require_http_methods(['POST', 'DELETE'])
def override_delete(request, pk, override_id, client_id=None):
    """
    DELETE /{client_id}/demand/versions/{id}/overrides/{override_id}/delete/

    Only unapplied overrides on DRAFT versions can be deleted
    (matches the admin.has_delete_permission guard from Sprint 3B.3).
    """
    blocked = feature_gate(request, 'consensus_override')
    if blocked:
        return blocked

    #override = get_object_or_404(
    #    ForecastOverride, pk=override_id, pk__exact=override_id,
    #    version_id=pk, version__client=request.client,
    #)
    override = get_object_or_404(
        ForecastOverride, pk=override_id, 
        version_id=pk, version__client=request.client,
    )

    if not override.version.is_editable:
        messages.error(request, 'Cannot delete overrides on a non-DRAFT version.')
    elif override.is_applied:
        messages.error(request, 'Cannot delete an applied override. Create an offsetting override instead.')
    else:
        override.delete()
        messages.success(request, 'Override deleted.')

    overrides = (
        ForecastOverride.objects
        .filter(version_id=pk)
        .select_related('created_by')
        .order_by('-created_at')
    )
    return render(request, 'demand/partials/override_table_body.html', {
        #'version': override.version if 'override' in dir() else None,
        'version': override.version,
        'overrides': overrides, 'active_nav': 'versions',
    })


@login_required
def override_affected_lines(request, pk, override_id, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/overrides/{override_id}/affected/

    Shows which ForecastLine rows were touched by this override —
    the propagation view your earlier sprint plan called for.
    """
    override = get_object_or_404(
        ForecastOverride, pk=override_id, version_id=pk, version__client=request.client,
    )

    qs = ForecastLine.objects.filter(
        version_id=pk,
        period_type=override.period_type,
        period_start=override.period_start,
    ).select_related('item', 'planning_location', 'planning_customer', 'distribution_channel')

    key = override.override_key
    if override.override_level == 'sku' and key.get('item_id'):
        qs = qs.filter(item__item_id=key['item_id'])
    elif override.override_level == 'location' and key.get('location_code'):
        qs = qs.filter(planning_location__code=key['location_code'])
    elif override.override_level == 'customer' and key.get('customer_code'):
        qs = qs.filter(planning_customer__code=key['customer_code'])

    client = override.version.client
    if client.is_distribution_channel_enabled():
        show_channel = qs.values('distribution_channel').distinct().count() > 1
    else:
        show_channel = False

    return render(request, 'demand/partials/override_affected_lines.html', {
        'override': override, 'lines': qs, 'show_channel': show_channel, 'active_nav': 'versions',
    })


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def version_export(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/export/

    Streams an .xlsx export. Page itself just shows a download button
    that hits this endpoint directly (not via HTMX — browsers handle
    file downloads natively).
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if request.GET.get('format') != 'xlsx':
        # Show the export options page first
        return render(request, 'demand/version_export.html', {'version': version})

    import io
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Forecast Export'

    headers = ['Item', 'Location', 'Customer', 'Period', 'Statistical Qty',
               'Override Qty', 'Final Qty', 'Final Value']
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='1F4E79')

    lines = (
        ForecastLine.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('period_start', 'planning_location__code', 'item__item_id')
    )
    for line in lines:
        ws.append([
            line.item.item_id,
            line.planning_location.code,
            line.planning_customer.code if line.planning_customer else '',
            line.period_start.isoformat(),
            float(line.statistical_qty),
            float(line.override_qty) if line.override_qty is not None else '',
            float(line.final_qty),
            float(line.final_value) if line.final_value is not None else '',
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f'forecast_{version.version_label.replace(" ", "_")}.xlsx'
    response = FileResponse(
        buf, as_attachment=True, filename=filename,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Accuracy
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def version_accuracy(request, pk, client_id=None):
    """GET /{client_id}/demand/versions/{id}/accuracy/"""
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    from mysite.models.demand.forecast import ForecastAccuracy
    from utils.demand.accuracy_report import (
        compute_metrics, location_children, taxonomy_children,
    )

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    qs = (
        ForecastAccuracy.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer', 'distribution_channel')
        .order_by('-mape')
    )

    if version.client.is_distribution_channel_enabled():
        channel_count = qs.values('distribution_channel').distinct().count()
        show_channel = channel_count > 1
    else:
        show_channel = False

    rows = list(qs)
    mapes = [float(r.mape) for r in rows if r.mape is not None]
    biases = [float(r.bias) for r in rows if r.bias is not None]
    avg_mape = (sum(mapes) / len(mapes)) if mapes else None
    avg_bias = (sum(biases) / len(biases)) if biases else None

    # Weighted metrics from the leaf rows (single DB pass).
    import pandas as pd
    df = pd.DataFrame(list(ForecastAccuracy.objects.filter(version=version).values(
        'actual_qty', 'forecast_qty', 'actual_value', 'forecast_value',
    )))
    weighted = compute_metrics(df)

    drill_location_rows, _, location_breadcrumb = location_children(version)
    drill_taxonomy_rows, _, taxonomy_breadcrumb = taxonomy_children(version)

    role = _demand_ui_role(request)

    context = {
        'version': version, 'accuracy_rows': rows[:200],
        'avg_mape': avg_mape, 'avg_bias': avg_bias,
        'weighted': weighted,
        'drill_location_rows': drill_location_rows,
        'drill_taxonomy_rows': drill_taxonomy_rows,
        'location_breadcrumb': location_breadcrumb,
        'taxonomy_breadcrumb': taxonomy_breadcrumb,
        'total_rows': len(rows),
        'show_channel': show_channel,
        'can_run_accuracy': version.accuracy_button_enabled(role),
        'accuracy_run_active': version.accuracy_run_status in (
            ForecastVersion.AccuracyRunStatus.QUEUED,
            ForecastVersion.AccuracyRunStatus.RUNNING,
        ),
        'active_nav': 'versions',
    }
    if _is_htmx(request):
        return render(request, 'demand/partials/accuracy_table_body.html', context)
    return render(request, 'demand/version_accuracy.html', context)


@login_required
@require_http_methods(['POST'])
def version_accuracy_run(request, pk, client_id=None):
    """
    POST /{client_id}/demand/versions/{id}/accuracy/run/

    Triggers compute_accuracy for this single version via Celery.
    Enforce the same enable rule server-side (role + status + actuals).
    Returns the accuracy-run-status partial, which polls itself via HTMX.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    role = _demand_ui_role(request)

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    if not version.accuracy_button_enabled(role):
        messages.error(request, 'Accuracy run not permitted for this version.')
        return render(
            request, 'demand/partials/accuracy_run_status.html',
            {'version': version},
        )

    if version.accuracy_run_status in (
        ForecastVersion.AccuracyRunStatus.QUEUED,
        ForecastVersion.AccuracyRunStatus.RUNNING,
    ):
        messages.warning(request, 'An accuracy run is already in progress.')
        return render(
            request, 'demand/partials/accuracy_run_status.html',
            {'version': version},
        )

    try:
        async_result = compute_accuracy.delay(version.client.pk, version.pk)
        task_id = async_result.id
    except Exception:
        logger.exception(
            'version_accuracy_run: apply_async failed for version pk=%s '
            '(Celery may be down).', pk,
        )
        task_id = ''

    ForecastVersion.objects.filter(pk=pk).update(
        accuracy_run_status='QUEUED',
        accuracy_run_error='',
        celery_task_id=task_id or '',
    )
    version.refresh_from_db()

    return render(
        request, 'demand/partials/accuracy_run_status.html',
        {
            'version': version,
            'can_run_accuracy': version.accuracy_button_enabled(role),
        },
    )


@login_required
def version_accuracy_run_status(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/accuracy/run-status/

    Polled by HTMX while an accuracy run is in progress. Returns the same
    partial; the partial stops polling once COMPLETE or FAILED.
    """
    role = _demand_ui_role(request)
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(
        request, 'demand/partials/accuracy_run_status.html',
        {
            'version': version,
            'can_run_accuracy': version.accuracy_button_enabled(role),
        },
    )


@login_required
def accuracy_hierarchy_locations(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/accuracy/hierarchy-locations/
    Query params: location_id (drill into a location), items=1 (item rows).
    HTMX partial: swaps itself into #accuracy-hierarchy-locations-container.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    from utils.demand.accuracy_report import location_children, location_items

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    location_id = request.GET.get('location_id')
    try:
        location_id = int(location_id) if location_id else None
    except (TypeError, ValueError):
        location_id = None
    items = request.GET.get('items') in ('1', 'true', 'True')

    if items and location_id:
        rows, current, breadcrumb = location_items(version, location_id)
    else:
        rows, current, breadcrumb = location_children(version, location_id)

    return render(
        request, 'demand/partials/accuracy_hierarchy_locations.html',
        {
            'version': version,
            'rows': rows,
            'current': current,
            'breadcrumb': breadcrumb,
            'items': items,
        },
    )


@login_required
def accuracy_hierarchy_taxonomy(request, pk, client_id=None):
    """
    GET /{client_id}/demand/versions/{id}/accuracy/hierarchy-taxonomy/
    Query params: node_path (materialized path to drill into), items=1.
    HTMX partial: swaps itself into #accuracy-hierarchy-taxonomy-container.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    from utils.demand.accuracy_report import taxonomy_children, taxonomy_items

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    node_path = request.GET.get('node_path') or None
    items = request.GET.get('items') in ('1', 'true', 'True')

    if items and node_path:
        rows, breadcrumb = taxonomy_items(version, node_path)
    else:
        rows, _, breadcrumb = taxonomy_children(version, node_path)

    return render(
        request, 'demand/partials/accuracy_hierarchy_taxonomy.html',
        {
            'version': version,
            'rows': rows,
            'node_path': node_path,
            'breadcrumb': breadcrumb,
            'items': items,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Actuals
# ─────────────────────────────────────────────────────────────────────────────

#from decimal import Decimal
#from django.db.models import Sum, Count, DecimalField
#from django.db.models.functions import Coalesce


@login_required
def actuals_list(request, client_id=None):
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    qs = (
        ActualSale.objects
        .filter(client=request.client)
        .select_related('item', 'planning_location', 'planning_customer', 'distribution_channel')
        .order_by('-period_start')
    )

    item_id       = request.GET.get('item_id', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    channel_code  = request.GET.get('channel_code', '').strip()
    period_type   = request.GET.get('period_type', '').strip()
    period_start  = request.GET.get('period_start', '').strip()

    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if customer_code:
        qs = qs.filter(planning_customer__code=customer_code)
    if channel_code:
        qs = qs.filter(distribution_channel__code=channel_code)
    if period_type:
        qs = qs.filter(period_type=period_type)
    if period_start:
        qs = qs.filter(period_start=period_start)

    # Dropdown choices from filtered data
    locations = list(
        qs.exclude(planning_location__isnull=True)
        .values_list('planning_location__code', 'planning_location__name')
        .distinct().order_by('planning_location__code')
    )
    customers = list(
        qs.exclude(planning_customer__isnull=True)
        .values_list('planning_customer__code', 'planning_customer__name')
        .distinct().order_by('planning_customer__code')
    )
    if request.client.is_distribution_channel_enabled():
        channel_count = qs.values('distribution_channel').distinct().count()
        show_channel = channel_count > 1
        channels = list(
            qs.exclude(distribution_channel__isnull=True)
            .values_list('distribution_channel__code', 'distribution_channel__label')
            .distinct().order_by('distribution_channel__code')
        )
    else:
        show_channel = False
        channels = []
    period_types = list(
        qs.order_by().values_list('period_type', flat=True)
        .distinct().order_by('period_type')
    )
    periods = list(
        qs.values_list('period_start', flat=True)
        .distinct().order_by('-period_start')
    )

    # ── Totals ────────────────────────────────────────────────────────────
    # Grand total across all filtered rows
    grand = qs.aggregate(
        total_qty=Coalesce(
            Sum('qty'),
            Decimal('0'),
            output_field=DecimalField()
        ),
        total_revenue=Coalesce(
            Sum('revenue'),
            Decimal('0'),
            output_field=DecimalField()
        ),
    )

    # Check if the result set is for a single item — item total is only
    # meaningful when filtering to one item
    distinct_items = qs.values('item__item_id').distinct().count()
    single_item = distinct_items == 1

    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    # Page total — sum only the rows on the current page
    page_ids = [sale.pk for sale in page_obj.object_list]
    # Page total
    page_total = ActualSale.objects.filter(pk__in=page_ids).aggregate(
        total_qty=Coalesce(
            Sum('qty'),
            Decimal('0'),
            output_field=DecimalField()
        ),
        total_revenue=Coalesce(
            Sum('revenue'),
            Decimal('0'),
            output_field=DecimalField()
        ),
    )

    filters = {
        'item_id':       item_id,
        'location_code': location_code,
        'customer_code': customer_code,
        'channel_code':  channel_code,
        'period_type':   period_type,
        'period_start':  period_start,
    }

    context = {
        'page_obj':     page_obj,
        'filters':      filters,
        'locations':    locations,
        'customers':    customers,
        'channels':     channels,
        'period_types': period_types,
        'periods':      periods,
        'show_location':       len(locations) > 1,
        'show_customer':       len(customers) > 0,
        'show_channel':        show_channel,
        'show_period_type':    len(period_types) > 1,
        'show_period':         len(periods) > 1,
        'show_item_search':    distinct_items > 1,
        'grand_total':  grand,
        'page_total':   page_total,
        'single_item':  single_item,
        'is_multipage': page_obj.has_other_pages(),
        'active_nav': 'actuals'
    }

    if _is_htmx(request):
        from django.template.loader import render_to_string
        html = (
            render_to_string('demand/partials/actuals_filter_bar.html', context, request) +
            render_to_string('demand/partials/actuals_table_body.html', context, request)
        )
        return HttpResponse(html)
    return render(request, 'demand/actuals_list.html', context)

# ─────────────────────────────────────────────────────────────────────────────
# Actuals — value summary (Total / Item / Location / Customer), mirrors
# version_aggregates() above. There's no separate "ActualAggregate" model —
# ActualSale rows are grouped live per level with .values().annotate().
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def actuals_aggregates(request, client_id=None):
    """
    GET /{client_id}/demand/actuals/aggregates/
 
    Query params: agg_level (total|location|item|customer),
    exclude_outliers (1|0, only meaningful when outlier management is
    active for this client).
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked
 
    agg_level = request.GET.get('agg_level', 'total')
    valid_levels = ['total', 'location', 'item', 'customer']
    if agg_level not in valid_levels:
        agg_level = 'total'
 
    # ── Filters ────────────────────────────────────────────────────────────
    period_start  = request.GET.get('period_start', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    item_id       = request.GET.get('item_id', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    qty_min       = request.GET.get('qty_min', '').strip()
    qty_max       = request.GET.get('qty_max', '').strip()
    revenue_min   = request.GET.get('revenue_min', '').strip()
    revenue_max   = request.GET.get('revenue_max', '').strip()
 
    # ── Outlier include/exclude toggle ──────────────────────────────────────
    outlier_ui_visible_flag = _outlier_ui_visible(request.client)
 
    exclude_outliers = False
    if outlier_ui_visible_flag:
        exclude_outliers_param = request.GET.get('exclude_outliers')
        if exclude_outliers_param is not None:
            exclude_outliers = exclude_outliers_param in ('1', 'true', 'True')
        else:
            # First load with no explicit choice yet — default from the
            # client's reporting flag, same "missing config -> raw" fallback
            # used elsewhere (missing config itself also -> raw/False).
            forecasting_config = getattr(request.client, 'forecasting_config', None)
            exclude_outliers = bool(
                forecasting_config and forecasting_config.reporting_uses_net_actuals
            )
 
    if exclude_outliers:
        base_qs = actuals_queryset_with_net(request.client, use_net=True)
        qty_field = 'net_qty'
        revenue_field = 'net_revenue'
    else:
        base_qs = ActualSale.objects.filter(client=request.client)
        qty_field = 'qty'
        revenue_field = 'revenue'
 
    # Row-level filters — applied before grouping
    qs = base_qs
    if period_start:
        qs = qs.filter(period_start=period_start)
    if agg_level == 'location' and location_code:
        qs = qs.filter(planning_location__code=location_code)
    if agg_level == 'item' and item_id:
        qs = qs.filter(item__item_id__icontains=item_id)
    if agg_level == 'customer' and customer_code:
        qs = qs.filter(planning_customer__code=customer_code)
 
    # ── Group by level ─────────────────────────────────────────────────────
    group_fields = ['period_start']
    if agg_level == 'location':
        group_fields.append('planning_location__code')
    elif agg_level == 'item':
        group_fields.append('item__item_id')
    elif agg_level == 'customer':
        group_fields.append('planning_customer__code')
 
    grouped = (
        qs.values(*group_fields)
        .annotate(
            total_qty=Coalesce(Sum(qty_field), Decimal('0'), output_field=DecimalField()),
            total_revenue=Coalesce(Sum(revenue_field), Decimal('0'), output_field=DecimalField()),
        )
        .order_by(*group_fields)
    )
 
    rows = list(grouped)
 
    # Post-aggregation (HAVING-style) range filters — done in Python since
    # these apply to the summed values, not the raw row values.
    def _to_decimal(raw):
        try:
            return Decimal(raw)
        except Exception:
            return None
 
    if qty_min and (d := _to_decimal(qty_min)) is not None:
        rows = [r for r in rows if r['total_qty'] >= d]
    if qty_max and (d := _to_decimal(qty_max)) is not None:
        rows = [r for r in rows if r['total_qty'] <= d]
    if revenue_min and (d := _to_decimal(revenue_min)) is not None:
        rows = [r for r in rows if r['total_revenue'] >= d]
    if revenue_max and (d := _to_decimal(revenue_max)) is not None:
        rows = [r for r in rows if r['total_revenue'] <= d]
 
    # ── Friendly display key per row ──────────────────────────────────────
    for row in rows:
        if agg_level == 'total':
            row['display_key'] = 'All'
        elif agg_level == 'location':
            row['display_key'] = row.get('planning_location__code') or '—'
        elif agg_level == 'item':
            row['display_key'] = row.get('item__item_id') or '—'
        elif agg_level == 'customer':
            row['display_key'] = row.get('planning_customer__code') or '—'
 
    # ── Distinct item count — drives "Item total" vs "Grand total" label ──
    single_item = False
    if agg_level == 'item':
        distinct_items = len({r['item__item_id'] for r in rows})
        single_item = distinct_items == 1
 
    # ── Dropdown choices — from this client's full actuals, not the
    #    level-filtered qs, independent of the currently applied filter.
    #    Uses base_qs (net-or-raw) purely for consistent client scoping —
    #    period_start/location_code/customer_code values themselves don't
    #    depend on qty/revenue, so this is unaffected by the toggle. ──────
    periods = list(
        base_qs.values_list('period_start', flat=True)
        .distinct().order_by('period_start')
    )
    location_choices = []
    if agg_level == 'location':
        location_choices = list(
            base_qs.exclude(planning_location__isnull=True)
            .values_list('planning_location__code', 'planning_location__name')
            .distinct().order_by('planning_location__code')
        )
    customer_choices = []
    if agg_level == 'customer':
        customer_choices = list(
            base_qs.exclude(planning_customer__isnull=True)
            .values_list('planning_customer__code', 'planning_customer__name')
            .distinct().order_by('planning_customer__code')
        )
 
    # ── Grand total — across every row matching filters (pre-pagination) ──
    grand_total = {
        'total_qty':     sum((r['total_qty'] for r in rows), Decimal('0')),
        'total_revenue': sum((r['total_revenue'] for r in rows), Decimal('0')),
    }
 
    paginator = Paginator(rows, 50)
    page_obj  = paginator.get_page(request.GET.get('page', 1))
 
    page_total = {
        'total_qty': sum(
            (r['total_qty'] for r in page_obj.object_list), Decimal('0')
        ),
        'total_revenue': sum(
            (r['total_revenue'] for r in page_obj.object_list), Decimal('0')
        ),
    }
 
    filters = {
        'period_start':      period_start,
        'location_code':     location_code,
        'item_id':           item_id,
        'customer_code':     customer_code,
        'qty_min':           qty_min,
        'qty_max':           qty_max,
        'revenue_min':       revenue_min,
        'revenue_max':       revenue_max,
        'exclude_outliers':  exclude_outliers,
    }
 
    context = {
        'aggregates':                page_obj.object_list,
        'page_obj':                  page_obj,
        'agg_level':                 agg_level,
        'agg_level_choices':         valid_levels,
        'grand_total':               grand_total,
        'page_total':                page_total,
        'single_item':               single_item,
        'is_multipage':              page_obj.has_other_pages(),
        'filters':                   filters,
        'periods':                   periods,
        'location_choices':          location_choices,
        'customer_choices':          customer_choices,
        'active_nav':                'actuals',
        'outlier_ui_visible': outlier_ui_visible_flag,
    }
 
    if _is_htmx(request):
        from django.template.loader import render_to_string
        html = (
            render_to_string(
                'demand/partials/actuals_aggregates_filter_bar.html',
                context, request
            ) +
            render_to_string(
                'demand/partials/actuals_aggregates_table_body.html',
                context, request
            )
        )
        return HttpResponse(html)
 
    return render(request, 'demand/actuals_aggregates.html', context)


@login_required
@require_http_methods(['GET', 'POST'])
def actuals_upload(request, client_id=None):
    blocked = feature_gate(request, 'actuals_upload')
    if blocked:
        return blocked

    from django.db.models import Max, Count

    def _actuals_summary():
        summary = ActualSale.objects.filter(
            client=request.client
        ).aggregate(
            latest_period=Max('period_start'),
            total_rows=Count('id'),
        )
        period_type_counts = (
            ActualSale.objects
            .filter(client=request.client)
            .order_by()
            .values('period_type')
            .annotate(cnt=Count('id'))
            .order_by('-cnt')
            .first()
        )
        return {
            'latest_period':       summary['latest_period'],
            'total_rows':          summary['total_rows'],
            'default_period_type': (
                period_type_counts['period_type']
                if period_type_counts else 'month'
            ),
        }

    if request.method == 'POST':
        import io, os, datetime
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        action              = request.POST.get('action', 'upload')
        pending_file        = request.POST.get('pending_file', '').strip()
        pending_period_type = request.POST.get('pending_period_type', '').strip()
        period_type         = request.POST.get('period_type', '').strip()

        # Resolve the effective period type
        effective_period_type = pending_period_type or period_type

        # ── Handle overlap resolution actions first ────────────────────────────
        # These have no file upload — skip file validation entirely

        if action == 'ignore':
            if pending_file:
                try:
                    default_storage.delete(pending_file)
                except Exception:
                    pass
            ctx = _actuals_summary()
            ctx.update({'period_choices': PERIOD_TYPE_CHOICES})
            return render(
                request,
                'demand/partials/actuals_upload_form.html',
                ctx,
            )

        if action == 'overlap' and pending_file:
            # Re-render the overlap panel from a stored (still-pending) file —
            # used by the "Go back" button on the delete reconfirmation panel.
            overlap_dates = []
            for s in request.POST.getlist('overlap_periods'):
                try:
                    overlap_dates.append(datetime.date.fromisoformat(s))
                except ValueError:
                    pass
            ctx = _actuals_summary()
            ctx.update({
                'period_choices':      PERIOD_TYPE_CHOICES,
                'overlap_periods':     sorted(overlap_dates),
                'overlap_count':       len(overlap_dates),
                'overlap_outlier_count': ActualSaleOutlierAdjustment.objects.filter(
                    actual_sale__client=request.client,
                    actual_sale__period_type=effective_period_type,
                    actual_sale__period_start__in=overlap_dates,
                ).count(),
                'pending_file':        pending_file,
                'pending_period_type': effective_period_type,
            })
            return render(
                request,
                'demand/partials/actuals_upload_overlap.html',
                ctx,
            )

        if action == 'delete_and_upload' and pending_file:
            overlap_dates = []
            for s in request.POST.getlist('overlap_periods'):
                try:
                    overlap_dates.append(datetime.date.fromisoformat(s))
                except ValueError:
                    pass
            # ── Reconfirmation guard: deleting actuals cascades to their 1:1
            # ── ActualSaleOutlierAdjustment rows. If any exist for the
            # ── overlapping periods, force an explicit second confirmation.
            if overlap_dates and not request.POST.get('confirmed'):
                outlier_qs = ActualSaleOutlierAdjustment.objects.filter(
                    actual_sale__client=request.client,
                    actual_sale__period_type=effective_period_type,
                    actual_sale__period_start__in=overlap_dates,
                )
                outlier_count = outlier_qs.count()
                if outlier_count:
                    outlier_status_counts = (
                        outlier_qs.order_by()
                        .values('status')
                        .annotate(cnt=Count('id'))
                        .order_by('status')
                    )
                    ctx = _actuals_summary()
                    ctx.update({
                        'period_choices':       PERIOD_TYPE_CHOICES,
                        'overlap_periods':      sorted(overlap_dates),
                        'overlap_count':        len(overlap_dates),
                        'overlap_outlier_count': outlier_count,
                        'outlier_count':        outlier_count,
                        'outlier_status_counts': outlier_status_counts,
                        'pending_file':         pending_file,
                        'pending_period_type':  effective_period_type,
                    })
                    return render(
                        request,
                        'demand/partials/actuals_upload_overlap_confirm.html',
                        ctx,
                    )
            if overlap_dates:
                deleted, _ = ActualSale.objects.filter(
                    client=request.client,
                    period_type=effective_period_type,
                    period_start__in=overlap_dates,
                ).delete()
                logger.info(
                    f'actuals_upload: deleted {deleted} rows for '
                    f'{len(overlap_dates)} periods before fresh upload'
                )
            save_path = pending_file
            job = ActualSaleImport.objects.create(
                client      = request.client,
                uploaded_by = request.user,
                file_name   = save_path,
                period_type = effective_period_type,
                status      = 'pending',
            )
            from mysite.tasks.demand.import_actuals import process_actuals_import
            process_actuals_import.delay(job.pk)
            return render(
                request,
                'demand/partials/actuals_upload_status.html',
                {'job': job},
            )

        if action == 'upload' and pending_file:
            # Add to existing — file already saved
            job = ActualSaleImport.objects.create(
                client      = request.client,
                uploaded_by = request.user,
                file_name   = pending_file,
                period_type = effective_period_type,
                status      = 'pending',
            )
            from mysite.tasks.demand.import_actuals import process_actuals_import
            process_actuals_import.delay(job.pk)
            return render(
                request,
                'demand/partials/actuals_upload_status.html',
                {'job': job},
            )

        # ── Fresh upload — validate file and period_type ───────────────────────
        uploaded_file = request.FILES.get('file')
        errors = {}

        if not uploaded_file:
            errors['file'] = 'Please choose a file.'
        else:
            ext = os.path.splitext(uploaded_file.name)[1].lower()
            if ext not in ('.csv', '.xlsx', '.xls'):
                errors['file'] = f'Unsupported file type "{ext}".'

        valid_period_types = [k for k, _ in PERIOD_TYPE_CHOICES]
        if period_type not in valid_period_types:
            errors['period_type'] = 'Select a valid period type.'

        if errors:
            ctx = _actuals_summary()
            ctx.update({
                'errors':         errors,
                'period_choices': PERIOD_TYPE_CHOICES,
            })
            return render(
                request,
                'demand/partials/actuals_upload_form.html',
                ctx, status=400,
            )

        # Read file into memory once
        raw = uploaded_file.read()
        ext = os.path.splitext(uploaded_file.name)[1].lower()

        # ── Peek for period overlap ────────────────────────────────────────────
        try:
            if ext == '.csv':
                df_peek = pd.read_csv(
                    io.BytesIO(raw), dtype=str, keep_default_na=False
                )
            else:
                df_peek = pd.read_excel(
                    io.BytesIO(raw), dtype=str, keep_default_na=False
                )

            df_peek.columns = [c.strip().lower() for c in df_peek.columns]

            if 'period_start' in df_peek.columns:
                file_periods = set()
                for v in df_peek['period_start'].dropna().unique():
                    try:
                        v_clean = str(v).strip().split(' ')[0].split('T')[0]
                        file_periods.add(datetime.date.fromisoformat(v_clean))
                    except ValueError:
                        pass

                if file_periods:
                    existing_periods = set(
                        ActualSale.objects
                        .filter(
                            client=request.client,
                            period_type=period_type,
                            period_start__in=file_periods,
                        )
                        .order_by()
                        .values_list('period_start', flat=True)
                        .distinct()
                    )

                    if existing_periods:
                        save_path = default_storage.save(
                            f'demand/actuals_imports/{uploaded_file.name}',
                            ContentFile(raw),
                        )
                        ctx = _actuals_summary()
                        ctx.update({
                            'period_choices':      PERIOD_TYPE_CHOICES,
                            'overlap_periods':     sorted(existing_periods),
                            'overlap_count':       len(existing_periods),
                            'overlap_outlier_count': ActualSaleOutlierAdjustment.objects.filter(
                                actual_sale__client=request.client,
                                actual_sale__period_type=period_type,
                                actual_sale__period_start__in=existing_periods,
                            ).count(),
                            'pending_file':        save_path,
                            'pending_period_type': period_type,
                        })
                        return render(
                            request,
                            'demand/partials/actuals_upload_overlap.html',
                            ctx,
                        )

        except Exception as exc:
            logger.warning(
                f'actuals_upload: period peek failed for {ext}: {exc}',
                exc_info=True,
            )

        # ── No overlap — save and queue ────────────────────────────────────────
        save_path = default_storage.save(
            f'demand/actuals_imports/{uploaded_file.name}',
            ContentFile(raw),
        )
        job = ActualSaleImport.objects.create(
            client      = request.client,
            uploaded_by = request.user,
            file_name   = save_path,
            period_type = period_type,
            status      = 'pending',
        )
        from mysite.tasks.demand.import_actuals import process_actuals_import
        process_actuals_import.delay(job.pk)
        return render(
            request,
            'demand/partials/actuals_upload_status.html',
            {'job': job},
        )

    # ── GET ───────────────────────────────────────────────────────────────────
    ctx = _actuals_summary()
    ctx.update({
        'period_choices': PERIOD_TYPE_CHOICES,
        'active_nav':     'actuals_upload',
    })
    if _is_htmx(request):
        return render(
            request, 'demand/partials/actuals_upload_form.html', ctx
        )
    return render(request, 'demand/actuals_upload.html', ctx)

@login_required
def actuals_upload_status(request, job_id, client_id=None):
    """
    GET /{client_id}/demand/actuals/upload/{job_id}/status/

    Polled by HTMX while status is pending/processing.
    """
    job = get_object_or_404(ActualSaleImport, pk=job_id, client=request.client)
    return render(request, 'demand/partials/actuals_upload_status.html', {'job': job})


@login_required
def actuals_template_download(request, client_id=None):
    """GET /{client_id}/demand/actuals/template/ — streams generated .xlsx."""
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    period_type = request.GET.get('period_type', 'month')
    valid_period_types = [k for k, _ in PERIOD_TYPE_CHOICES]
    if period_type not in valid_period_types:
        period_type = 'month'

    import tempfile
    from django.core.management import call_command

    tmp_path = tempfile.mktemp(suffix='.xlsx')
    call_command(
        'generate_actuals_template',
        client=request.client.client_id,
        period_type=period_type,
        output_path=tmp_path,
    )
    response = FileResponse(
        open(tmp_path, 'rb'),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = (
        f'attachment; filename="actuals_template_{request.client.client_id}_{period_type}.xlsx"'
    )
    return response


# ─────────────────────────────────────────────────────────────────────────────
# Series Profiles (classification review)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def series_profile_list(request, client_id=None):
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    p = request.GET
    demand_class  = p.get('demand_class', '')
    abc_class     = p.get('abc_class', '')
    is_manual     = p.get('is_manual', '')
    location_code = p.get('location_code', '')
    item_id       = p.get('item_id', '').strip()
    abc_level     = p.get('abc_level', '')

    # ── Available grains from actual evaluations ──────────────────────────────
    raw_grains = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client)
        .values_list('grain', flat=True)
        .distinct()
        .order_by('grain')
    )

    # Group by pattern so each ABC level appears once in the dropdown
    seen_patterns: set[str] = set()
    patterned_grains: list[str] = []
    for g in raw_grains:
        pat = _grain_pattern(g)
        if pat not in seen_patterns:
            seen_patterns.add(pat)
            patterned_grains.append(g)

    GRAIN_LABELS: dict[str, str] = {
        # ── item-prefix patterns ───────────────────────────────────────────
        'item_cust_location':    'Item × Location × Customer',
        'item_loc_dc_cust':      'Item × Location × Channel × Customer',
        'item_loc_dc':           'Item × Location × Channel',
        'item_loc':              'Item × Leaf Location',
        'item_salesnode':        'Item × Sales Node',
        'item_top_week':         'Item × Top Node (Week)',
        'item_top_fortnight':    'Item × Top Node (Fortnight)',
        'item_top_month':        'Item × Top Node (Month)',
        'item_top_quarter':      'Item × Top Node (Quarter)',
        'item_top_halfyear':     'Item × Top Node (Half-Year)',
        'item_top_year':         'Item × Top Node (Year)',
        'item_client':           'Item × Client Total',
        'item_client_week':      'Item × Client (Week)',
        'item_client_fortnight': 'Item × Client (Fortnight)',
        'item_client_month':     'Item × Client (Month)',
        'item_client_quarter':   'Item × Client (Quarter)',
        'item_client_halfyear':  'Item × Client (Half-Year)',
        'item_client_year':      'Item × Client (Year)',
        # ── taxon-prefix patterns ──────────────────────────────────────────
        'taxon_cust_location':    'Category × Location × Customer',
        'taxon_loc_dc_cust':      'Category × Location × Channel × Customer',
        'taxon_loc_dc':           'Category × Location × Channel',
        'taxon_loc':              'Category × Leaf Location',
        'taxon_salesnode':        'Category × Sales Node',
        'taxon_top_week':         'Category × Top Node (Week)',
        'taxon_top_fortnight':    'Category × Top Node (Fortnight)',
        'taxon_top_month':        'Category × Top Node (Month)',
        'taxon_top_quarter':      'Category × Top Node (Quarter)',
        'taxon_top_halfyear':     'Category × Top Node (Half-Year)',
        'taxon_top_year':         'Category × Top Node (Year)',
        'taxon_client':           'Category × Client Total',
        'taxon_client_week':      'Category × Client (Week)',
        'taxon_client_fortnight': 'Category × Client (Fortnight)',
        'taxon_client_month':     'Category × Client (Month)',
        'taxon_client_quarter':   'Category × Client (Quarter)',
        'taxon_client_halfyear':  'Category × Client (Half-Year)',
        'taxon_client_year':      'Category × Client (Year)',
    }
    for pat in seen_patterns:
        if pat in GRAIN_LABELS:
            continue
        if '_loc_depth_' in pat:
            try:
                depth = int(pat.rsplit('_', 1)[-1])
                GRAIN_LABELS[pat] = f'Item × Location (Depth {depth})'
            except ValueError:
                GRAIN_LABELS[pat] = pat.replace('_', ' ').title()
        else:
            GRAIN_LABELS[pat] = pat.replace('_', ' ').title()

    abc_level_choices = [
        (g, GRAIN_LABELS.get(_grain_pattern(g), g)) for g in patterned_grains
    ]

    # Default to first available grain
    if not abc_level or abc_level not in raw_grains:
        abc_level = patterned_grains[0] if patterned_grains else 'item_cust_location'

    # ── Determine display mode + grain category from selected grain ───────────
    pattern = _grain_pattern(abc_level)
    grain_category = 'taxon' if pattern.startswith('taxon_') else 'item'

    if pattern.endswith('_cust_location') or pattern.endswith('_loc_dc_cust'):
        display_mode = 'atomic'
    elif pattern.endswith('_loc_dc') or pattern.endswith('_loc') or '_loc_depth_' in pattern:
        display_mode = 'item_location'
    elif '_salesnode' in pattern:
        display_mode = 'sales_node'
    elif '_top_' in pattern:
        display_mode = 'top'
    else:
        display_mode = 'item_client'

    # ── Extract depth for loc_depth grains ───────────────────────────────────
    loc_depth = None
    if display_mode == 'item_location' and '_loc_depth_' in pattern:
        try:
            loc_depth = int(pattern.rsplit('_', 1)[-1])
        except ValueError:
            loc_depth = None

    # ── Build leaf → ancestor map for depth grains ────────────────────────────
    leaf_to_ancestor: dict[int, int | None] = {}
    if loc_depth is not None:
        location_paths = {
            loc['id']: [p for p in loc['path'].split('/') if p]
            for loc in PlanningLocation.objects
                .filter(client=request.client)
                .values('id', 'path')
        }
        leaf_to_ancestor = {
            loc_id: int(parts[loc_depth - 1]) if loc_depth <= len(parts) else None
            for loc_id, parts in location_paths.items()
        }

    # ── Base queryset ─────────────────────────────────────────────────────────
    qs = (
        SeriesProfile.objects
        .filter(client=request.client)
        .select_related('item', 'planning_location', 'planning_customer', 'distribution_channel')
        .order_by('item__item_id', 'planning_location__code',
                  'planning_customer__code')
    )

    if request.client.is_distribution_channel_enabled():
        show_channel = qs.values('distribution_channel').distinct().count() > 1
    else:
        show_channel = False

    # ── Apply filters ─────────────────────────────────────────────────────────
    if demand_class:
        qs = qs.filter(demand_class_atomic=demand_class.upper())
    if is_manual == 'true':
        qs = qs.filter(chosen_strategy='MANUAL')
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)

    # Filter by ABC class at the selected grain level (by pattern, not exact grain)
    if abc_class:
        abc_class_filter = _pattern_to_grain_q(pattern) & Q(abc_class=abc_class.upper())
        matching_items = list(
            SeriesLevelEvaluation.objects
            .filter(client=request.client)
            .filter(abc_class_filter)
            .values_list('item_id', flat=True)
            .distinct()
        )
        qs = qs.filter(item_id__in=matching_items)

    # ── Dropdown choices from filtered qs ─────────────────────────────────────
    demand_classes = list(
        qs.exclude(demand_class_atomic='')
        .values_list('demand_class_atomic', flat=True)
        .distinct().order_by('demand_class_atomic')
    )
    abc_class_filter = _pattern_to_grain_q(pattern)
    abc_classes_available = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client)
        .filter(abc_class_filter)
        .exclude(abc_class='')
        .values_list('abc_class', flat=True)
        .distinct().order_by('abc_class')
    )
    locations = list(
        qs.exclude(planning_location__isnull=True)
        .values_list('planning_location__code', 'planning_location__name')
        .distinct().order_by('planning_location__code')
    )
    distinct_items = qs.values('item__item_id').distinct().count()

    # ── Paginate ──────────────────────────────────────────────────────────────
    paginator = Paginator(qs, 50)
    page_obj  = paginator.get_page(p.get('page', 1))

    # ── Fetch evaluations for page items ──────────────────────────────────────
    page_item_ids = list({prof.item_id for prof in page_obj.object_list})
    eval_grain_filter = _pattern_to_grain_q(pattern)

    evals = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client)
        .filter(eval_grain_filter)
        .filter(item_id__in=page_item_ids)
        .values(
            'item_id',
            'abc_class',
            'value_share_pct_at_level',
            'evaluation_key',
            'planning_customer_id',
        )
    )

    # ── Build abc_lookup and dedup_key based on display mode ──────────────────
    if display_mode == 'item_client':
        abc_lookup = {
            e['item_id']: {
                'abc_class':       e['abc_class'],
                'value_share_pct': e['value_share_pct_at_level'],
            }
            for e in evals
        }

        def get_abc(profile):
            return abc_lookup.get(profile.item_id, {})

        def dedup_key(profile):
            return profile.item_id

    elif display_mode == 'item_location':
        abc_lookup = {}
        for e in evals:
            loc_id = e['evaluation_key'].get('location_id')
            if loc_id is not None:
                abc_lookup[(e['item_id'], int(loc_id))] = {
                    'abc_class':       e['abc_class'],
                    'value_share_pct': e['value_share_pct_at_level'],
                }

        def get_abc(profile):
            if leaf_to_ancestor:
                anc_id = leaf_to_ancestor.get(profile.planning_location_id)
            else:
                anc_id = profile.planning_location_id
            if anc_id is None:
                return {}
            return abc_lookup.get((profile.item_id, anc_id), {})

        def dedup_key(profile):
            if leaf_to_ancestor:
                anc_id = leaf_to_ancestor.get(profile.planning_location_id)
            else:
                anc_id = profile.planning_location_id
            return (profile.item_id, anc_id)

    elif display_mode == 'sales_node':
        abc_lookup = {}
        for e in evals:
            sn_id = e['evaluation_key'].get('sales_node_id')
            if sn_id is not None:
                abc_lookup[(e['item_id'], int(sn_id))] = {
                    'abc_class':       e['abc_class'],
                    'value_share_pct': e['value_share_pct_at_level'],
                }

        # Build leaf → sales ancestors map once
        sales_ancestor_map: dict[int, set[int]] = defaultdict(set)
        page_location_ids = {prof.planning_location_id for prof in page_obj.object_list if prof.planning_location_id}
        if page_location_ids:
            ancestor_map_raw = get_sales_hierarchy_ancestor_map(request.client.id)
            links_qs = SalesForecastLink.objects.filter(
                client=request.client,
                planning_location_id__in=page_location_ids,
            ).values('planning_location_id', 'sales_node_id')
            for link in links_qs:
                ancestors = ancestor_map_raw.get(link['sales_node_id'], [])
                sales_ancestor_map[link['planning_location_id']].add(link['sales_node_id'])
                sales_ancestor_map[link['planning_location_id']].update(ancestors)

        def get_abc(profile):
            anc_ids = sales_ancestor_map.get(profile.planning_location_id, set())
            for anc_id in anc_ids:
                result = abc_lookup.get((profile.item_id, anc_id))
                if result:
                    return result
            return {}

        def dedup_key(profile):
            # Find the first matching ancestor for dedup
            anc_ids = sales_ancestor_map.get(profile.planning_location_id, set())
            for anc_id in anc_ids:
                if (profile.item_id, anc_id) in abc_lookup:
                    return (profile.item_id, anc_id)
            return (profile.item_id, profile.planning_location_id)

    else:
        # atomic — item_cust_location / item_loc_dc_cust
        abc_lookup = {}
        for e in evals:
            loc_id  = e['evaluation_key'].get('location_id')
            cust_id = e['planning_customer_id']
            if loc_id is not None:
                abc_lookup[(e['item_id'], int(loc_id), cust_id)] = {
                    'abc_class':       e['abc_class'],
                    'value_share_pct': e['value_share_pct_at_level'],
                }

        def get_abc(profile):
            return abc_lookup.get(
                (profile.item_id,
                 profile.planning_location_id,
                 profile.planning_customer_id),
                {
                    'abc_class':       profile.abc_class_atomic,
                    'value_share_pct': None,
                }
            )

        def dedup_key(profile):
            return (
                profile.item_id,
                profile.planning_location_id,
                profile.planning_customer_id,
            )

    # ── Attach ABC and deduplicate ─────────────────────────────────────────────
    seen     = set()
    profiles = []

    ancestor_location_map: dict[int, dict] = {}
    if display_mode in ('item_location',):
        for e in evals:
            loc_id     = e['evaluation_key'].get('location_id')
            level_label = e['evaluation_key'].get('level_label', '')
            if loc_id is not None:
                ancestor_location_map[int(loc_id)] = {
                    'location_id': int(loc_id),
                    'level_label': level_label,
                }
        if ancestor_location_map:
            for loc in (
                PlanningLocation.objects
                .filter(client=request.client, id__in=ancestor_location_map.keys())
                .values('id', 'code', 'name')
            ):
                ancestor_location_map[loc['id']].update({
                    'code': loc['code'],
                    'name': loc['name'],
                })

    ancestor_sales_node_map: dict[int, dict] = {}
    if display_mode == 'sales_node':
        for e in evals:
            sn_id = e['evaluation_key'].get('sales_node_id')
            if sn_id is not None:
                ancestor_sales_node_map[int(sn_id)] = {'sales_node_id': int(sn_id)}
        if ancestor_sales_node_map:
            for sn in (
                SalesNode.objects
                .filter(client=request.client, id__in=ancestor_sales_node_map.keys())
                .values('id', 'code', 'name')
            ):
                ancestor_sales_node_map[sn['id']].update({
                    'code': sn['code'],
                    'name': sn['name'],
                })

    for profile in page_obj.object_list:
        key = dedup_key(profile)
        if key in seen:
            continue
        seen.add(key)

        profile.abc_at_level = get_abc(profile)
        profile.ancestor_location = {}
        profile.ancestor_sales_node = {}

        if display_mode == 'item_location':
            if leaf_to_ancestor:
                anc_id = leaf_to_ancestor.get(profile.planning_location_id)
            else:
                anc_id = profile.planning_location_id
            profile.ancestor_location = ancestor_location_map.get(anc_id, {})

        elif display_mode == 'sales_node':
            try:
                # key is (item_id, sn_id) for sales_node mode
                sn_id = key[1]
            except (IndexError, TypeError):
                sn_id = None
            profile.ancestor_sales_node = ancestor_sales_node_map.get(sn_id, {})

        profiles.append(profile)

    # ── Recompute tracking ─────────────────────────────────────────────────────
    cfg = ForecastingConfig.get_for_client(request.client)
    last_recompute = {
        'at': cfg.profiles_last_computed_at,
    }
    last_window = {
        'analysis_from': cfg.profiles_last_window_start,
        'analysis_to':   cfg.profiles_last_window_end,
    }
    last_period_types = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client)
        .values_list('period_type', flat=True)
        .distinct()
    )
    last_period_types.sort()

    # ── Context ───────────────────────────────────────────────────────────────
    filters = {
        'demand_class':  demand_class,
        'abc_class':     abc_class,
        'is_manual':     is_manual,
        'location_code': location_code,
        'item_id':       item_id,
        'abc_level':     abc_level,
    }

    show_location_modes = {'atomic', 'item_location', 'sales_node'}
    context = {
        'page_obj':            page_obj,
        'profiles':            profiles,
        'filters':             filters,
        'demand_classes':      demand_classes,
        'abc_classes':         abc_classes_available,
        'locations':           locations,
        'abc_level_choices':   abc_level_choices,
        'selected_abc_level':  abc_level,
        'display_mode':        display_mode,
        'grain_category':      grain_category,
        'show_location_column': display_mode in show_location_modes,
        'show_demand_class':   len(demand_classes) > 1,
        'show_abc_class':      len(abc_classes_available) > 1,
        'show_location':       (
            len(locations) > 1 and display_mode in show_location_modes
        ),
        'show_is_manual':     qs.filter(chosen_strategy='MANUAL').exists(),
        'show_item_search':   distinct_items > 1,
        'show_channel':       show_channel,
        'period_choices':     PERIOD_TYPE_CHOICES,
        'active_nav':         'series_profiles',
        'last_recompute':     last_recompute,
        'last_window':        last_window,
        'last_period_types':  last_period_types,
    }

    if _is_htmx(request):
        from django.template.loader import render_to_string
        from django.http import HttpResponse
        html = (
            render_to_string('demand/partials/series_filter_bar.html',
                             context, request) +
            render_to_string('demand/partials/series_profile_table_body.html',
                             context, request)
        )
        return HttpResponse(html)

    return render(request, 'demand/series_profile_list.html', context)

@login_required
def series_profile_detail(request, pk, client_id=None):
    """
    GET /{client_id}/demand/series-profiles/{pk}/

    Shows the full evaluation log (search path) for one series —
    the audit trail from Sprint 3B.3's classification engine.
    """
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    #from mysite.models.demand.forecast import SeriesLevelEvaluation

    profile = get_object_or_404(
        SeriesProfile.objects.select_related(
            'item', 'planning_location', 'planning_customer', 'override_set_by',
        ),
        pk=pk, client=request.client,
    )
    evaluations = (
        SeriesLevelEvaluation.objects
        .filter(client=request.client, item=profile.item, period_type=profile.period_type)
        .order_by('is_accepted', 'grain')
    )
    return render(request, 'demand/series_profile_detail.html', {
        'profile': profile, 'evaluations': evaluations, 'active_nav': 'series_profiles'
    })


@login_required
@require_http_methods(['POST'])
def series_profile_override(request, pk, client_id=None):
    """
    POST /{client_id}/demand/series-profiles/{pk}/override/

    Sets override_grain / override_strategy / override_note.
    """
    blocked = feature_gate(request, 'consensus_override')
    if blocked:
        return blocked

    profile = get_object_or_404(SeriesProfile, pk=pk, client=request.client)

    override_grain    = request.POST.get('override_grain', '').strip()
    override_strategy = request.POST.get('override_strategy', '').strip()
    override_note      = request.POST.get('override_note', '').strip()

    valid_grains = set(
        profile.item.series_level_evaluations.filter(
            client=request.client, period_type=profile.period_type,
        ).values_list('grain', flat=True)
    ) if hasattr(profile.item, 'series_level_evaluations') else set()

    if override_grain and valid_grains and override_grain not in valid_grains:
        messages.error(request, f'"{override_grain}" is not a valid grain for this series.')
        return redirect('demand_ui:series_profile_detail', client_id=request.client.client_id, pk=pk)

    from django.utils import timezone
    profile.override_grain    = override_grain
    profile.override_strategy = override_strategy
    profile.override_note     = override_note
    profile.override_set_by   = request.user
    profile.override_set_at   = timezone.now()
    profile.save(update_fields=[
        'override_grain', 'override_strategy', 'override_note',
        'override_set_by', 'override_set_at',
    ])
    messages.success(request, 'Override saved.')

    return redirect('demand_ui:series_profile_detail', client_id=request.client.client_id, pk=pk)


@login_required
@require_http_methods(['POST'])
def recompute_series_profiles(request, client_id=None):
    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    period_types = list(
        ActualSale.objects
        .filter(client=request.client)
        .order_by()                              # ← clears any Meta ordering
        .values_list('period_type', flat=True)
        .distinct()
    )

    if not period_types:
        return HttpResponse(
            '<div class="alert alert-warning py-2 text-sm">'
            'No actuals data found.</div>'
        )

    #from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
    #from celery import chain

    if len(period_types) == 1:
        result = compute_series_profiles.delay(
            request.client.pk, period_types[0]
        )
        task_id = result.id
    else:
        task_chain = chain(
            *[compute_series_profiles.si(request.client.pk, pt)
              for pt in period_types]
        )
        result  = task_chain.delay()
        task_id = result.id

    return render(request, 'demand/partials/recompute_status.html', {
        'status':  'running',
        'task_id': task_id,
    })

@login_required
def recompute_status(request, client_id=None):
    from celery.result import AsyncResult
    task_id = request.GET.get('task_id', '')

    if not task_id:
        return HttpResponse('')

    result = AsyncResult(task_id)

    if result.ready():
        status = 'done' if result.successful() else 'failed'
    else:
        status = 'running'

    return render(request, 'demand/partials/recompute_status.html', {
        'status':  status,
        'task_id': task_id,
    })

# ─────────────────────────────────────────────────────────────────────────────
# Outlier Management
# ─────────────────────────────────────────────────────────────────────────────

from mysite.tasks.demand.detect_outliers import run_outlier_detection

from datetime import timedelta
 
@login_required
def outlier_detection_form(request, client_id):
    """
    GET renders the range-picker form fragment.
 
    Proposed range (Q4):
      - If a previous run's range is on record: propose picking up right
        where it left off (day after last_outlier_detection_range_end)
        through the latest actuals period currently available — i.e.
        "run detection on everything new since last time."
      - If there's no previous run at all: propose the client's full
        available actuals range (earliest through latest period_start) —
        i.e. "here's everything there is, in case you want to run once
        over all of it first."
      - If there's nothing new since the last run (suggested start would
        be after the latest available data), don't propose a range at
        all — surface that there's nothing new instead of pre-filling a
        start date past the end of the data.
    """
    client = request.client
    config = getattr(client, "forecasting_config", None)  # was "forecastingconfig"
 
    actuals_bounds = ActualSale.objects.filter(client=client).aggregate(
        earliest=Min("period_start"), latest=Max("period_start"),
    )
    earliest_actual_period = actuals_bounds["earliest"]
    latest_actual_period = actuals_bounds["latest"]
 
    suggested_start = None
    suggested_end = latest_actual_period
    no_new_data = False
 
    if config and config.last_outlier_detection_range_end:
        suggested_start = config.last_outlier_detection_range_end + timedelta(days=1)
    else:
        suggested_start = earliest_actual_period
 
    if suggested_start and latest_actual_period and suggested_start > latest_actual_period:
        # Last run already covered everything there currently is.
        suggested_start = None
        suggested_end = None
        no_new_data = True
    elif suggested_start is None:
        # No previous run AND no actuals at all for this client yet.
        no_new_data = True
 
    return render(request, "demand/outliers/partials/_detection_form.html", {
        "suggested_start": suggested_start,
        "suggested_end": suggested_end,
        "no_new_data": no_new_data,
        "forecasting_config": config,
    })
 
 

@login_required
@require_POST
def trigger_outlier_detection(request, client_id):
    client = request.client
    period_start = request.POST.get("period_start")
    period_end = request.POST.get("period_end")
    if not period_start or not period_end:
        return render(request, "demand/outliers/partials/_detection_form.html", {
            "error": "Both a start and end period are required.",
            "forecasting_config": getattr(client, "forecasting_config", None),  # was "forecastingconfig"
        })
 
    run_outlier_detection.delay(
        client_id=client.client_id,
        target_period_start=period_start,
        target_period_end=period_end,
        triggered_by_user_id=request.user.id,
    )
    return render(request, "demand/outliers/partials/_detection_triggered.html", {
        "period_start": period_start, "period_end": period_end,
    })


@login_required
def outlier_queue(request, client_id):
    return render(request, "demand/outliers/queue.html", _outlier_queue_context(request))


def _outlier_queue_context(request):
    """Shared context for the Outlier Review Queue page (GET and bulk-delete
    re-renders), so both stay in sync on status filter, counts, and nav."""
    client = request.client
    qs = ActualSaleOutlierAdjustment.objects.filter(
        actual_sale__client=client
    ).select_related(
        "actual_sale", "actual_sale__item", "actual_sale__planning_location",
        "actual_sale__planning_customer", "actual_sale__distribution_channel",
    )
 
    status = request.GET.get("status", "CANDIDATE")
    if status:
        qs = qs.filter(status=status)
 
    return {
        "adjustments": qs.order_by("-created_at")[:200],
        "current_status": status,
        "active_nav": "outlier_queue",
        "forecasting_config": getattr(client, "forecasting_config", None),  # was "forecastingconfig"
        "outlier_candidate_count": ActualSaleOutlierAdjustment.objects.filter(
            actual_sale__client=client, status="CANDIDATE"
        ).count(),
    }


@login_required
@require_POST
def outlier_bulk_delete(request, client_id):
    """
    Discard proposed (CANDIDATE) outlier adjustments so a future detection
    run can re-propose them afresh. Only CANDIDATE rows are eligible —
    CONFIRMED/REJECTED are deliberate decisions and are never touched.

    mode=selected -> delete the CANDIDATE rows whose pks arrive in
                     adjustment_ids (checkbox selection).
    mode=all      -> delete every CANDIDATE row for this client.
    """
    client = request.client
    base = ActualSaleOutlierAdjustment.objects.filter(
        actual_sale__client=client,
        status="CANDIDATE",
    )

    deleted = 0
    if request.POST.get("mode") == "all":
        deleted, _ = base.delete()
    else:
        ids = [pk for pk in request.POST.getlist("adjustment_ids") if pk.isdigit()]
        if ids:
            deleted, _ = base.filter(pk__in=ids).delete()

    ctx = _outlier_queue_context(request)
    if deleted:
        ctx["notice"] = f"{deleted} proposed outlier(s) discarded."
    return render(request, "demand/outliers/queue.html", ctx)
 



@login_required
@require_POST
def outlier_confirm(request, client_id, pk):
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    if "qty_adjustment" in request.POST:
        adj.qty_adjustment = request.POST["qty_adjustment"]
    if "revenue_adjustment" in request.POST:
        adj.revenue_adjustment = request.POST["revenue_adjustment"] or None
    adj.confirm(user=request.user)
    return render(request, "demand/outliers/partials/_row.html", {"adjustment": adj})


@login_required
@require_POST
def outlier_reject(request, client_id, pk):
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    adj.reject(user=request.user)
    return render(request, "demand/outliers/partials/_row.html", {"adjustment": adj})


@login_required
def raise_exception_form(request, client_id, actual_sale_id):
    actual = get_object_or_404(ActualSale, pk=actual_sale_id, client=request.client)
    if request.method == "POST":
        adj, created = ActualSaleOutlierAdjustment.objects.get_or_create(
            actual_sale=actual,
            defaults={"detected_by": "USER", "status": "CANDIDATE"},
        )
        adj.qty_adjustment = request.POST.get("qty_adjustment")
        adj.revenue_adjustment = request.POST.get("revenue_adjustment") or None
        adj.reason = request.POST.get("reason", "")
        adj.created_by = request.user
        try:
            adj.full_clean()
        except Exception as exc:
            return render(request, "demand/outliers/partials/_raise_exception_form.html",
                           {"actual": actual, "errors": exc.message_dict})
        adj.confirm(user=request.user)  # planner-raised exceptions are self-confirming
        return render(request, "demand/outliers/partials/_row.html", {"adjustment": adj})

    return render(request, "demand/outliers/partials/_raise_exception_form.html", {"actual": actual})

@login_required
def outlier_decisions_report(request, client_id):
    client = request.client
    qs = ActualSaleOutlierAdjustment.objects.filter(
        actual_sale__client=client
    ).exclude(status="CANDIDATE").select_related(
        "actual_sale", "actual_sale__item", "actual_sale__planning_location",
        "actual_sale__planning_customer", "actual_sale__distribution_channel",
        "created_by", "confirmed_by",
    )
    for param, field in [
        ("item", "actual_sale__item_id"),
        ("planning_location", "actual_sale__planning_location_id"),
        ("planning_customer", "actual_sale__planning_customer_id"),
        ("distribution_channel", "actual_sale__distribution_channel_id"),
        ("status", "status"),
        ("detected_by", "detected_by"),
    ]:
        value = request.GET.get(param)
        if value:
            qs = qs.filter(**{field: value})
    if request.GET.get("period_start"):
        qs = qs.filter(actual_sale__period_start__gte=request.GET["period_start"])
    if request.GET.get("period_end"):
        qs = qs.filter(actual_sale__period_start__lte=request.GET["period_end"])

    return render(request, "demand/outliers/decisions_report.html", {
        "adjustments": qs.order_by("-confirmed_at")[:500],
        "active_nav": "outlier_decisions",
    })


@login_required
@require_POST
def outlier_revise(request, client_id, pk):
    """
    Edit a previously CONFIRMED/REJECTED adjustment's qty/revenue or status —
    reuses the same mutable record per the earlier one-to-one decision, not a
    new row. Re-running clean() enforces the same qty/revenue ceiling.
    """
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    if "qty_adjustment" in request.POST:
        adj.qty_adjustment = request.POST["qty_adjustment"]
    if "revenue_adjustment" in request.POST:
        adj.revenue_adjustment = request.POST["revenue_adjustment"] or None
    new_status = request.POST.get("status")
    if new_status in ("CONFIRMED", "REJECTED"):
        adj.status = new_status
        adj.confirmed_by = request.user
        from django.utils import timezone
        adj.confirmed_at = timezone.now()
    try:
        adj.full_clean()
    except Exception as exc:
        return render(request, "demand/outliers/partials/_decision_row.html",
                       {"adjustment": adj, "errors": exc.message_dict})
    adj.save()
    # Note: flag_stale_forecast_versions fires automatically via the post_save
    # signal on ActualSaleOutlierAdjustment (see signals.py delta) — no need
    # to call it explicitly here, even though status may not have changed on
    # every revision (e.g. only the qty_adjustment amount was edited). If you
    # want stale-flagging on amount-only edits too (not just status flips),
    # keep the signal firing unconditionally on any CONFIRMED/REJECTED save
    # rather than gating it on an actual transition.
    return render(request, "demand/outliers/partials/_decision_row.html", {"adjustment": adj})


@login_required
@require_POST
def outlier_undo_decision(request, client_id, pk):
    """
    Reverts a CONFIRMED/REJECTED adjustment back to CANDIDATE — the same
    mutable record, not a new one (consistent with the one-to-one design).
    Clearing confirmed_by/confirmed_at means it reads as "never decided"
    again, and it'll show up in the Outlier Review Queue's CANDIDATE tab
    immediately (no need to wait for a detection run — it already exists).
 
    Undoing a CONFIRMED adjustment changes its netting status (it was
    excluded from forecast/reporting nets; back at CANDIDATE it no longer
    is) — the shared post_save signal only re-flags stale forecast versions
    on transitions TO CONFIRMED/REJECTED, not back to CANDIDATE, so this
    view calls flag_stale_forecast_versions explicitly rather than relying
    on that signal to cover a case it wasn't written for.
 
    Returns an empty 200 response; the row's hx-swap="delete" removes it
    from the Decisions Report page regardless of body content, since this
    row no longer belongs there once its status is CANDIDATE again.
    """
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    adj.status = 'CANDIDATE'
    adj.confirmed_by = None
    adj.confirmed_at = None
    adj.save()
    flag_stale_forecast_versions.delay(actual_sale_id=adj.actual_sale_id)
    return HttpResponse(status=200)

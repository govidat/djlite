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
from django.db.models import Count, Min

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAggregate,
    ForecastOverride, OverrideSplitWeight, SeriesProfile, SeriesLevelEvaluation,
    AbcClassDefinition, ForecastingConfig,
)
from mysite.models.demand.actuals import (
    ActualSale, ActualSaleImport, PERIOD_TYPE_CHOICES,
)
from mysite.models.demand.hierarchy import (
    PlanningLocation
)
#from utils.feature_control import is_demand_feature_disabled
from utils.mixins import feature_gate, _is_htmx, _client_url_kwargs
import logging
logger = logging.getLogger(__name__)

from django.db.models import ExpressionWrapper, BooleanField, Q
from django.db.models.functions import Abs
import datetime
import calendar
from django.db.models import Min, Max, Count
from celery import chain
from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
from mysite.tasks.demand.run_forecast import run_forecast

#from decimal import Decimal
from django.db.models import Sum, Count, DecimalField
from django.db.models.functions import Coalesce
from utils.taxonomy_filters import (
        resolve_item_ids_for_multiple_nodes, parse_node_ids_param, TaxonomyFilterError,
    )
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

    context = {
        'versions': qs,
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
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('period_start', 'planning_location__code', 'item__item_id')
    )

    item_id       = request.GET.get('item_id', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    has_override  = request.GET.get('has_override', '')
    period_start  = request.GET.get('period_start', '').strip()

    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if customer_code:
        qs = qs.filter(planning_customer__code=customer_code)
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
        'has_override':  has_override,
        'period_start':  period_start,
    }

    context = {
        'version':        version,
        'page_obj':       page_obj,
        'filters':        filters,
        'locations':      locations,
        'customers':      customers,
        'periods':        periods,
        'grand_total':    grand_total,
        'page_total':     page_total,
        'single_item':    single_item,
        'is_multipage':   page_obj.has_other_pages(),
        'show_location':  len(locations) > 1,
        'show_customer':  len(customers) > 1,
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
        ForecastLine.objects.select_related('item', 'planning_location', 'planning_customer'),
        pk=line_id, version_id=pk, version__client=request.client,
    )
    return render(request, 'demand/partials/lines_table_row.html', {'line': line})


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

"""
@login_required
def version_aggregates(request, pk, client_id=None):


    blocked = feature_gate(request, 'demand_planning')
    if blocked:
        return blocked

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    agg_level = request.GET.get('agg_level', 'total')
    valid_levels = ['total', 'location', 'item', 'customer']
    if agg_level not in valid_levels:
        agg_level = 'total'

    qs = (
        ForecastAggregate.objects
        .filter(version=version, agg_level=agg_level)
        .order_by('period_start', 'agg_key')
    )

    # ── Distinct item count — drives qty column visibility ────────────────
    # At 'item' level, each row IS one item so we check distinct agg_key count
    # At other levels (total, location, customer) qty is a sum across items
    # and is not meaningful — always hide it
    if agg_level == 'item':
        distinct_items = qs.values('agg_key').distinct().count()
        single_item = distinct_items == 1
        show_qty = True
    else:
        # total/location/customer — qty never meaningful
        single_item = False
        show_qty = False
    #show_qty = single_item  # qty only shown when drilling into one item

    # ── Totals ────────────────────────────────────────────────────────────
    from django.db.models import Sum
    from django.db.models.functions import Coalesce
    from django.db.models import DecimalField

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

    is_multipage = page_obj.has_other_pages()

    # Page total
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

    # has_override flag per row
    aggregates = list(page_obj.object_list)
    for agg in aggregates:
        stat  = agg.total_statistical_value
        final = agg.total_final_value
        if stat is not None and final is not None:
            agg.has_override = abs(float(final) - float(stat)) > 0.5
        else:
            agg.has_override = False

    context = {
        'version':       version,
        'aggregates':    aggregates,
        'page_obj':      page_obj,
        'agg_level':     agg_level,
        'agg_level_choices': valid_levels,
        'grand_total':   grand_total,
        'page_total':    page_total,
        'show_qty':      show_qty,
        'single_item':   single_item,
        'is_multipage':  is_multipage,
    }

    if _is_htmx(request):
        return render(request, 'demand/partials/aggregates_table_body.html', context)
    return render(request, 'demand/version_aggregates.html', context)
"""


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
    ).select_related('item', 'planning_location', 'planning_customer')

    key = override.override_key
    if override.override_level == 'sku' and key.get('item_id'):
        qs = qs.filter(item__item_id=key['item_id'])
    elif override.override_level == 'location' and key.get('location_code'):
        qs = qs.filter(planning_location__code=key['location_code'])
    elif override.override_level == 'customer' and key.get('customer_code'):
        qs = qs.filter(planning_customer__code=key['customer_code'])

    return render(request, 'demand/partials/override_affected_lines.html', {
        'override': override, 'lines': qs, 'active_nav': 'versions',
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

    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    qs = (
        ForecastAccuracy.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('-mape')
    )

    avg_mape = None
    avg_bias = None
    rows = list(qs)
    mapes = [float(r.mape) for r in rows if r.mape is not None]
    biases = [float(r.bias) for r in rows if r.bias is not None]
    if mapes:
        avg_mape = sum(mapes) / len(mapes)
    if biases:
        avg_bias = sum(biases) / len(biases)

    context = {
        'version': version, 'accuracy_rows': rows[:200],
        'avg_mape': avg_mape, 'avg_bias': avg_bias,
        'total_rows': len(rows),
        'active_nav': 'versions',
    }
    if _is_htmx(request):
        return render(request, 'demand/partials/accuracy_table_body.html', context)
    return render(request, 'demand/version_accuracy.html', context)


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
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('-period_start')
    )

    item_id       = request.GET.get('item_id', '').strip()
    location_code = request.GET.get('location_code', '').strip()
    customer_code = request.GET.get('customer_code', '').strip()
    period_type   = request.GET.get('period_type', '').strip()
    period_start  = request.GET.get('period_start', '').strip()

    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if customer_code:
        qs = qs.filter(planning_customer__code=customer_code)
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
        'period_type':   period_type,
        'period_start':  period_start,
    }

    context = {
        'page_obj':     page_obj,
        'filters':      filters,
        'locations':    locations,
        'customers':    customers,
        'period_types': period_types,
        'periods':      periods,
        'show_location':       len(locations) > 1,
        'show_customer':       len(customers) > 0,
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

        if action == 'delete_and_upload' and pending_file:
            overlap_dates = []
            for s in request.POST.getlist('overlap_periods'):
                try:
                    overlap_dates.append(datetime.date.fromisoformat(s))
                except ValueError:
                    pass
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
    available_grains = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client)
        .order_by()
        .values_list('grain', flat=True)
        .distinct()
        .order_by('grain')
    )

    GRAIN_LABELS = {
        'item_cust_location': 'Item × Location × Customer',
        'item_loc':           'Item × Leaf Location',
        'item_client':        'Item × Client Total',
    }
    for g in available_grains:
        if g not in GRAIN_LABELS:
            if 'loc_depth' in g:
                try:
                    depth = int(g.rsplit('_', 1)[-1])
                    GRAIN_LABELS[g] = f'Item × Location (Depth {depth})'
                except ValueError:
                    GRAIN_LABELS[g] = g.replace('_', ' ').title()
            elif g.startswith('item_client_'):
                horizon = g.replace('item_client_', '')
                GRAIN_LABELS[g] = f'Item × Client ({horizon.title()})'
            else:
                GRAIN_LABELS[g] = g.replace('_', ' ').title()

    abc_level_choices = [
        (g, GRAIN_LABELS.get(g, g)) for g in available_grains
    ]

    # Default to most granular grain
    if not abc_level or abc_level not in available_grains:
        abc_level = available_grains[0] if available_grains else 'item_cust_location'

    # ── Determine display mode from selected grain ────────────────────────────
    if abc_level == 'item_client' or abc_level.startswith('item_client_'):
        display_mode = 'item_client'
    elif abc_level == 'item_loc' or (
        'loc_depth' in abc_level and not abc_level.startswith('item_client')
    ):
        display_mode = 'item_location'
    else:
        display_mode = 'atomic'  # item_cust_location

    # ── Extract depth for loc_depth grains ───────────────────────────────────
    loc_depth = None
    if display_mode == 'item_location' and 'loc_depth' in abc_level:
        try:
            loc_depth = int(abc_level.rsplit('_', 1)[-1])
        except ValueError:
            loc_depth = None

    # ── Build leaf → ancestor map for depth grains ────────────────────────────
    # Needed to match profile.planning_location_id (leaf) to
    # evaluation_key.location_id (ancestor at depth N)
    leaf_to_ancestor = {}
    if loc_depth is not None:
        def _ancestor_from_path(path, target_depth):
            parts = [p for p in path.split('/') if p]
            idx = target_depth - 1
            return int(parts[idx]) if idx < len(parts) else None

        leaf_to_ancestor = {
            loc['id']: _ancestor_from_path(loc['path'], loc_depth)
            for loc in PlanningLocation.objects
                .filter(client=request.client)
                .values('id', 'path')
        }

    # ── Base queryset ─────────────────────────────────────────────────────────
    qs = (
        SeriesProfile.objects
        .filter(client=request.client)
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('item__item_id', 'planning_location__code',
                  'planning_customer__code')
    )

    # ── Apply filters ─────────────────────────────────────────────────────────
    if demand_class:
        qs = qs.filter(demand_class_atomic=demand_class.upper())
    if is_manual == 'true':
        qs = qs.filter(chosen_strategy='MANUAL')
    if location_code:
        qs = qs.filter(planning_location__code=location_code)
    if item_id:
        qs = qs.filter(item__item_id__icontains=item_id)

    # Filter by ABC class at the selected grain level
    if abc_class:
        matching_items = (
            SeriesLevelEvaluation.objects
            .filter(
                client=request.client,
                grain=abc_level,
                abc_class=abc_class.upper(),
            )
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
    abc_classes_available = list(
        SeriesLevelEvaluation.objects
        .filter(client=request.client, grain=abc_level)
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

    evals = list(
        SeriesLevelEvaluation.objects
        .filter(
            client=request.client,
            grain=abc_level,
            item_id__in=page_item_ids,
        )
        .values(
            'item_id',
            'abc_class',
            'value_share_pct_at_level',
            'evaluation_key',       # contains location_id for loc grains
            'planning_customer_id', # FK, None for __NULL__ customers
        )
    )

    # ── Build abc_lookup and dedup_key based on display mode ──────────────────
    if display_mode == 'item_client':
        # One eval per item — key by item_id only
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
        # evaluation_key contains 'location_id' (ancestor at this depth)
        # profile.planning_location_id is leaf — use leaf_to_ancestor to match
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
                # depth grain — map leaf → ancestor
                anc_id = leaf_to_ancestor.get(profile.planning_location_id)
            else:
                # item_loc grain — location_id IS the leaf location
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

    else:
        # atomic — item_cust_location
        # evaluation_key has 'location_id' and 'customer_code'
        # use planning_customer_id (model FK) to match profiles
        abc_lookup = {}
        for e in evals:
            loc_id  = e['evaluation_key'].get('location_id')
            cust_id = e['planning_customer_id']  # None for __NULL__ rows
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

    # Pre-fetch ancestor location details for item_location display
    # evaluation_key already has location_id and level_label
    ancestor_location_map = {}  # ancestor_loc_id → {code, label}
    if display_mode == 'item_location':
        for e in evals:
            loc_id     = e['evaluation_key'].get('location_id')
            level_label = e['evaluation_key'].get('level_label', '')
            if loc_id is not None:
                ancestor_location_map[int(loc_id)] = {
                    'location_id':  int(loc_id),
                    'level_label':  level_label,
                }
        # Fetch location codes and names in one query
        if ancestor_location_map:
            ancestor_locs = (
                PlanningLocation.objects
                .filter(
                    client=request.client,
                    id__in=ancestor_location_map.keys()
                )
                .values('id', 'code', 'name')
            )
            for loc in ancestor_locs:
                ancestor_location_map[loc['id']].update({
                    'code': loc['code'],
                    'name': loc['name'],
                })

    for profile in page_obj.object_list:
        profile.abc_at_level = get_abc(profile)
        key = dedup_key(profile)

        if key not in seen:
            seen.add(key)

            # Attach ancestor location info for item_location display
            if display_mode == 'item_location':
                if leaf_to_ancestor:
                    anc_id = leaf_to_ancestor.get(profile.planning_location_id)
                else:
                    anc_id = profile.planning_location_id
                profile.ancestor_location = ancestor_location_map.get(anc_id, {})
            else:
                profile.ancestor_location = {}

            profiles.append(profile)

    # ── Context ───────────────────────────────────────────────────────────────
    filters = {
        'demand_class':  demand_class,
        'abc_class':     abc_class,
        'is_manual':     is_manual,
        'location_code': location_code,
        'item_id':       item_id,
        'abc_level':     abc_level,
    }

    context = {
        'page_obj':           page_obj,
        'profiles':           profiles,
        'filters':            filters,
        'demand_classes':     demand_classes,
        'abc_classes':        abc_classes_available,
        'locations':          locations,
        'abc_level_choices':  abc_level_choices,
        'selected_abc_level': abc_level,
        'display_mode':       display_mode,
        'show_demand_class':  len(demand_classes) > 1,
        'show_abc_class':     len(abc_classes_available) > 1,
        'show_location':      (
            len(locations) > 1 and display_mode != 'item_client'
        ),
        'show_is_manual':     qs.filter(chosen_strategy='MANUAL').exists(),
        'show_item_search':   distinct_items > 1,
        'period_choices':     PERIOD_TYPE_CHOICES,
        'active_nav': 'series_profiles'
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
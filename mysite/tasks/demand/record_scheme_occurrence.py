"""
Record scheme occurrences: measure actual uplift for closed scheme periods.

Called at period-close cadence for each ACTIVE scheme with fully elapsed periods.
Creates SalesSchemeOccurrence records with actual uplift measurements.
"""

import statistics
from decimal import Decimal

from celery import shared_task
from django.db import transaction

from mysite.models.demand.schemes import (
    SalesScheme, SalesSchemePeriod, SalesSchemeOccurrence,
    ResolvedSalesSchemePeriod,
)
from mysite.models.demand.actuals import ActualSale
from utils.demand.actuals_net import scheme_netted_queryset
from utils.demand.periods import step_date


@shared_task
def record_scheme_occurrence(scheme_id, period_type, period_start):
    """Measure actual uplift for a closed scheme period.

    For each ACTIVE scheme with fully elapsed periods:
    1. Baseline demand = median of neighbouring periods' raw qty/revenue.
    2. actual_qty_uplift_pct = (scheme_period_qty / baseline_qty) − 1.
    3. actual_value_uplift_pct = (scheme_period_revenue / baseline_revenue) − 1.
    4. actual_pull_forward_pct = 1 − (Δ shadow vs baseline) / (window uplift volume).
    5. variance = actual − expected for each measure.
    6. Upsert SalesSchemeOccurrence.
    """
    scheme = SalesScheme.objects.select_related("client").filter(pk=scheme_id).first()
    if scheme is None or scheme.status != "ACTIVE":
        return {"status": "skipped", "reason": "scheme not found or not ACTIVE"}

    client = scheme.client
    config = getattr(client, "forecasting_config", None)

    # Get the scheme's resolved periods for this window
    window_rows = ResolvedSalesSchemePeriod.objects.filter(
        scheme=scheme, is_shadow=False,
        period_type=period_type, period_start=period_start,
    )

    if not window_rows.exists():
        return {"status": "skipped", "reason": "no resolved window rows"}

    # Collect the items covered by this window
    window_item_ids = list(window_rows.values_list("item_id", flat=True).distinct())

    # Get raw actuals for the window period
    window_actuals = ActualSale.objects.filter(
        client=client,
        item_id__in=window_item_ids,
        period_type=period_type,
        period_start=period_start,
    )
    window_qty = sum(a.qty for a in window_actuals if a.qty)
    window_revenue = sum(a.revenue for a in window_actuals if a.revenue)

    if window_qty == 0:
        return {"status": "skipped", "reason": "zero window qty"}

    # Step 1: Baseline demand = median of neighbouring periods
    n_neighbours = 3
    lookback_start = step_date(period_start, period_type, -(n_neighbours + 1))
    lookahead_end = step_date(period_start, period_type, n_neighbours + 1)

    neighbour_periods = []
    d = lookback_start
    while d <= lookahead_end:
        if d != period_start:
            neighbour_periods.append(d)
        d = step_date(d, period_type, 1)

    neighbour_actuals = ActualSale.objects.filter(
        client=client,
        item_id__in=window_item_ids,
        period_type=period_type,
        period_start__in=neighbour_periods,
    )

    # Group by period and sum
    period_qtys = {}
    period_revenues = {}
    for a in neighbour_actuals:
        period_qtys.setdefault(a.period_start, 0)
        period_revenues.setdefault(a.period_start, 0)
        if a.qty:
            period_qtys[a.period_start] += float(a.qty)
        if a.revenue:
            period_revenues[a.period_start] += float(a.revenue)

    if not period_qtys:
        return {"status": "skipped", "reason": "no neighbour data"}

    baseline_qty = Decimal(str(statistics.median(period_qtys.values())))
    baseline_revenue = Decimal(str(statistics.median(period_revenues.values()))) if period_revenues else None

    # Step 2: actual_qty_uplift_pct
    actual_qty_uplift_pct = (Decimal(str(window_qty)) / baseline_qty) - Decimal('1') if baseline_qty > 0 else Decimal('0')

    # Step 3: actual_value_uplift_pct
    actual_value_uplift_pct = None
    if window_revenue and baseline_revenue and baseline_revenue > 0:
        actual_value_uplift_pct = (Decimal(str(window_revenue)) / baseline_revenue) - Decimal('1')

    # Step 4: actual_pull_forward_pct
    actual_pull_forward_pct = None
    shadow_rows = ResolvedSalesSchemePeriod.objects.filter(
        scheme=scheme, is_shadow=True,
        period_type=period_type,
    )
    if shadow_rows.exists() and scheme.shadow_periods > 0:
        shadow_item_ids = list(shadow_rows.values_list("item_id", flat=True).distinct())
        shadow_actuals = ActualSale.objects.filter(
            client=client,
            item_id__in=shadow_item_ids,
            period_type=period_type,
            period_start__in=[r.period_start for r in shadow_rows],
        )
        shadow_total_qty = sum(a.qty for a in shadow_actuals if a.qty)
        shadow_baseline_total = baseline_qty * len(shadow_rows) if shadow_rows.count() > 0 else Decimal('0')
        delta_shadow = shadow_total_qty - float(shadow_baseline_total)
        window_uplift_volume = float(baseline_qty * (actual_qty_uplift_pct))
        if window_uplift_volume > 0:
            actual_pull_forward_pct = Decimal(str(max(0, min(1, 1 - abs(delta_shadow) / window_uplift_volume))))

    # Step 5: variances
    qty_uplift_variance = actual_qty_uplift_pct - scheme.expected_qty_uplift_pct
    value_uplift_variance = None
    if actual_value_uplift_pct is not None:
        value_uplift_variance = actual_value_uplift_pct - scheme.expected_value_uplift_pct
    pull_forward_variance = None
    if actual_pull_forward_pct is not None:
        pull_forward_variance = actual_pull_forward_pct - scheme.pull_forward_pct

    # Step 6: Upsert occurrence
    from django.utils import timezone
    occurrence, created = SalesSchemeOccurrence.objects.update_or_create(
        scheme=scheme,
        period_type=period_type,
        period_start=period_start,
        defaults={
            'actual_qty_uplift_pct': actual_qty_uplift_pct.quantize(Decimal('0.0001')),
            'actual_value_uplift_pct': actual_value_uplift_pct.quantize(Decimal('0.0001')) if actual_value_uplift_pct else None,
            'actual_pull_forward_pct': actual_pull_forward_pct.quantize(Decimal('0.0001')) if actual_pull_forward_pct else None,
            'qty_uplift_variance': qty_uplift_variance.quantize(Decimal('0.0001')),
            'value_uplift_variance': value_uplift_variance.quantize(Decimal('0.0001')) if value_uplift_variance else None,
            'pull_forward_variance': pull_forward_variance.quantize(Decimal('0.0001')) if pull_forward_variance else None,
            'closed_at': timezone.now(),
        }
    )

    return {
        "status": "recorded",
        "occurrence_id": occurrence.pk,
        "actual_qty_uplift_pct": str(actual_qty_uplift_pct),
        "created": created,
    }


def suggest_uplift_for_scheme(scheme_code, client_id):
    """Suggest expected uplift and pull-forward from prior occurrences.

    When a planner registers a scheme with the same scheme_code that has >= 2
    prior occurrences, pre-fill expected_*_uplift_pct and pull_forward_pct with
    the median of the prior occurrences' actuals.  Surface variance warnings
    when occurrences missed expectation by a wide margin.

    Returns a dict:
      {
        "suggested": { field: median_value, ... },
        "occurrence_count": int,
        "history": [ { period_start, actual_qty_uplift_pct, ... }, ... ],
        "warnings": [ str, ... ],
      }
    or None if insufficient history.
    """
    occurrences = list(
        SalesSchemeOccurrence.objects.filter(
            scheme__client_id=client_id,
            scheme__scheme_code=scheme_code,
        )
        .exclude(actual_qty_uplift_pct__isnull=True)
        .order_by('-period_start')[:12]
    )

    if len(occurrences) < 2:
        return None

    qty_uplifts = [o.actual_qty_uplift_pct for o in occurrences if o.actual_qty_uplift_pct is not None]
    value_uplifts = [o.actual_value_uplift_pct for o in occurrences if o.actual_value_uplift_pct is not None]
    pull_forwards = [o.actual_pull_forward_pct for o in occurrences if o.actual_pull_forward_pct is not None]

    suggested = {}
    if qty_uplifts:
        suggested['expected_qty_uplift_pct'] = statistics.median(qty_uplifts)
    if value_uplifts:
        suggested['expected_value_uplift_pct'] = statistics.median(value_uplifts)
    if pull_forwards:
        suggested['pull_forward_pct'] = statistics.median(pull_forwards)

    if not suggested:
        return None

    # ── Variance warnings (IQR-based) ────────────────────────────────
    warnings = []

    def _iqr_warning(values, label, iqr_threshold=Decimal('0.15')):
        """Warn when IQR exceeds threshold — occurrences are inconsistent."""
        if len(values) < 4:
            return
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[(3 * n) // 4]
        iqr = q3 - q1
        if iqr > iqr_threshold:
            lo = min(values)
            hi = max(values)
            warnings.append(
                f"Past runs of '{label}' varied widely: "
                f"actual uplift ranged from {lo:.1%} to {hi:.1%} "
                f"(IQR = {iqr:.1%}). Consider reviewing each occurrence."
            )

    _iqr_warning(qty_uplifts, 'qty uplift')
    _iqr_warning(value_uplifts, 'value uplift')
    _iqr_warning(pull_forwards, 'pull-forward')

    # ── Single-occurrence outlier warning ─────────────────────────────
    if len(qty_uplifts) >= 3:
        med = statistics.median(qty_uplifts)
        mad = statistics.median([abs(v - med) for v in qty_uplifts])
        for o in occurrences:
            if o.actual_qty_uplift_pct is not None and mad > 0:
                if abs(o.actual_qty_uplift_pct - med) > 3 * mad:
                    warnings.append(
                        f"Occurrence at {o.period_start} had qty uplift "
                        f"of {o.actual_qty_uplift_pct:.1%} — "
                        f"far from the median ({med:.1%})."
                    )

    # ── Build history for display ─────────────────────────────────────
    history = []
    for o in occurrences:
        history.append({
            'period_start': str(o.period_start),
            'actual_qty_uplift_pct': str(o.actual_qty_uplift_pct) if o.actual_qty_uplift_pct is not None else None,
            'actual_value_uplift_pct': str(o.actual_value_uplift_pct) if o.actual_value_uplift_pct is not None else None,
            'actual_pull_forward_pct': str(o.actual_pull_forward_pct) if o.actual_pull_forward_pct is not None else None,
        })

    return {
        'suggested': {k: str(v) for k, v in suggested.items()},
        'occurrence_count': len(occurrences),
        'history': history,
        'warnings': warnings,
    }

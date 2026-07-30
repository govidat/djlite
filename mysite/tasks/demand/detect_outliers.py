
from decimal import Decimal

from celery import shared_task
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone

from mysite.models import ActualSale, ForecastVersion, ActualSaleOutlierAdjustment, Client
from utils.demand.outlier_detection import detect_candidates

from utils.demand.periods import as_date, step_date




# Period-type -> relativedelta kwarg and per-period multiplier, covering every
# value in PERIOD_TYPE_CHOICES. base_period_end is a DateField (no time
# component), so sub-day granularities (second/minute/hour) don't have a
# sound interpretation here — relativedelta silently upgrades a date to a
# datetime when given hours/minutes/seconds rather than raising, which would
# only surface as a confusing TypeError later when compared against
# actual.period_start (a plain date). Fail loudly and immediately instead.
_PERIOD_STEP = {
    "day": ("days", 1),
    "week": ("weeks", 1),
    "fortnight": ("weeks", 2),
    "month": ("months", 1),
    "bimonth": ("months", 2),
    "quarter": ("months", 3),
    "halfyear": ("months", 6),
    "year": ("years", 1),
}

_UNSUPPORTED_SUB_DAY_PERIODS = {"second", "minute", "hour"}

def _horizon_end(version):
    if version.period_type in _UNSUPPORTED_SUB_DAY_PERIODS:
        raise ValueError(
            f"flag_stale_forecast_versions doesn't support period_type="
            f"{version.period_type!r} — base_period_end is a DateField with "
            f"no time component, so sub-day horizon arithmetic isn't well-"
            f"defined here. This would need base_period_end to become a "
            f"DateTimeField before this task could handle it correctly."
        )
    unit, multiplier = _PERIOD_STEP[version.period_type]
    return version.base_period_end + relativedelta(**{unit: version.horizon_periods * multiplier})


 
@shared_task
def run_outlier_detection(client_id, target_period_start, target_period_end, triggered_by_user_id=None):
    """
    Planner-triggered. target_period_start/target_period_end are REQUIRED —
    this task never scans a client's full actuals history in one run.
 
    Accepts either date objects or ISO-format strings for the two period
    bounds (see periods.as_date — Celery JSON-serializes task args, so
    these frequently arrive as strings even if a caller passed real dates).
 
    Pulls a lookback window before target_period_start purely for
    statistical context (median/MAD baseline, persistence check); only
    creates ActualSaleOutlierAdjustment rows for ActualSale rows whose
    period_start falls within the target range. The lookback length is
    config.min_history_periods PERIODS OF THE ACTUALS' OWN period_type —
    not hardcoded months — since a client's actuals may be recorded in
    weeks, quarters, etc.
    """
    target_period_start = as_date(target_period_start)
    target_period_end = as_date(target_period_end)
 
    from mysite.models import Client
    client = Client.objects.select_related("forecasting_config").get(client_id=client_id)
    config = getattr(client, "forecasting_config", None)
    if config is None:
        return  # nothing configured yet — nothing to do
 
    # Determine period_type from the target range itself, before computing
    # a lookback window — if there's nothing in the target range at all,
    # there's nothing to detect regardless of lookback, so bail out early
    # rather than guessing a period_type with no data to confirm it.
    target_range_period_types = list(
        ActualSale.objects.filter(
            client=client,
            period_start__gte=target_period_start,
            period_start__lte=target_period_end,
        )
        # order_by() with no args clears ActualSale's Meta.ordering
        # (period_type, period_start, planning_location, item). Without
        # this, Postgres requires ORDER BY columns to also appear in
        # SELECT DISTINCT, so Django silently folds period_start/
        # planning_location/item into the distinctness check too — every
        # row then looks "distinct" even when period_type is identical,
        # since those hidden extra columns differ row to row.
        .order_by()
        .values_list("period_type", flat=True)
        .distinct()
    )
    if not target_range_period_types:
        return  # no actuals in this range — nothing to detect
 
    if len(target_range_period_types) > 1:
        raise ValueError(
            f"Mixed period_type values found in target range for client "
            f"{client_id}: {target_range_period_types}. ActualSale rows in "
            f"one run are expected to share a single period_type."
        )
    period_type = target_range_period_types[0]
 
    lookback_start = step_date(target_period_start, period_type, -config.min_history_periods)
 
    rows = (
        ActualSale.objects.filter(
            client=client,
            period_start__gte=lookback_start,
            period_start__lte=target_period_end,
        )
        .select_related("outlier_adjustment")
        .order_by("planning_location_id", "item_id", "distribution_channel_id",
                   "planning_customer_id", "period_start")
    )
 
    series_map = {}
    for row in rows:
        key = (row.planning_location_id, row.item_id, row.distribution_channel_id, row.planning_customer_id)
        series_map.setdefault(key, []).append(row)
 
    to_create = []
    for key, series_rows in series_map.items():
        series_rows.sort(key=lambda r: r.period_start)
        values = [r.qty for r in series_rows]
        candidate_indices = detect_candidates(
            values,
            mad_threshold=config.mad_threshold,
            persistence_periods=config.persistence_periods,
            min_history_periods=config.min_history_periods,
        )
        for i in candidate_indices:
            row = series_rows[i]
            if row.period_start < target_period_start:
                continue  # lookback-only period — context, never a candidate
            if hasattr(row, "outlier_adjustment"):
                continue  # 1:1 constraint — already has an adjustment, skip
            suggested_qty = _suggest_adjustment_qty(values, i)
            suggested_revenue = _suggest_adjustment_revenue(row, suggested_qty)
            to_create.append(
                ActualSaleOutlierAdjustment(
                    actual_sale=row,
                    qty_adjustment=suggested_qty,
                    revenue_adjustment=suggested_revenue,
                    detected_by="SYSTEM",
                    status="CANDIDATE",
                    reason="System-detected statistical outlier",
                )
            )
 
    with transaction.atomic():
        ActualSaleOutlierAdjustment.objects.bulk_create(to_create, ignore_conflicts=True)
        config.last_outlier_detection_run_at = timezone.now()
        config.last_outlier_detection_run_by_id = triggered_by_user_id
        config.last_outlier_detection_range_start = target_period_start
        config.last_outlier_detection_range_end = target_period_end
        config.save(update_fields=[
            "last_outlier_detection_run_at", "last_outlier_detection_run_by",
            "last_outlier_detection_range_start", "last_outlier_detection_range_end",
        ])
 
    if to_create:
        _notify_planners(client, count=len(to_create))
 
def _suggest_adjustment_qty(values, index):
    import statistics
    median = statistics.median(values)
    excess = values[index] - median
    return max(excess, values[index] * 0) if excess > 0 else values[index] * 0
 
 
def _suggest_adjustment_revenue(row, suggested_qty):
    """
    Prorata suggestion: scale the row's revenue by the same fraction as the
    suggested qty exclusion, assuming a roughly uniform unit rate across
    the row. This is only a starting point for the planner to review and
    edit before confirming — a real bulk-sale outlier may carry a different
    unit rate than the row's average (qty_adjustment and revenue_adjustment
    are recorded independently for exactly that reason), but a prorata
    estimate is a more useful default than leaving the suggestion blank.
 
    Returns None when there's nothing sensible to prorate — no revenue on
    the row at all, or a zero-qty row (which would divide by zero).
    """
    if row.revenue is None or row.qty == 0:
        return None
    fraction = suggested_qty / row.qty
    return (row.revenue * fraction).quantize(Decimal("0.01"))
 
 
def _notify_planners(client, count):
    pass
 
 
def _horizon_end(version):
    """Kept as a thin wrapper for backward compatibility with anything
    already importing _horizon_end directly — delegates to the shared
    period-arithmetic helper."""
    return step_date(version.base_period_end, version.period_type, version.horizon_periods)
 
 
@shared_task
def flag_stale_forecast_versions(actual_sale_id):
    """
    When a planner confirms or rejects an outlier adjustment, any DRAFT
    ForecastVersion whose forecast horizon covers the adjusted actual's
    period should be flagged stale — its stored ForecastLine values were
    computed before this confirmation/rejection.
 
    horizon_end isn't a stored field — it's derived per-version from
    base_period_end + horizon_periods, so this can't be done as a single
    .filter() call; it's computed in Python per DRAFT version instead.
    """
    actual = ActualSale.objects.select_related("client").get(pk=actual_sale_id)
 
    draft_versions = ForecastVersion.objects.filter(
        client_id=actual.client_id, status=ForecastVersion.Status.DRAFT,
    )
 
    stale_ids = [
        version.pk
        for version in draft_versions
        if version.base_period_end < actual.period_start <= _horizon_end(version)
    ]
 
    if stale_ids:
        ForecastVersion.objects.filter(pk__in=stale_ids).update(stale_actuals=True)
 

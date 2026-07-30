# mysite/utils/demand/periods.py
"""
Shared date arithmetic for anything that needs to step forward/back by a
number of periods of a given period_type (ActualSale.period_type and
ForecastVersion.period_type share the same PERIOD_TYPE_CHOICES).

Used by:
  - mysite.tasks.demand.detect_outliers.run_outlier_detection
    (lookback window before a planner-picked target range)
  - mysite.tasks.demand.detect_outliers.flag_stale_forecast_versions
    (forecast horizon end = base_period_end + horizon_periods)

Kept in one place so both call sites can't silently drift out of sync with
each other on period-type coverage or arithmetic.
"""

import datetime

from dateutil.relativedelta import relativedelta

# period_type -> (relativedelta unit, periods-per-unit multiplier)
PERIOD_STEP = {
    "day": ("days", 1),
    "week": ("weeks", 1),
    "fortnight": ("weeks", 2),
    "month": ("months", 1),
    "bimonth": ("months", 2),
    "quarter": ("months", 3),
    "halfyear": ("months", 6),
    "year": ("years", 1),
}

# second/minute/hour appear in PERIOD_TYPE_CHOICES but aren't supported here:
# ActualSale.period_start and ForecastVersion.base_period_end are both plain
# DateFields with no time component. relativedelta silently upgrades a date
# to a datetime when given hours/minutes/seconds rather than raising, which
# would only surface as a confusing TypeError later when the result gets
# compared against another plain date. Fail loudly and immediately instead.
UNSUPPORTED_SUB_DAY_PERIODS = {"second", "minute", "hour"}


def step_date(base_date: datetime.date, period_type: str, n_periods: int) -> datetime.date:
    """
    Returns base_date advanced by n_periods periods of period_type.
    n_periods may be negative to step backward (e.g. for a lookback window).
    """
    if period_type in UNSUPPORTED_SUB_DAY_PERIODS:
        raise ValueError(
            f"step_date doesn't support period_type={period_type!r} — the "
            f"underlying date field has no time component, so sub-day "
            f"arithmetic isn't well-defined here. This would need the "
            f"relevant field to become a DateTimeField before this could "
            f"be handled correctly."
        )
    if period_type not in PERIOD_STEP:
        raise ValueError(f"Unrecognized period_type: {period_type!r}")

    unit, multiplier = PERIOD_STEP[period_type]
    return base_date + relativedelta(**{unit: n_periods * multiplier})


def as_date(value) -> datetime.date:
    """
    Coerces a date, datetime, or ISO-format string (e.g. from an HTML
    <input type="date"> arriving via request.POST, or a Celery task
    argument that was JSON-serialized) into a plain datetime.date.

    Celery serializes task arguments as JSON by default, which doesn't have
    a native date type — so even if a caller passes a real date/datetime
    object into .delay(...), it can still arrive at the task as a string.
    Parsing defensively here means the task works the same whether it's
    triggered from the UI form, a management command, or called directly
    in a test with an actual date object.
    """
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    raise TypeError(f"Cannot interpret {value!r} as a date")
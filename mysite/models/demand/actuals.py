"""
THIS IS REQUIRED FOR THIS SET PF MODELS - UPDATED AS PER SPRINT3.2
3. Add to the indexing pattern kept in migration
# 1. Generate the migration normally
python manage.py makemigrations

# 2. Open the generated file and add the two functions
#    above the Migration class, then add RunPython at the
#    end of operations[]

# These functions live here — not imported from anywhere
def add_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    indexes = [
        # Item base table - REPLACE # in the beginning and # at the end of each line with ". So the line should read 3doubequote-Create - 3doublequote
        # Unique index for rows WITH a customer (standard behaviour)
        #""CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_with_customer ON mysite_actualsale (client_id, planning_location_id, item_id, planning_customer_id, period_type, period_start) WHERE planning_customer_id IS NOT NULL#"",
        #""CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_no_customer ON mysite_actualsale (client_id, planning_location_id, item_id, period_type, period_start) WHERE planning_customer_id IS NULL#"",     
    ]
    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS uq_actualsale_with_customer'
        'DROP INDEX IF EXISTS uq_actualsale_no_customer'
        # ... rest of drops
    ]
    for sql in drops:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0001_initial'),
    ]

    operations = [
        # ... all auto-generated model operations first ...

        migrations.RunPython(
            add_postgres_indexes,      # ← runs on: python manage.py migrate (forward)
            remove_postgres_indexes,   # ← runs on: python manage.py migrate <app> <prev> (reverse)

        ),
    ]

# 3. Verify it runs cleanly
python manage.py migrate

# 4. Confirm on PostgreSQL (production)
#python manage.py dbshell
# slash d mysite_item   # should show the GIN index

5. Add the new sub model to signals.py, translation.py, admin
"""
"""
mysite/models/demand/actuals.py

ActualSale  — lowest-level demand actuals:
              client × planning_location × item × planning_customer × period

ActualSaleImport — audit log of each upload batch (CSV / Excel).

Period design:
  Every row carries period_type (the bucket granularity), period_start (first
  day of the bucket), and period_end (last day, stored for fast range queries).
  period_end is auto-computed in save() using compute_period_end().

  All rows for a given client's actuals series MUST share the same period_type.
  StatsForecast requires a uniform, regular time series — mixing monthly and
  weekly rows for the same unique_id will cause forecasting errors.

  Supported period types and their pandas/StatsForecast freq aliases:
      second   → "s"       minute  → "min"    hour     → "h"
      day      → "D"       week    → "W-MON"  month    → "MS"
      bimonth  → "2MS"     quarter → "QS"     halfyear → "2QS"
      year     → "YS"

Natural key: (client, planning_location, item, planning_customer,
              period_type, period_start)
Use update_or_create on this key to make uploads idempotent.
"""

import datetime
from dateutil.relativedelta import relativedelta

from django.db import models
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
from calendar import monthrange

# ─────────────────────────────────────────────────────────────────────────────
# Period helpers
# ─────────────────────────────────────────────────────────────────────────────

PERIOD_TYPE_CHOICES = [
    ("second",   _("Second")),
    ("minute",   _("Minute")),
    ("hour",     _("Hour")),
    ("day",      _("Day")),
    ("week",     _("Week")),
    ("fortnight",     _("Fortnight (2 weeks)")),
    ("month",    _("Month")),
    ("bimonth",  _("Bi-Monthly (2 months)")),
    ("quarter",  _("Quarter")),
    ("halfyear", _("Half-Year")),
    ("year",     _("Year")),
]

# Maps period_type → pandas/StatsForecast freq string.
# Imported by the Celery forecast task.
PERIOD_FREQ_MAP: dict[str, str] = {
    "second":   "s",
    "minute":   "min",
    "hour":     "h",
    "day":      "D",
    "week":     "W-MON",
    "fortnight": "2W-MON",
    "month":    "MS",
    "bimonth":  "2MS",
    "quarter":  "QS",
    "halfyear": "2QS",
    "year":     "YS",
}

PERIOD_HIGHER_HORIZONS: dict[str, list[str]] = {
    'second':   ['minute', 'hour', 'day'],
    'minute':   ['hour', 'day', 'week'],
    'hour':     ['day', 'week', 'month'],
    'day':      ['week', 'fortnight', 'month'],
    'week':     ['month', 'quarter'],
    'fortnight':['month', 'quarter'],
    'month':    ['quarter', 'halfyear'],
    'bimonth':  ['halfyear', 'year'],
    'quarter':  ['halfyear', 'year'],
    'halfyear': ['year'],
    'year':     [],
}

def compute_period_end(period_start: datetime.date, period_type: str) -> datetime.date:
    """
    Return the last day (inclusive) of the bucket that starts on period_start.

    Examples:
        compute_period_end(date(2024, 1, 1), "month")    → date(2024, 1, 31)
        compute_period_end(date(2024, 1, 1), "quarter")  → date(2024, 3, 31)
        compute_period_end(date(2024, 1, 1), "week")     → date(2024, 1, 7)
        compute_period_end(date(2024, 1, 1), "day")      → date(2024, 1, 1)
    """
    d = period_start
    if period_type == "second":
        return d                       # same-day; sub-day precision not in DateField
    elif period_type == "minute":
        return d
    elif period_type == "hour":
        return d
    elif period_type == "day":
        return d
    elif period_type == "week":
        return d + datetime.timedelta(days=6)
    elif period_type == "fortnight":
        if d.day == 1:
            return d.replace(day=14)
        elif d.day == 15:
            last_day = monthrange(d.year, d.month)[1]
            return d.replace(day=last_day)
        else:
            raise ValueError(
                f"Fortnight period_start must be the 1st or 15th day of the month, got {d}"
            )    
    elif period_type == "month":
        return d + relativedelta(months=1) - datetime.timedelta(days=1)
    elif period_type == "bimonth":
        return d + relativedelta(months=2) - datetime.timedelta(days=1)
    elif period_type == "quarter":
        return d + relativedelta(months=3) - datetime.timedelta(days=1)
    elif period_type == "halfyear":
        return d + relativedelta(months=6) - datetime.timedelta(days=1)
    elif period_type == "year":
        return d + relativedelta(years=1) - datetime.timedelta(days=1)
    else:
        raise ValueError(f"Unknown period_type: {period_type!r}")


def validate_period_start(period_start: datetime.date, period_type: str) -> None:
    """
    Raise ValueError if period_start is not a valid anchor for the given period_type.

    Rules:
      week     → must be a Monday (weekday() == 0)
      month    → must be the 1st of the month
      bimonth  → must be 1st of an odd month (Jan, Mar, May …)
      quarter  → must be 1st of Jan / Apr / Jul / Oct
      halfyear → must be 1st of Jan or Jul
      year     → must be 1st of Jan
    """
    d = period_start
    if period_type == "week" and d.weekday() != 0:
        raise ValueError(f"period_start for week must be a Monday, got {d} ({d.strftime('%A')}).")
    if period_type in ("month", "bimonth", "quarter", "halfyear", "year") and d.day != 1:
        raise ValueError(f"period_start for {period_type} must be the 1st of the month, got {d}.")
    if period_type == "fortnight" and d.day not in (1, 15):
        raise ValueError(f"period_start for fortnight must be the 1st or 15th of the month, got {d}.")
    if period_type == "bimonth" and d.month % 2 != 1:
        raise ValueError(f"period_start for bimonth must be an odd month (Jan/Mar/…), got month {d.month}.")
    if period_type == "quarter" and d.month not in (1, 4, 7, 10):
        raise ValueError(f"period_start for quarter must be Jan/Apr/Jul/Oct, got month {d.month}.")
    if period_type == "halfyear" and d.month not in (1, 7):
        raise ValueError(f"period_start for halfyear must be Jan or Jul, got month {d.month}.")
    if period_type == "year" and d.month != 1:
        raise ValueError(f"period_start for year must be January, got month {d.month}.")

def get_higher_period_types(base_period_type: str, steps: int) -> list[str]:
    """
    Return the list of higher period types to try, up to `steps` levels.

    Examples:
        get_higher_period_types('month', 2)  → ['quarter', 'halfyear']
        get_higher_period_types('day', 3)    → ['week', 'fortnight', 'month']
        get_higher_period_types('year', 2)   → []
    """
    horizons = PERIOD_HIGHER_HORIZONS.get(base_period_type, [])
    return horizons[:steps]

# ─────────────────────────────────────────────────────────────────────────────
# ActualSaleImport — upload audit log
# ─────────────────────────────────────────────────────────────────────────────

class ActualSaleImport(models.Model):
    """Audit log for each actuals upload batch."""

    STATUS_CHOICES = [
        ("pending",    _("Pending")),
        ("processing", _("Processing")),
        ("done",       _("Done")),
        ("failed",     _("Failed")),
    ]

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="actual_sale_imports",
    )
    uploaded_by = models.ForeignKey(
        "auth.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    uploaded_at  = models.DateTimeField(auto_now_add=True)
    file_name    = models.CharField(max_length=512)
    period_type  = models.CharField(
        _("period type"),
        max_length=16,
        choices=PERIOD_TYPE_CHOICES,
        default="month",
        help_text=_("Bucket granularity of the data in this upload."),
    )
    row_count    = models.PositiveIntegerField(default=0)
    status       = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_log    = models.TextField(blank=True)

    class Meta:
        app_label = "mysite"
        ordering = ["-uploaded_at"]
        verbose_name = _("02-07 actual sale import")
        verbose_name_plural = _("02-07 actual sale imports")

    def __str__(self):
        return f"{self.file_name} [{self.period_type}] ({self.status}) — {self.uploaded_at:%Y-%m-%d}"


# ─────────────────────────────────────────────────────────────────────────────
# ActualSale — atomic demand actuals at flexible period grain
# ─────────────────────────────────────────────────────────────────────────────

class ActualSale(models.Model):
    """
    One row = one (location, item, customer, period) combination.

    period_type + period_start define the bucket. period_end is stored
    explicitly (computed in save()) for fast DuckDB range queries.

    This is the atomic grain that StatsForecast consumes. During the Celery
    forecast task, rows are aggregated up the three hierarchies using DuckDB
    and then passed to hierarchicalforecast with the freq from PERIOD_FREQ_MAP.
    """

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="actual_sales",
    )
    # ── Location ──────────────────────────────────────────────────────────────
    planning_location = models.ForeignKey(
        PlanningLocation,
        on_delete=models.PROTECT,
        related_name="actual_sales",
        verbose_name=_("planning location"),
    )
    item = models.ForeignKey(
        "mysite.Item",
        on_delete=models.PROTECT,
        related_name="actual_sales",
        verbose_name=_("item"),
        help_text=_(
            "Active item belonging to this client. "
            "Item must have status='active'."
        ),
    )    
    """
    # ── Item: leaf TaxonomyNode from product_planning Taxonomy ────────────────
    item = models.ForeignKey(
        "mysite.TaxonomyNode",
        on_delete=models.PROTECT,
        related_name="actual_sales",
        verbose_name=_("item"),
        help_text=_(
            "Must be a leaf node of the Taxonomy with slug='product_planning'."
        ),
    )
    """
    # ── Customer (nullable = unattributed) ────────────────────────────────────
    planning_customer = models.ForeignKey(
        PlanningCustomer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actual_sales",
        verbose_name=_("planning customer"),
        help_text=_(
            "Null means demand is not attributed to any specific customer or group."
        ),
    )
    # ── Period ────────────────────────────────────────────────────────────────
    period_type = models.CharField(
        _("period type"),
        max_length=16,
        choices=PERIOD_TYPE_CHOICES,
        default="month",
        help_text=_(
            "Granularity of this period bucket. All rows in one forecast run "
            "must share the same period_type."
        ),
    )
    period_start = models.DateField(
        _("period start"),
        help_text=_(
            "First day of the period bucket (e.g. 2024-01-01 for a January month bucket, "
            "2024-01-01 for Q1 2024, 2024-01-01 for ISO week starting Mon 1 Jan 2024)."
        ),
    )
    period_end = models.DateField(
        _("period end"),
        editable=False,
        help_text=_(
            "Last day of the period bucket (inclusive). Auto-computed from "
            "period_type + period_start. Stored for fast range queries."
        ),
    )
    # ── Measures ──────────────────────────────────────────────────────────────
    qty = models.DecimalField(
        _("quantity"),
        max_digits=14,
        decimal_places=3,
        help_text=_("Sales quantity in base UoM."),
    )
    revenue = models.DecimalField(
        _("revenue"),
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Revenue in client's base currency. Optional."),
    )
    # ── Import provenance ─────────────────────────────────────────────────────
    import_batch = models.ForeignKey(
        ActualSaleImport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actual_sales",
    )

    class Meta:
        app_label = "mysite"
        # Natural key — enforces idempotent imports across any period type
        unique_together = [
            (
                "client", "planning_location", "item",
                "planning_customer", "period_type", "period_start",
            ), # this can be removed in pg as there is another index to take care
        ]
        ordering = ["period_type", "period_start", "planning_location", "item"]
        verbose_name = _("02-05 Actual Sale")
        verbose_name_plural = _("02-05 Actual Sales")
        indexes = [
            # Fast subtree queries: actuals for a location across any period range
            models.Index(
                fields=["client", "planning_location", "period_type", "period_start"],
                name="ix_actualsale_loc_period",
            ),
            # Fast item-level time-series extraction
            models.Index(
                fields=["client", "item", "period_type", "period_start"],
                name="ix_actualsale_item_period",
            ),
            # Customer-level drill-down
            models.Index(
                fields=["client", "planning_customer", "period_type", "period_start"],
                name="ix_actualsale_cust_period",
            ),
            # Range queries: "give me all actuals between date A and date B"
            models.Index(
                fields=["client", "period_type", "period_start", "period_end"],
                name="ix_actualsale_period_range",
            ),
        ]

    def save(self, *args, **kwargs):
        # Auto-compute period_end before every save
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        cust = self.planning_customer or "unattributed"
        return (
            f"{self.period_type}:{self.period_start} | {self.planning_location} | "
            f"{self.item} | {cust} | qty={self.qty}"
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        # Enforce planning_location belongs to client
        if self.planning_location_id and self.planning_location.client_id != self.client_id:
            raise ValidationError(_("Planning location must belong to the same client."))
        # Enforce planning_customer belongs to client
        if self.planning_customer_id and self.planning_customer.client_id != self.client_id:
            raise ValidationError(_("Planning customer must belong to the same client."))
        if self.item_id and self.item.client_id != self.client_id:
            raise ValidationError(_("Item must belong to the same client."))
        if self.item_id and self.item.status != "active":
            raise ValidationError(_("Only active items can have actuals recorded against them."))
        

        # Enforce period_start is a valid anchor for the chosen period_type
        if self.period_start and self.period_type:
            try:
                validate_period_start(self.period_start, self.period_type)
            except ValueError as exc:
                raise ValidationError({"period_start": str(exc)})
"""            
Celery Task: `process_summary_actuals_import`

This task handles location-level summary uploads (no customer, no item
breakdown — just total qty and revenue per location per period). It writes
to a separate `ActualSaleLocation` summary table rather than `ActualSale`.

### 5.1 `ActualSaleLocation` model

Add this to `mysite/models/demand/actuals.py` below `ActualSale`:

5.2 Summary import file columns

```
period_start    YYYY-MM-DD   required
location_code   string       required
total_qty       decimal      required
total_revenue   decimal      optional

"""
class ActualSaleLocation(models.Model):
    """
    Location-level summary actuals. One row per (client, location, period).

    Populated either:
      a) By direct upload via process_summary_actuals_import, or
      b) By aggregating ActualSale rows (via a Celery rollup task in 3B.3).

    Used as a consistency check: if the sum of ActualSale.qty for a
    location × period does not match ActualSaleLocation.total_qty,
    the data has gaps.
    """
    client            = models.ForeignKey(
        "mysite.Client", on_delete=models.CASCADE,
        related_name="actual_sale_locations",
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name="actual_sale_locations",
        verbose_name=_("planning location"),
    )
    period_type  = models.CharField(
        _("period type"), max_length=16, choices=PERIOD_TYPE_CHOICES,
    )
    period_start = models.DateField(_("period start"))
    period_end   = models.DateField(_("period end"), editable=False)
    total_qty    = models.DecimalField(
        _("total quantity"), max_digits=16, decimal_places=3,
    )
    total_revenue = models.DecimalField(
        _("total revenue"), max_digits=18, decimal_places=2,
        null=True, blank=True,
    )
    import_batch  = models.ForeignKey(
        ActualSaleImport, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="summary_actuals",
    )

    class Meta:
        app_label     = "mysite"
        unique_together = [
            ("client", "planning_location", "period_type", "period_start"),
        ]
        ordering      = ["period_type", "period_start", "planning_location"]
        verbose_name  = _("02-06 Actual Sale Location")
        verbose_name_plural = _("02-06 Actual Sale Locations")
        indexes = [
            models.Index(
                fields=["client", "planning_location", "period_type", "period_start"],
                name="ix_actualsaleloc_period",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.period_type}:{self.period_start} | "
            f"{self.planning_location} | qty={self.total_qty}"
        )
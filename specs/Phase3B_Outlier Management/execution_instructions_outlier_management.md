# Execution Instructions — Actuals Outlier Management (Sprint 3B.2b)

This is a build runbook for Phases 1–6 of the project plan. Each phase lists the exact files to
touch, the order to touch them in, and a checkpoint to verify before moving on. Code shown is
illustrative — adapt names/paths to match your actual app layout, but the shapes (fields, signatures,
signal wiring) should be followed closely since later phases depend on them.

---

## Phase 1 — Data Model & Query-Time Netting Helper

### Step 1.1 — Add fields to `Client`

Open the file containing the `Client` model and add the six new fields. Keep them together in a
clearly labeled block so they're easy to find later:

```python
class Client(models.Model):
    # ... existing fields ...

    # ── Outlier detection & net-actuals configuration ──────────────────────
    mad_threshold = models.DecimalField(
        max_digits=6, decimal_places=2, default=3.5,
        help_text=_("For Actual Sale outlier detection. Leave it untouched if not sure."),
    )
    persistence_periods = models.PositiveSmallIntegerField(
        default=3,
        help_text=_(
            "For Actual Sale outlier detection. Leave it untouched if not sure. Number of "
            "consecutive periods a sustained elevation must hold before it's treated as a "
            "level shift rather than a candidate."
        ),
    )
    min_history_periods = models.PositiveSmallIntegerField(
        default=12,
        help_text=_(
            "For Actual Sale outlier detection. Leave it untouched if not sure. Skip detection "
            "for a series with fewer periods of history than this."
        ),
    )
    forecast_uses_net_actuals = models.BooleanField(default=True)
    reporting_uses_net_actuals = models.BooleanField(default=True)
    abc_classification_uses_net_actuals = models.BooleanField(default=True)
```

Run:
```bash
python manage.py makemigrations mysite -n add_outlier_detection_fields_to_client
```
Inspect the generated migration — it should be additive-only (six `AddField` operations, no data
migration needed since all have defaults).

### Step 1.2 — Add `outlier_management` to `ClientFeatureControl`

Wherever your existing `ClientFeatureControl` keys are enumerated (a choices list, an enum, or a
seed-data fixture), add `"outlier_management"` following the same pattern as your other optional
Phase 3B module flags. If feature keys are DB-seeded rather than code-defined, add a data migration
that inserts the new key with a sensible default (`enabled=False` is the safer default for a brand-new
module — flip to `True` per-Client once QA'd).

### Step 1.3 — Create `ActualSaleOutlierAdjustment`

Create `mysite/models/demand/outliers.py`:

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.actuals import ActualSale


class ActualSaleOutlierAdjustment(models.Model):
    DETECTED_BY_CHOICES = [("SYSTEM", _("System")), ("USER", _("User"))]
    STATUS_CHOICES = [
        ("CANDIDATE", _("Candidate")),
        ("CONFIRMED", _("Confirmed")),
        ("REJECTED", _("Rejected")),
    ]

    actual_sale = models.OneToOneField(
        ActualSale, on_delete=models.CASCADE, related_name="outlier_adjustment",
    )
    qty_adjustment = models.DecimalField(
        _("qty adjustment"), max_digits=14, decimal_places=3,
        help_text=_("Portion of actual_sale.qty attributable to the outlier; deducted, not the full row."),
    )
    revenue_adjustment = models.DecimalField(
        _("revenue adjustment"), max_digits=16, decimal_places=2, null=True, blank=True,
        help_text=_("Independent of qty_adjustment. Optional, mirroring ActualSale.revenue."),
    )
    detected_by = models.CharField(_("detected by"), max_length=8, choices=DETECTED_BY_CHOICES)
    status = models.CharField(
        _("status"), max_length=12, choices=STATUS_CHOICES, default="CANDIDATE",
    )
    reason = models.CharField(_("reason"), max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    confirmed_at = models.DateTimeField(_("confirmed at"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        indexes = [
            models.Index(fields=["status"], name="ix_outlieradj_status"),
        ]
        verbose_name = _("02-06 Actual Sale Outlier Adjustment")
        verbose_name_plural = _("02-06 Actual Sale Outlier Adjustments")

    def __str__(self):
        return f"{self.actual_sale} | qty_adj={self.qty_adjustment} | {self.status}"

    def clean(self):
        if self.qty_adjustment is not None and self.actual_sale_id:
            if self.qty_adjustment > self.actual_sale.qty:
                raise ValidationError({"qty_adjustment": _("Cannot exceed the actual's qty.")})
            if self.qty_adjustment < 0:
                raise ValidationError({"qty_adjustment": _("Cannot be negative.")})
        if (
            self.revenue_adjustment is not None
            and self.actual_sale_id
            and self.actual_sale.revenue is not None
        ):
            if self.revenue_adjustment > self.actual_sale.revenue:
                raise ValidationError({"revenue_adjustment": _("Cannot exceed the actual's revenue.")})
            if self.revenue_adjustment < 0:
                raise ValidationError({"revenue_adjustment": _("Cannot be negative.")})

    def confirm(self, user):
        from django.utils import timezone
        self.status = "CONFIRMED"
        self.confirmed_by = user
        self.confirmed_at = timezone.now()
        self.full_clean()
        self.save()

    def reject(self, user):
        self.status = "REJECTED"
        self.confirmed_by = user
        self.confirmed_at = None
        self.save()
```

Register the model in `mysite/models/demand/__init__.py` (or wherever your demand models are
re-exported) so it's importable as `mysite.models.ActualSaleOutlierAdjustment`.

Run:
```bash
python manage.py makemigrations mysite -n add_actual_sale_outlier_adjustment
```

**Checkpoint:** `python manage.py migrate` runs cleanly; in the shell,
`ActualSaleOutlierAdjustment(actual_sale=some_actual, qty_adjustment=Decimal("999999")).full_clean()`
raises `ValidationError` against a real `ActualSale` fixture with a smaller qty.

### Step 1.4 — Write the netting helper

Create `mysite/utils/demand/actuals_net.py`:

```python
from django.db.models import Case, DecimalField, F, Value, When
from django.db.models.functions import Coalesce

from mysite.models.demand.actuals import ActualSale


def actuals_queryset_with_net(client, use_net: bool):
    """
    Returns an ActualSale queryset for `client`, annotated with net_qty / net_revenue.

    use_net is supplied by the caller from the relevant Client flag
    (client.forecast_uses_net_actuals / client.reporting_uses_net_actuals /
    client.abc_classification_uses_net_actuals). This function itself doesn't
    read any flag off `client` — keeping it flag-agnostic means all three
    call sites share one code path and one set of tests.
    """
    qs = ActualSale.objects.filter(client=client).select_related("outlier_adjustment")

    if not use_net:
        return qs.annotate(
            net_qty=F("qty"),
            net_revenue=F("revenue"),
        )

    return qs.annotate(
        net_qty=Case(
            When(
                outlier_adjustment__status="CONFIRMED",
                then=F("qty") - F("outlier_adjustment__qty_adjustment"),
            ),
            default=F("qty"),
            output_field=DecimalField(max_digits=14, decimal_places=3),
        ),
        net_revenue=Case(
            When(
                outlier_adjustment__status="CONFIRMED",
                then=F("revenue") - Coalesce(
                    F("outlier_adjustment__revenue_adjustment"),
                    Value(0),
                ),
            ),
            default=F("revenue"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )
```

### Step 1.5 — Unit tests for Phase 1

Create `mysite/tests/demand/test_actuals_net.py`:

```python
from decimal import Decimal
from django.test import TestCase
from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.outliers import ActualSaleOutlierAdjustment
from mysite.utils.demand.actuals_net import actuals_queryset_with_net
# import your test fixture factories for Client, PlanningLocation, Item, etc.


class ActualsNetTests(TestCase):
    def setUp(self):
        # build a minimal client + actual_sale fixture here
        ...

    def test_no_adjustment_passthrough(self):
        row = actuals_queryset_with_net(self.client, use_net=True).get(pk=self.actual.pk)
        self.assertEqual(row.net_qty, self.actual.qty)

    def test_candidate_adjustment_not_netted(self):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=self.actual, qty_adjustment=Decimal("100"),
            detected_by="SYSTEM", status="CANDIDATE",
        )
        row = actuals_queryset_with_net(self.client, use_net=True).get(pk=self.actual.pk)
        self.assertEqual(row.net_qty, self.actual.qty)

    def test_confirmed_adjustment_netted(self):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=self.actual, qty_adjustment=Decimal("100"),
            detected_by="SYSTEM", status="CONFIRMED",
        )
        row = actuals_queryset_with_net(self.client, use_net=True).get(pk=self.actual.pk)
        self.assertEqual(row.net_qty, self.actual.qty - Decimal("100"))

    def test_use_net_false_ignores_confirmed_adjustment(self):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=self.actual, qty_adjustment=Decimal("100"),
            detected_by="SYSTEM", status="CONFIRMED",
        )
        row = actuals_queryset_with_net(self.client, use_net=False).get(pk=self.actual.pk)
        self.assertEqual(row.net_qty, self.actual.qty)
```

**Checkpoint before moving to Phase 2:** all four tests above pass; `clean()` validation tests for
over-limit qty/revenue also pass; `makemigrations --check` is clean.

---

## Phase 2 — Detection Engine

### Step 2.1 — Write the detection function (pure, testable, no Celery yet)

Create `mysite/utils/demand/outlier_detection.py` — keep the statistics separate from the Celery task
so it's directly unit-testable without Celery's eager-mode plumbing:

```python
from decimal import Decimal
import statistics


def mad_score(values: list[Decimal]) -> list[Decimal]:
    """Median Absolute Deviation score per point in a series."""
    if len(values) < 3:
        return [Decimal("0")] * len(values)
    median = statistics.median(values)
    abs_devs = [abs(v - median) for v in values]
    mad = statistics.median(abs_devs)
    if mad == 0:
        return [Decimal("0")] * len(values)
    # 0.6745 scales MAD to be comparable to a standard deviation under normality
    return [Decimal("0.6745") * abs(v - median) / mad for v in values]


def is_sustained(values: list[Decimal], index: int, persistence_periods: int, median: Decimal) -> bool:
    """
    True if the elevated value at `index` persists for `persistence_periods`
    consecutive periods at a similar level — treated as a level shift, not
    a transient spike, and therefore NOT a candidate.
    """
    window = values[index: index + persistence_periods]
    if len(window) < persistence_periods:
        return False
    threshold = median * Decimal("1.5")  # values holding above 1.5x median count as "elevated"
    return all(v >= threshold for v in window)


def detect_candidates(
    series_values: list[Decimal],
    mad_threshold: Decimal,
    persistence_periods: int,
    min_history_periods: int,
) -> list[int]:
    """
    Returns list of indices in series_values flagged as outlier candidates.
    series_values must be in chronological order.
    """
    if len(series_values) < min_history_periods:
        return []

    scores = mad_score(series_values)
    median = Decimal(str(statistics.median(series_values)))
    candidates = []
    for i, score in enumerate(scores):
        if score < mad_threshold:
            continue
        if is_sustained(series_values, i, persistence_periods, median):
            continue  # sustained elevation -> level shift, not a candidate
        candidates.append(i)
    return candidates
```

### Step 2.2 — Unit test the pure detection function first

Create `mysite/tests/demand/test_outlier_detection.py`:

```python
from decimal import Decimal
from django.test import SimpleTestCase
from mysite.utils.demand.outlier_detection import detect_candidates


class DetectCandidatesTests(SimpleTestCase):
    def test_flags_single_period_spike(self):
        series = [Decimal(x) for x in [100, 105, 98, 102, 500, 101, 99, 103, 97, 100, 104, 99]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertIn(4, result)

    def test_does_not_flag_sustained_increase(self):
        series = [Decimal(x) for x in [100, 105, 98, 102, 400, 410, 405, 103, 97, 100, 104, 99]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertNotIn(4, result)
        self.assertNotIn(5, result)

    def test_skips_short_history(self):
        series = [Decimal(x) for x in [100, 500, 100]]
        result = detect_candidates(series, mad_threshold=Decimal("3.5"), persistence_periods=3, min_history_periods=12)
        self.assertEqual(result, [])
```

Run these and iterate on `mad_score`/`is_sustained` until they pass — this is the highest-risk logic
in the whole feature, worth getting solid before wiring it into Celery.

### Step 2.3 — Wire the Celery task

Create `mysite/tasks/demand/detect_outliers.py`:

```python
from celery import shared_task
from django.db import transaction

from mysite.models.demand.actuals import ActualSale, ActualSaleImport
from mysite.models.demand.outliers import ActualSaleOutlierAdjustment
from mysite.utils.demand.outlier_detection import detect_candidates


@shared_task
def detect_outlier_candidates(client_id, import_batch_id):
    import_batch = ActualSaleImport.objects.select_related("client").get(pk=import_batch_id)
    client = import_batch.client

    rows = (
        ActualSale.objects.filter(client_id=client_id, import_batch_id=import_batch_id)
        .select_related("outlier_adjustment")
        .order_by("planning_location_id", "item_id", "distribution_channel_id",
                   "planning_customer_id", "period_start")
    )

    # group into series by grain, excluding the period dimension
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
            mad_threshold=client.mad_threshold,
            persistence_periods=client.persistence_periods,
            min_history_periods=client.min_history_periods,
        )
        for i in candidate_indices:
            row = series_rows[i]
            if hasattr(row, "outlier_adjustment"):
                continue  # 1:1 constraint — already has an adjustment, skip
            suggested_qty = _suggest_adjustment_qty(values, i)
            to_create.append(
                ActualSaleOutlierAdjustment(
                    actual_sale=row,
                    qty_adjustment=suggested_qty,
                    detected_by="SYSTEM",
                    status="CANDIDATE",
                    reason="System-detected statistical outlier",
                )
            )

    with transaction.atomic():
        ActualSaleOutlierAdjustment.objects.bulk_create(to_create, ignore_conflicts=True)

    if to_create:
        _notify_planners(client, count=len(to_create))


def _suggest_adjustment_qty(values, index):
    """Simple starter heuristic: suggest the excess above the series median."""
    import statistics
    median = statistics.median(values)
    excess = values[index] - median
    return max(excess, values[index] * 0) if excess > 0 else values[index] * 0


def _notify_planners(client, count):
    # hook into your existing Django messages / email digest mechanism
    pass
```

### Step 2.4 — Wire the trigger

Find where `ActualSaleImport.status` transitions to `COMPLETE` in your existing import pipeline
(likely the end of `process_actuals_import`). Add:

```python
from mysite.tasks.demand.detect_outliers import detect_outlier_candidates

# ... at the point where import_batch.status is set to COMPLETE and saved ...
detect_outlier_candidates.delay(client_id=import_batch.client_id, import_batch_id=import_batch.id)
```

Do **not** use a `post_save` signal on `ActualSaleImport` for this — it's cleaner and easier to trace
to fire it explicitly at the one call site where the import actually completes, matching how your
other post-import steps are likely already wired.

**Checkpoint before moving to Phase 3:** run a real import fixture through Celery (eager mode in
tests, `CELERY_TASK_ALWAYS_EAGER=True`), assert `ActualSaleOutlierAdjustment` rows are created for the
expected rows and only those rows.

---

## Phase 3 — Planner Review Views & Admin

### Step 3.1 — Add `stale_actuals` to `ForecastVersion`

```python
class ForecastVersion(models.Model):
    # ... existing fields ...
    stale_actuals = models.BooleanField(
        default=False,
        help_text=_("True if a confirmed outlier adjustment was recorded against an actual "
                     "covered by this version's horizon after the version was generated."),
    )
```
```bash
python manage.py makemigrations mysite -n add_stale_actuals_to_forecast_version
```

### Step 3.2 — Stale-flagging task

Add to `mysite/tasks/demand/detect_outliers.py`:

```python
@shared_task
def flag_stale_forecast_versions(actual_sale_id):
    actual = ActualSale.objects.select_related("client").get(pk=actual_sale_id)
    affected = ForecastVersion.objects.filter(
        client_id=actual.client_id,
        status="DRAFT",
        horizon_start__lte=actual.period_start,
        horizon_end__gte=actual.period_start,
    )
    affected.update(stale_actuals=True)
```

Wire it via a `post_save` signal on `ActualSaleOutlierAdjustment` (this one is fine as a signal, since
confirm/reject can happen from multiple call sites — the view, the admin, a future bulk action):

```python
# mysite/signals/demand.py (or wherever your demand signals live)
from django.db.models.signals import post_save
from django.dispatch import receiver

from mysite.models.demand.outliers import ActualSaleOutlierAdjustment
from mysite.tasks.demand.detect_outliers import flag_stale_forecast_versions


@receiver(post_save, sender=ActualSaleOutlierAdjustment)
def _on_outlier_adjustment_status_change(sender, instance, **kwargs):
    if instance.status in ("CONFIRMED", "REJECTED"):
        flag_stale_forecast_versions.delay(actual_sale_id=instance.actual_sale_id)
```

Make sure this signal module is imported in your app's `AppConfig.ready()`.

### Step 3.3 — Views

Create `mysite/demand_ui/views/outliers.py`:

```python
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.outliers import ActualSaleOutlierAdjustment


@login_required
def outlier_queue(request):
    client = request.client  # existing client-scoping middleware
    qs = ActualSaleOutlierAdjustment.objects.filter(
        actual_sale__client=client
    ).select_related(
        "actual_sale", "actual_sale__item", "actual_sale__planning_location",
        "actual_sale__planning_customer", "actual_sale__distribution_channel",
    )

    status = request.GET.get("status", "CANDIDATE")
    if status:
        qs = qs.filter(status=status)
    # apply additional filters: item, planning_location, planning_customer,
    # distribution_channel, period range — from request.GET as needed

    return render(request, "demand_ui/outliers/queue.html", {
        "adjustments": qs.order_by("-created_at")[:200],
        "current_status": status,
    })


@login_required
@require_POST
def outlier_confirm(request, pk):
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    # allow the planner to tweak the suggested amount before confirming
    if "qty_adjustment" in request.POST:
        adj.qty_adjustment = request.POST["qty_adjustment"]
    if "revenue_adjustment" in request.POST:
        adj.revenue_adjustment = request.POST["revenue_adjustment"] or None
    adj.confirm(user=request.user)
    return render(request, "demand_ui/outliers/_row.html", {"adjustment": adj})


@login_required
@require_POST
def outlier_reject(request, pk):
    adj = get_object_or_404(ActualSaleOutlierAdjustment, pk=pk, actual_sale__client=request.client)
    adj.reject(user=request.user)
    return render(request, "demand_ui/outliers/_row.html", {"adjustment": adj})


@login_required
def raise_exception_form(request, actual_sale_id):
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
            return render(request, "demand_ui/outliers/_raise_exception_form.html",
                           {"actual": actual, "errors": exc.message_dict})
        adj.confirm(user=request.user)  # planner-raised exceptions are self-confirming
        return render(request, "demand_ui/outliers/_row.html", {"adjustment": adj})

    return render(request, "demand_ui/outliers/_raise_exception_form.html", {"actual": actual})
```

Add URL routes in `demand_ui/urls.py`:

```python
path("outliers/", views.outlier_queue, name="outlier_queue"),
path("outliers/<int:pk>/confirm/", views.outlier_confirm, name="outlier_confirm"),
path("outliers/<int:pk>/reject/", views.outlier_reject, name="outlier_reject"),
path("actuals/<int:actual_sale_id>/outlier/raise/", views.raise_exception_form, name="raise_exception_form"),
```

### Step 3.4 — Templates

`templates/demand_ui/outliers/queue.html` (extends your existing base layout):
```html
{% extends "demand_ui/base.html" %}
{% block content %}
<div id="outlier-queue">
  <h1>Outlier Review Queue</h1>
  <div class="tabs">
    <a hx-get="{% url 'outlier_queue' %}?status=CANDIDATE" hx-target="#outlier-queue" hx-select="#outlier-queue">Candidates</a>
    <a hx-get="{% url 'outlier_queue' %}?status=CONFIRMED" hx-target="#outlier-queue" hx-select="#outlier-queue">Confirmed</a>
    <a hx-get="{% url 'outlier_queue' %}?status=REJECTED" hx-target="#outlier-queue" hx-select="#outlier-queue">Rejected</a>
  </div>
  <table>
    <tbody id="outlier-rows">
      {% for adjustment in adjustments %}
        {% include "demand_ui/outliers/_row.html" %}
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

`templates/demand_ui/outliers/_row.html`:
```html
<tr id="outlier-row-{{ adjustment.pk }}">
  <td>{{ adjustment.actual_sale.item }}</td>
  <td>{{ adjustment.actual_sale.planning_location }}</td>
  <td>{{ adjustment.actual_sale.distribution_channel }}</td>
  <td>{{ adjustment.actual_sale.planning_customer|default:"—" }}</td>
  <td>{{ adjustment.actual_sale.period_start }}</td>
  <td>{{ adjustment.actual_sale.qty }}</td>
  <td>{{ adjustment.qty_adjustment }}</td>
  <td>{{ adjustment.status }}</td>
  <td>
    {% if adjustment.status == "CANDIDATE" %}
      <form hx-post="{% url 'outlier_confirm' adjustment.pk %}" hx-target="#outlier-row-{{ adjustment.pk }}" hx-swap="outerHTML">
        <input type="hidden" name="qty_adjustment" value="{{ adjustment.qty_adjustment }}">
        <button type="submit">Confirm</button>
      </form>
      <form hx-post="{% url 'outlier_reject' adjustment.pk %}" hx-target="#outlier-row-{{ adjustment.pk }}" hx-swap="outerHTML">
        <button type="submit">Reject</button>
      </form>
    {% endif %}
  </td>
</tr>
```

`templates/demand_ui/outliers/_raise_exception_form.html`:
```html
<form hx-post="{% url 'raise_exception_form' actual.pk %}" hx-target="this" hx-swap="outerHTML">
  {% if errors %}<div class="error">{{ errors }}</div>{% endif %}
  <label>Qty to exclude (max {{ actual.qty }})</label>
  <input type="number" step="0.001" name="qty_adjustment" max="{{ actual.qty }}" required>
  <label>Revenue to exclude {% if actual.revenue %}(max {{ actual.revenue }}){% endif %}</label>
  <input type="number" step="0.01" name="revenue_adjustment" {% if actual.revenue %}max="{{ actual.revenue }}"{% endif %}>
  <label>Reason</label>
  <input type="text" name="reason">
  <button type="submit">Raise Exception</button>
</form>
```

Add an "Outlier queue" link and open-candidate-count badge to your shared `demand_ui` nav partial —
a simple context processor or template tag can supply
`ActualSaleOutlierAdjustment.objects.filter(actual_sale__client=request.client, status='CANDIDATE').count()`.

Add a `stale_actuals` badge conditionally in your Forecast Version list template:
```html
{% if version.stale_actuals %}<span class="badge badge-warning">Actuals changed — rerun recommended</span>{% endif %}
```

### Step 3.5 — Admin

```python
@admin.register(ActualSaleOutlierAdjustment)
class ActualSaleOutlierAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("actual_sale", "qty_adjustment", "status", "detected_by", "confirmed_by", "confirmed_at")
    list_filter = ("status", "detected_by")
    readonly_fields = ("detected_by", "created_by", "confirmed_by", "confirmed_at")
    autocomplete_fields = ("actual_sale",)
```

Add the six new `Client` fields to your existing `ClientAdmin`, grouped under a collapsible
"Outlier Detection" fieldset:
```python
fieldsets = [
    # ... existing fieldsets ...
    (_("Outlier Detection"), {
        "classes": ("collapse",),
        "fields": (
            "mad_threshold", "persistence_periods", "min_history_periods",
            "forecast_uses_net_actuals", "reporting_uses_net_actuals",
            "abc_classification_uses_net_actuals",
        ),
    }),
]
```

**Checkpoint before moving to Phase 4:** manually run through the queue in a browser — see a
candidate, confirm it, see it disappear from the CANDIDATE tab and appear under CONFIRMED, see the
`stale_actuals` badge appear on an affected draft forecast version.

---

## Phase 4 — Forecast & Override Engine Integration

### Step 4.1 — `build_actuals_dataframe`

Find the existing function (likely in `mysite/utils/demand/forecast_engine.py`). Change the actuals
pull to route through the netting helper:

```python
def build_actuals_dataframe(client, period_start, period_end):
    from mysite.utils.demand.actuals_net import actuals_queryset_with_net

    qs = actuals_queryset_with_net(client, use_net=client.forecast_uses_net_actuals).filter(
        period_start__gte=period_start, period_start__lte=period_end,
    )
    # If you currently drop into DuckDB via a raw SQL pull rather than the ORM queryset
    # directly, replicate the same Case/When logic as a SQL CASE expression in that query
    # instead, keyed on a LEFT JOIN to mysite_actualsaleoutlieradjustment WHERE status='CONFIRMED'.
    return pl.DataFrame(qs.values("planning_location_id", "item_id", "distribution_channel_id",
                                  "planning_customer_id", "period_start", "net_qty", "net_revenue"))
```

If your existing pipeline already goes ORM → Polars → DuckDB (not raw SQL), this ORM-level change is
sufficient and no DuckDB SQL needs touching. If instead you currently issue raw SQL directly against
Postgres for performance, add the equivalent `LEFT JOIN` there:

```sql
SELECT
    a.*,
    CASE WHEN oa.status = 'CONFIRMED' THEN a.qty - oa.qty_adjustment ELSE a.qty END AS net_qty,
    CASE WHEN oa.status = 'CONFIRMED' THEN a.revenue - COALESCE(oa.revenue_adjustment, 0) ELSE a.revenue END AS net_revenue
FROM mysite_actualsale a
LEFT JOIN mysite_actualsaleoutlieradjustment oa ON oa.actual_sale_id = a.id
WHERE a.client_id = %(client_id)s
  AND a.period_start BETWEEN %(period_start)s AND %(period_end)s
```

### Step 4.2 — `compute_proportional_shares`

Same pattern — replace the direct `ActualSale` query with `actuals_queryset_with_net(client,
use_net=client.forecast_uses_net_actuals)` and read `net_qty`/`net_revenue` instead of `qty`/`revenue`.

### Step 4.3 — Regression test

```python
def test_forecast_run_differs_with_confirmed_vs_rejected_outlier(self):
    # build identical actuals fixture, run forecast once with a CONFIRMED
    # adjustment on a spike period, once with the same adjustment REJECTED
    # assert the resulting ForecastLine values differ meaningfully
    ...
```

**Checkpoint:** this regression test passes and is committed — it's your guard against a future
refactor silently reverting to raw actuals in the forecast path.

---

## Phase 5 — Reporting & ABC Classification Integration

### Step 5.1 — Reporting queries

Wherever revenue/qty reporting reads `ActualSale` directly, swap in
`actuals_queryset_with_net(client, use_net=client.reporting_uses_net_actuals)`.

### Step 5.2 — ABC classification

Same pattern, gated by `client.abc_classification_uses_net_actuals`. Given ABC classification has
already had a scoping bug in this codebase (the earlier fieldset/JSONField mixup), double check this
change doesn't touch the same code path that caused that bug — add a regression test specifically
confirming ABC classification still scopes correctly per-client after this change.

### Step 5.3 — Independence test

```python
def test_reporting_and_forecast_flags_are_independent(self):
    # set forecast_uses_net_actuals=True, reporting_uses_net_actuals=False on the same client
    # confirm forecast query returns net values, reporting query returns raw values
    ...
```

**Checkpoint:** independence test passes — this is the test that proves the three flags aren't
accidentally sharing one code path that only reads one of them.

---

## Phase 6 — Hardening & Regression

- [ ] Run the full detection test suite against a larger synthetic fixture (e.g. 50 series, mixed
      spikes/level-shifts/clean series) and manually spot-check a sample of the flagged vs. unflagged
      results
- [ ] Time a `detect_outlier_candidates` run against a realistic monthly import batch size; if it's
      slow, profile whether the per-series grouping (Step 2.3) is the bottleneck — likely candidate
      for switching to a Polars/DuckDB groupby instead of Python dict grouping if history is large
- [ ] Cross-browser check the HTMX confirm/reject/raise-exception flows, including Firefox
      specifically given this project's prior history with Firefox dialog issues
- [ ] End-to-end test: import → `detect_outlier_candidates` fires → planner confirms via
      `outlier_confirm` view → `flag_stale_forecast_versions` fires → `build_actuals_dataframe`
      reflects the net value → a Client with `reporting_uses_net_actuals=False` still shows raw
      revenue in a reporting query against the same data
- [ ] `python manage.py makemigrations --check` clean; full test suite green; manual QA sign-off

Once Phase 6 checks are green, Sprint 3B.2b is done and Sprint 3B.3 (Forecast Models) can build on top
of `client.forecast_uses_net_actuals` and the netting helper with no further outlier-management work
required.

# Item Lifecycle Management — Substitution / Discontinuation / Introduction — Execution Instructions

Runbook for **Sprint 3B.2d**. Order of execution: Phase 1 (models/config/wiring) → Phase 2 (baseline
re-key layer — substitution) → Phase 3 (forecast-output layers — discontinuation + introduction) →
Phase 4 (detection/reporting) → Phase 5 (HTMX UI + tests). Every phase ends with a runnable
checkpoint.

Invariant carried through the whole sprint: **three lifecycle events, three layers, one flag.**

| Event | Scenario | Layer | Where it runs |
|-------|----------|-------|---------------|
| `ItemSubstitution` | 3 — retired code → successor | baseline re-key | inside `actuals_queryset_with_net()` after scheme + outlier netting |
| `ItemDiscontinuation` | 1 — item withdrawn | forecast-output filter | at `write_forecast_lines` (nil on/after `effective_from`) |
| `ItemIntroduction` | 2 — new item borrows a reference forecast | forecast-output copy | at `write_forecast_lines` (reference × `ratio`, window-bounded) |

All three are gated by one `ForecastingConfig.use_item_lifecycle` flag (default `True`) and one
`item_lifecycle` `ClientFeatureControl` key. A single item holds **one** lifecycle subject role
(old_item / new_item of substitution, discontinued item, or introduction new_item).

---

## Phase 1 — Models, Config & Wiring

### Step 1.1 — Create `mysite/models/demand/lifecycle.py`

A new small module for the item-lifecycle cluster (its own concern, like `schemes.py`). Three models
share a validation helper that keeps subject roles pairwise-exclusive and chains impossible.

```python
from decimal import Decimal
from django.db import models
from django.db.models import Q, CheckConstraint
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def _assert_subject_role_free(client_id, item_id, exclude_model=None, exclude_pk=None):
    """One lifecycle directive per item: an item may hold exactly ONE subject role."""
    from mysite.models.demand.lifecycle import (ItemSubstitution, ItemDiscontinuation,
                                                ItemIntroduction)
    checks = (
        (ItemSubstitution, "old_item_id"),
        (ItemSubstitution, "new_item_id"),
        (ItemDiscontinuation, "item_id"),
        (ItemIntroduction, "new_item_id"),
    )
    for model, field in checks:
        if model is exclude_model:
            continue
        if (model.objects.filter(client_id=client_id, **{field: item_id})
                          .exclude(pk=exclude_pk).exists()):
            raise ValidationError(
                _("One lifecycle directive per item: this item already holds another role."))


class ItemSubstitution(models.Model):
    """Scenario 3 — retired item code -> successor item code, with unit conversion.

    The successor's forecast series is its OWN netted actuals PLUS the
    predecessor's netted actuals converted by conversion_factor, for
    periods before effective_from. Applied as a live re-key JOIN in
    actuals_queryset_with_net() (nothing is materialized).
    Direct mapping only: an item may never be both a predecessor and a
    successor across rows (no chains, no cycles).
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_substitutions")
    old_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="substituted_by")
    new_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="successor_of")
    # Units of NEW per unit of OLD. 2 old = 1 new  ->  0.5.
    # Applies identically to qty and revenue (per-unit price preserved).
    conversion_factor = models.DecimalField(
        _("conversion factor"), max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text=_("new_qty = old_qty x factor; new_revenue = old_revenue x factor. "
                    "2 old units = 1 new unit -> 0.5."),
    )
    # Launch date of the successor. Old-item actuals with period_start <
    # effective_from are converted; rows on/after it stay with the old item
    # (which is forecast as nil on/after this date).
    effective_from = models.DateField(
        _("effective from"), null=True, blank=True,
        help_text=_("Successor launch date. Old actuals BEFORE this date convert to new_item "
                    "(null = convert the entire old history). Exclusive cutoff."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "old_item")]
        indexes = [
            models.Index(fields=["client", "old_item"], name="ix_itemsubst_old"),
            models.Index(fields=["client", "new_item"], name="ix_itemsubst_new"),
        ]
        constraints = [
            CheckConstraint(
                check=Q(conversion_factor__gt=0), name="itemsubst_factor_positive"),
        ]
        verbose_name = _("02-05D Item Substitution")

    def clean(self):
        if self.old_item_id == self.new_item_id:
            raise ValidationError(_("old_item and new_item must differ."))
        if self.old_item_id and self.old_item.client_id != self.client_id:
            raise ValidationError(_("old_item must belong to the same client."))
        if self.new_item_id and self.new_item.client_id != self.client_id:
            raise ValidationError(_("new_item must belong to the same client."))
        if self.conversion_factor is not None and self.conversion_factor <= 0:
            raise ValidationError(_("conversion_factor must be > 0."))
        # Direct mapping only: an item may not be BOTH a predecessor and a
        # successor across substitution rows (kills chains AND cycles).
        if (ItemSubstitution.objects
                .filter(client_id=self.client_id, old_item_id=self.new_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: new_item may not itself be an old_item "
                "of another substitution."))
        if (ItemSubstitution.objects
                .filter(client_id=self.client_id, new_item_id=self.old_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: old_item may not itself be a new_item "
                "of another substitution."))
        # One lifecycle directive per item: neither subject may hold another role.
        if self.old_item_id:
            _assert_subject_role_free(self.client_id, self.old_item_id, self.__class__, self.pk)
        if self.new_item_id:
            _assert_subject_role_free(self.client_id, self.new_item_id, self.__class__, self.pk)


class ItemDiscontinuation(models.Model):
    """Scenario 1 — item withdrawn from an effective date.

    The item keeps its full history (it feeds reporting/ABC/accuracy) but its
    forecast is NIL on/after effective_from: write_forecast_lines emits no
    line for horizon periods with period_start >= effective_from. Periods
    before it forecast normally from the item's own history.
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_discontinuations")
    item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                             related_name="discontinuations")
    # Withdrawal date. NULL = nil forecast from the current run onward.
    effective_from = models.DateField(
        _("effective from"), null=True, blank=True,
        help_text=_("Forecast is nil on/after this date; periods before it forecast normally. "
                    "Null = nil forecast immediately."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "item")]
        indexes = [
            models.Index(fields=["client", "item"], name="ix_itemdisc_item"),
        ]
        verbose_name = _("02-05D Item Discontinuation")

    def clean(self):
        if self.item_id and self.item.client_id != self.client_id:
            raise ValidationError(_("item must belong to the same client."))
        _assert_subject_role_free(self.client_id, self.item_id, self.__class__, self.pk)


class ItemIntroduction(models.Model):
    """Scenario 2 — new item with no history borrows a reference item's forecast.

    For horizon periods where the new item has fewer than
    ForecastingConfig.min_history_periods own actual periods AND the period is
    inside [copy_from, copy_to] (NULL bounds: copy_from -> borrow from launch,
    copy_to -> borrow until enough own history), the new item's ForecastLine is
    set to the reference item's statistical line x ratio, tagged
    borrowed_from_item / borrowed_ratio. Reference item is NOT retired.
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_introductions")
    new_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="introduction_of")
    reference_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                       related_name="referenced_by")
    # Units of NEW per unit of REFERENCE. Applies identically to qty and value.
    ratio = models.DecimalField(
        _("ratio"), max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text=_("new forecast = reference forecast x ratio."),
    )
    copy_from = models.DateField(
        _("copy from"), null=True, blank=True,
        help_text=_("First period to borrow (null = from the new item's launch)."),
    )
    copy_to = models.DateField(
        _("copy to"), null=True, blank=True,
        help_text=_("Last period to borrow (null = until the new item has "
                    "min_history_periods own periods). The copy stops at the "
                    "earlier of copy_to and enough own history."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "new_item")]
        indexes = [
            models.Index(fields=["client", "new_item"], name="ix_itemintro_new"),
            models.Index(fields=["client", "reference_item"], name="ix_itemintro_ref"),
        ]
        constraints = [
            CheckConstraint(check=Q(ratio__gt=0), name="itemintro_ratio_positive"),
        ]
        verbose_name = _("02-05D Item Introduction")

    def clean(self):
        if self.new_item_id == self.reference_item_id:
            raise ValidationError(_("new_item and reference_item must differ."))
        if self.new_item_id and self.new_item.client_id != self.client_id:
            raise ValidationError(_("new_item must belong to the same client."))
        if self.reference_item_id and self.reference_item.client_id != self.client_id:
            raise ValidationError(_("reference_item must belong to the same client."))
        if self.ratio is not None and self.ratio <= 0:
            raise ValidationError(_("ratio must be > 0."))
        if self.copy_from and self.copy_to and self.copy_to < self.copy_from:
            raise ValidationError(_("copy_to must be >= copy_from."))
        # No reference chains: new_item may not itself be another intro's
        # reference_item, nor a substitution/discontinuation subject.
        if (ItemIntroduction.objects
                .filter(client_id=self.client_id, reference_item_id=self.new_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: new_item may not itself be a reference_item "
                "of another introduction."))
        _assert_subject_role_free(self.client_id, self.new_item_id, self.__class__, self.pk)
```

Migration + checkpoint:

```bash
python manage.py makemigrations mysite -n add_item_lifecycle
python manage.py migrate
python manage.py check   # 0 issues
```

### Step 1.2 — `ForecastingConfig` flag

In `mysite/models/demand/forecast.py`, next to the scheme flags (replaces the former
`use_item_substitution`):

```python
    # Item lifecycle (substitution / discontinuation / introduction): re-key
    # retired items' netted actuals to their successor, nil withdrawn items'
    # forecast after their effective date, and copy a reference item's forecast
    # onto a newly introduced item until it has enough own history. One flag for
    # all consumers (forecast, profiles, price, detection, reporting, line-write).
    use_item_lifecycle = models.BooleanField(
        default=True,
        help_text=_("Apply item lifecycle events (substitution re-key, "
                    "discontinuation nil, introduction borrow) when building "
                    "series and writing forecast lines."),
    )
```

### Step 1.3 — Feature key

In `utils/feature_control.py`:

- Add `"item_lifecycle"` to the `demand_planning` frozenset in `_FEATURE_HIERARCHY` (replacing the
  former `"item_substitution"` key).
- Add a thin wrapper mirroring `outlier_ui_visible` / `scheme_ui_visible`:

```python
def item_lifecycle_ui_visible(client) -> bool:
    return not is_feature_disabled(client, "item_lifecycle")["disabled"]
```

### Step 1.4 — Authorization & signals (`mysite/signals.py`)

1. Add `ItemSubstitution`, `ItemDiscontinuation`, `ItemIntroduction` to the model import block and to
   `ADMIN_ONLY_MODELS` (same mechanism as the scheme cluster) — admin-role users get
   `view/add/change/delete_item_substitution|item_discontinuation|item_introduction` on migrate.
2. **No data signal is needed.** The substitution layer is a live JOIN and the output layers read the
   models at write time, so there is nothing to materialize on save/delete (unlike scheme
   resolution). The only receiver worth adding is a *validation* net for the exclusivity /
   direct-mapping rules if rows are ever written outside `clean()` (bulk import paths): optional
   `pre_save` receiver mirroring Step 1.1's role checks.

**Checkpoint:** a non-superuser admin-role user sees all three lifecycle models in Django admin after
migrate; viewer/staff users see none (same auth checkpoint as 3B.2c Step 1.5).

### Step 1.5 — Admin

New module `mysite/admin/demand_lifecycle.py` (mirror `demand_schemes.py`), registered in
`mysite/admin/__init__.py`:

```python
class ItemSubstitutionAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display = ['client', 'old_item', 'new_item', 'conversion_factor',
                    'effective_from', 'updated_at']
    list_filter = ['client']
    search_fields = ['old_item__item_id', 'new_item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

class ItemDiscontinuationAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display = ['client', 'item', 'effective_from', 'updated_at']
    list_filter = ['client']
    search_fields = ['item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

class ItemIntroductionAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display = ['client', 'new_item', 'reference_item', 'ratio',
                    'copy_from', 'copy_to', 'updated_at']
    list_filter = ['client']
    search_fields = ['new_item__item_id', 'reference_item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    # Item FKs use raw_id_fields for 10K-item clients and limit_choices_to
    # {"client_id": <row client>} where feasible.
```

Add `use_item_lifecycle` to the `ForecastingConfigAdmin` fieldset (replacing `use_item_substitution`).

---

## Phase 2 — Baseline Re-key Layer (Substitution — Scenario 3)

### Step 2.1 — Extend `actuals_queryset_with_net`

In `utils/demand/actuals_net.py`, add the `use_substitution` parameter and a re-key layer that runs
AFTER the netting annotations. At most one substitution row matches each ActualSale (unique
`(client, old_item)`), so a correlated `Subquery` keeps one row per ActualSale — same shape as the
scheme netting annotations.

```python
from django.db.models import Case, CharField, DecimalField, F, IntegerField, Q, Subquery, Value, When
from django.db.models.functions import Coalesce

def actuals_queryset_with_net(client, use_net: bool, use_substitution: bool = False):
    """ActualSale queryset with net_qty/net_revenue, plus an optional
    item-substitution re-key.

    When use_substitution is True each row additionally carries:
      eff_item_id / eff_item_code  — the item the row should be keyed to
        (successor when the row converts, the row's own item otherwise)
      net_qty / net_revenue        — already scaled by conversion_factor when
        the row converts (effective/effective values)
    The effective-from rule is exclusive: a row converts only when
    period_start < effective_from (or effective_from is NULL). Rows on/after
    the launch date stay with the old item, unconverted.
    """
    from mysite.models.demand.lifecycle import ItemSubstitution
    from mysite.models.demand.actuals import ActualSale

    qs = ActualSale.objects.filter(client=client).select_related("outlier_adjustment")

    if not use_net:
        qs = qs.annotate(net_qty=F("qty"), net_revenue=F("revenue"))
    else:
        qs = qs.annotate(
            net_qty=Case(
                When(outlier_adjustment__status="CONFIRMED",
                     then=F("qty") - F("outlier_adjustment__qty_adjustment")),
                default=F("qty"),
                output_field=DecimalField(max_digits=14, decimal_places=3)),
            net_revenue=Case(
                When(outlier_adjustment__status="CONFIRMED",
                     then=F("revenue") - Coalesce(
                         F("outlier_adjustment__revenue_adjustment"), Value(0))),
                default=F("revenue"),
                output_field=DecimalField(max_digits=16, decimal_places=2)),
        )

    if use_substitution:
        sub = (ItemSubstitution.objects
               .filter(client_id=OuterRef("client_id"),
                       old_item_id=OuterRef("item_id"))
               .annotate(new_code=Coalesce("new_item__item_id", Value("")))
               .values("new_item_id", "new_code", "conversion_factor", "effective_from"))
        converts = (Q(sub_new_id__isnull=False)
                    & (Q(sub_eff_from__isnull=True)
                       | Q(period_start__lt=F("sub_eff_from"))))
        qs = (qs.annotate(
            sub_new_id=Subquery(sub.values("new_item_id")[:1]),
            sub_new_code=Subquery(sub.values("new_code")[:1]),
            sub_factor=Subquery(sub.values("conversion_factor")[:1]),
            sub_eff_from=Subquery(sub.values("effective_from")[:1]),
        ).annotate(
            eff_item_id=Coalesce(
                Case(When(converts, then=F("sub_new_id")),
                     default=None, output_field=IntegerField()),
                F("item_id")),
            eff_item_code=Coalesce(
                Case(When(converts, then=F("sub_new_code")),
                     default=None, output_field=CharField(max_length=64)),
                F("item__item_id")),
            net_qty=F("net_qty") * Coalesce(
                Case(When(converts, then=F("sub_factor")),
                     default=None, output_field=DecimalField(max_digits=14, decimal_places=6)),
                Value(1), output_field=DecimalField(max_digits=14, decimal_places=6)),
            net_revenue=F("net_revenue") * Coalesce(
                Case(When(converts, then=F("sub_factor")),
                     default=None, output_field=DecimalField(max_digits=14, decimal_places=6)),
                Value(1), output_field=DecimalField(max_digits=16, decimal_places=2)),
        ))

    return qs
```

Notes:
- `OuterRef`/`CharField` must be imported. The `converts` condition is evaluated per row in SQL; when
  the subquery is empty (`sub_new_id` NULL) nothing converts.
- The scaling composes correctly with scheme netting because substitution is the LAST layer — the
  incoming `net_qty`/`net_revenue` are already scheme- and outlier-netted.
- When `use_substitution` is False the annotation set is byte-for-byte identical to today (identity),
  so the flag is a clean opt-in.

### Step 2.2 — Re-key consumers to the effective item

All three consumers switch their grain keys from `item_id`/`item__item_id` to `eff_item_id` /
`eff_item_code` and pass `use_substitution=cfg.use_item_lifecycle`. Nothing else downstream
changes — `unique_id`, grouping, and price math all operate on the effective item.

1. **`build_actuals_dataframe`** (`utils/demand/forecast_engine.py`):
   - Call `actuals_queryset_with_net(client, use_net, use_substitution=bool(cfg.use_item_lifecycle))`.
   - `.values(...)` picks `eff_item_id`, `eff_item_code` (replace `item_id`, `item__item_id`).
   - `unique_id` is built from `eff_item_code`; group keys use `eff_item_id` / `eff_item_code`.
   - Netting rename `net_qty→qty`, `net_revenue→revenue` is unchanged.
2. **`update_weighted_avg_prices`** (`utils/demand/forecast_engine.py`):
   - Same flag; aggregate on `eff_item_id` so the successor's weighted price covers converted history
     (`sum(net_revenue)/sum(net_qty)` over the merged series). The retired item's blended price updates
     only from its post-launch (unconverted) rows — expected.
3. **`compute_series_profiles._load_actuals`** (`utils/demand/compute_series_profiles.py`):
   - Same flag; `values()` uses `eff_item_id` + `net_qty` so classification sees the merged series and
     the successor inherits a sensible grain/model decision from predecessor volume.

**Checkpoint (fixture):** A=12 monthly periods (qty 100 each, revenue 1000 each), B launched
`effective_from = month 10`, `conversion_factor = 0.5`:

```bash
python manage.py test mysite.tests.demand.test_item_substitution
```

- B's matrix rows: months 1–9 = 50 qty / 500 revenue (A×0.5), months 10–12 = B's own actuals.
- If A also has months 10–12 rows, they stay keyed to A (unconverted), never summed into B.
- A produces **no forecast** on/after month 10.
- `use_item_lifecycle=False` → A and B rows untouched (identity).

---

## Phase 3 — Forecast-Output Layers (Discontinuation + Introduction — Scenarios 1 & 2)

### Step 3.1 — `ForecastLine` borrowed-line columns

Migration adding two nullable columns so borrowed lines are transparent to planners:

```python
# mysite/models/demand/forecast.py, on ForecastLine
    borrowed_from_item = models.ForeignKey(
        "mysite.Item", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+", help_text=_("Reference item whose forecast was copied "
                                      "onto this line (ItemIntroduction)."),
    )
    borrowed_ratio = models.DecimalField(
        _("borrowed ratio"), max_digits=14, decimal_places=6, null=True, blank=True,
        help_text=_("Ratio applied to the reference forecast (qty and value)."),
    )
```

```bash
python manage.py makemigrations mysite -n add_borrowed_forecast_columns
python manage.py migrate
```

### Step 3.2 — Discontinuation filter in `write_forecast_lines`

In the forecast pipeline (after the statistical run / before `ForecastAggregate` roll-ups), load the
client's discontinuations once and suppress lines on/after `effective_from`. The pre-cutoff horizon
and every non-discontinued item are untouched.

```python
from mysite.models.demand.lifecycle import ItemDiscontinuation

def _load_discontinuation_cutoffs(client_id):
    """{item_id: effective_from-or-sentinel}; effective_from NULL = suppress all."""
    return {d.item_id: d.effective_from
            for d in ItemDiscontinuation.objects.filter(client_id=client_id)}

def _is_discontinued(item_id, period_start, cutoffs):
    cutoff = cutoffs.get(item_id)
    if cutoff is None and item_id not in cutoffs:
        return False
    return cutoff is None or period_start >= cutoff
```

In `write_forecast_lines(version_id, ...)`, when `cfg.use_item_lifecycle`:
- `cutoffs = _load_discontinuation_cutoffs(client_id)`
- Skip any candidate `ForecastLine` where `_is_discontinued(line.item_id, line.period_start,
  cutoffs)` is True — no line is written for that (item, period), i.e. the forecast is nil.

Also apply the same rule to the **retired old_item of a substitution**: `effective_from` from the
substitution row suppresses that item's own forecast on/after the launch date (the successor owns the
demand). Load the substitution cutoffs alongside discontinuation cutoffs:

```python
from mysite.models.demand.lifecycle import ItemSubstitution
sub_cutoffs = {s.old_item_id: s.effective_from
               for s in ItemSubstitution.objects.filter(client_id=client_id)}
cutoffs = {**sub_cutoffs, **discontinuation_cutoffs}
```

### Step 3.3 — Introduction borrow in `write_forecast_lines`

After the discontinuation filter and the statistical run, when `cfg.use_item_lifecycle`, apply the
borrow per `ItemIntroduction` row. The borrow needs (a) the new item's own-period count per leaf grain
before each horizon period, and (b) the reference item's statistical lines for the same periods.

```python
from mysite.models.demand.lifecycle import ItemIntroduction

def _own_history_period_count(client_id, item_id, period_type, before_date, grains):
    """Number of distinct own actual periods < before_date at each leaf grain."""
    # Count distinct ActualSale periods for the item at (planning_location,
    # distribution_channel, planning_customer), capped at min_history_periods.
    ...

def apply_introduction_borrows(client_id, cfg, version, lines_by_grain, reference_lines):
    """Overwrite/backfill new-item lines with reference x ratio where borrowed."""
    min_hist = cfg.min_history_periods
    for intro in (ItemIntroduction.objects.filter(client_id=client_id)
                                          .select_related("reference_item")):
        for grain, line in lines_by_grain[intro.new_item_id].items():
            period_start = line.period_start
            if intro.copy_from and period_start < intro.copy_from:
                continue
            if intro.copy_to and period_start > intro.copy_to:
                continue
            own = _own_history_period_count(client_id, intro.new_item_id,
                                            line.period_type, period_start, grain)
            if own >= min_hist:
                continue  # enough own history — the new item forecasts itself
            ref = reference_lines.get((intro.reference_item_id, grain, period_start))
            if ref is None:
                continue  # no reference line at this grain/period -> no borrowed line
            line.statistical_qty = ref.statistical_qty * intro.ratio
            line.statistical_value = (ref.statistical_value * intro.ratio
                                      if ref.statistical_value is not None else None)
            line.borrowed_from_item_id = intro.reference_item_id
            line.borrowed_ratio = intro.ratio
            line.model_used = "BORROWED"  # keep model provenance honest
```

The reference's statistical lines are read from the same run's built lines (or the composed baseline
for the reference at the same grains). `ForecastAggregate` roll-ups then naturally include the
borrowed qty/value because they roll up the (now populated) `ForecastLine` rows. Lines that are not
borrowed keep their own statistical values; the new item's own sparse series (when it has any history)
is only overridden while inside the window *and* below `min_history_periods`.

**Checkpoint (fixtures):**

```bash
python manage.py test mysite.tests.demand.test_item_lifecycle
```

- Discontinuation: item D has 12 periods of history, `effective_from = month 10`; horizon months 10–12
  produce no `ForecastLine` (nil), months 1–9 forecast normally; `effective_from = NULL` → no forecast
  at all.
- Introduction: new item N (no history), reference R with `ratio = 0.5`, `copy_from = launch`;
  `min_history_periods = 6`; N's lines for months 1–6 = R×0.5 with `borrowed_from_item=R`,
  `borrowed_ratio=0.5`; from month 7 (≥ 6 own periods) N's own statistical forecast takes over; with
  `copy_to` set, the borrow stops at `copy_to` even if own history is still short.
- `use_item_lifecycle=False` → no borrowed lines, no discontinuity suppression.

---

## Phase 4 — Detection & Reporting

### Step 4.1 — Detection skip rules

In `mysite/tasks/demand/detect_outliers.py`, `run_outlier_detection`:

1. Load the set of `old_item_id`s from `ItemSubstitution` for the client (direct-mapping guarantee:
   each retired code is unique). Exclude those items from candidate generation — their history is
   owned by the successor and already carries its confirmed adjustments.
2. **Do NOT skip discontinued items** — their history belongs to nobody and still feeds
   reporting/ABC/accuracy; their own spikes remain detectable (contrast with substitution old_items).
3. The **successor**'s detection series is read through the composed helper with
   `use_substitution=cfg.use_item_lifecycle`, so it sees the merged (converted) history; spikes that
   were already netted on the retired code do not re-appear.

Reporting and ABC classification already share the helper — pass
`use_substitution=cfg.use_item_lifecycle` at their call sites so the merged series is consistent
everywhere (same flag, default True). The introduction borrow never affects detection (it is a
forecast-output, not baseline).

**Checkpoint:** a raw spike in A's pre-launch history is NOT proposed as a B candidate when A's spike
was already outlier-netted; no candidate is ever proposed for the retired A; a spike in a discontinued
item's own history IS still proposed; the actuals dashboard honours the flag.

---

## Phase 5 — HTMX UI + Tests

### Step 5.1 — Views (`mysite/demand_ui/views.py` + templates)

- `item_substitution_list` / `item_substitution_create` / `item_substitution_edit` — substitution rows
  (old → new, factor, effective_from).
- `item_discontinuation_list` / `item_discontinuation_create` / `item_discontinuation_edit` — item,
  effective_from.
- `item_introduction_list` / `item_introduction_create` / `item_introduction_edit` — new_item,
  reference_item, ratio, copy_from, copy_to.
- Forms surface each model's `clean()` errors inline. Templates under
  `templates/demand/lifecycle/` (extend `_base_demand.html`); nav link gated on
  `item_lifecycle_ui_visible`. URLs under `/planning/`; no DRF endpoints.

**Checkpoint:** a planner creates `A→B (0.5, effective_from=...)`, `D (effective_from=...)`, and
`N←R (0.5, copy_from=..., copy_to=...)` from the UI; a forecast run for B shows converted A history,
for D shows nil after its date, and for N shows borrowed R lines; toggling the feature key hides all
three sections.

### Step 5.2 — Test suite (`mysite/tests/demand/test_item_lifecycle.py`)

- Models: `conversion_factor`/`ratio <= 0`, cross-client, old==new / new==reference, inverted
  `copy_to < copy_from`, duplicated `(client, subject)`, direct-mapping violations (item already a
  `new_item` / already an `old_item` / already a `reference_item`), and mixed subject roles (item
  already used by another event type) → all raise.
- Helper (Phase 2): 2-old = 1-new fixture → converted qty/revenue; `effective_from` cutoff (on/after
  excluded); NULL `effective_from` converts everything; identity when flag off; composition with
  scheme+outlier netting (netted values scale, not raw).
- Consumers (Phase 2): B's forecast matrix and weighted price = merged series; A's post-launch rows
  stay A; A's forecast nil after launch; `compute_series_profiles` picks B's decision from merged
  history.
- Output layers (Phase 3): discontinuation nil on/after date (and NULL → all); introduction borrow
  with window + own-history stop conditions + `borrowed_from_item`/`borrowed_ratio` attribution;
  reference lines untouched; aggregate roll-up includes borrowed values; identity when flag off.
- Detection (Phase 4): retired A never proposed; B's merged-series spike handled normally; a
  discontinued item's spike still proposed.
- Feature gate: `item_lifecycle_ui_visible()` respects parent `demand_planning`.

---

## Verification (full sprint)

```bash
python manage.py check
python manage.py test mysite.tests.demand.test_item_lifecycle \
    mysite.tests.demand.test_item_substitution \
    mysite.tests.demand.test_actuals_net \
    mysite.tests.demand.test_forecast_engine \
    mysite.tests.demand.test_compute_series_profiles \
    mysite.tests.demand.test_outlier_detection
```

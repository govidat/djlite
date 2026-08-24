# Execution Instructions — Sales Promotion Scheme Management (Sprint 3B.2c)

This is a build runbook for Phases 1–6 of the project plan. Each phase lists the exact files to touch,
the order to touch them in, and a checkpoint to verify before moving on. Code shown is illustrative —
adapt names/paths to match your actual app layout, but the shapes (fields, signatures, signal wiring)
should be followed closely since later phases depend on them.

**Ordering invariant (non-negotiable):** `baseline = Actuals − scheme impact − outlier`. The scheme layer
nets first; outlier detection runs on scheme-netted series. Every consumer of actuals (forecast engine,
series profiles, price update, outlier detection, reporting, ABC) reads the same composed baseline
helper — never two different definitions of "net".

---

## Phase 1 — Data Model, Scope Resolution & Config

### Step 1.1 — Create `mysite/models/demand/schemes.py`

A new module for the scheme cluster (kept out of `actuals.py` — it is a distinct concern; the 1:1
outlier model that lives there is too small to justify this split, this cluster is not).

```python
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Scope types mirror VendorSchemeScope from Phase 3C. BRAND is the "vendor" of the
# scheme: the vendor is the Brand, and the brand→item link lives in the item taxonomy
# (not the planning product hierarchy). See SCOPE resolution notes below.
SCOPE_TYPE_CHOICES = [
    ("OVERALL",  _("Overall")),
    ("TAXONOMY", _("Product group (planning product hierarchy)")),
    ("BRAND",    _("Brand (item taxonomy Brand node)")),
    ("ITEM",     _("Specific item")),
]

SCHEME_STATUS_CHOICES = [
    ("DRAFT",    _("Draft")),
    ("ACTIVE",   _("Active")),
    ("ARCHIVED", _("Archived")),
]


class SalesScheme(models.Model):
    """A planned or historical sales promotion scheme.

    A single scheme covers BOTH historical and future periods: each
    SalesSchemePeriod whose bucket is in the past nets actuals; each period
    whose bucket falls in the forecast horizon re-adds uplift. No separate
    future/historical flag is needed.
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="sales_schemes")
    scheme_code = models.CharField(_("scheme code"), max_length=30)
    name = models.CharField(_("name"), max_length=120)
    status = models.CharField(_("status"), max_length=16,
                              choices=SCHEME_STATUS_CHOICES, default="DRAFT")

    # ── Economic inputs (planner-entered) ────────────────────────────────
    # Independent by design: a 1-for-1 scheme is qty_uplift=1.00, value_uplift=0.00
    # (qty doubles, revenue flat). Never derive value uplift from qty uplift.
    expected_qty_uplift_pct = models.DecimalField(
        _("expected qty uplift %"), max_digits=7, decimal_places=4, default=Decimal("0"),
        help_text=_("Expected % increase in qty vs a no-scheme period. 1.00 = double."),
    )
    expected_value_uplift_pct = models.DecimalField(
        _("expected value uplift %"), max_digits=7, decimal_places=4, default=Decimal("0"),
        help_text=_(
            "Expected % change in revenue vs a no-scheme period, entered independently "
            "of qty uplift. 1-for-1: 0.00 (qty doubles, revenue flat). Must be > -1.00."
        ),
    )
    # Metadata only — informational / may pre-fill a default value uplift, never
    # authoritative for netting.
    discount_pct = models.DecimalField(
        _("discount %"), max_digits=7, decimal_places=4, null=True, blank=True,
        help_text=_("Informational. May pre-fill expected_value_uplift_pct on create."),
    )

    # ── Pre/post shadow (pull-forward) ────────────────────────────────────
    # IN SCOPE for 3B.2c. A fraction of the netted-out window uplift is treated
    # as pulled forward from neighbouring periods. shadow_periods = 0 disables
    # the shadow for this scheme (backwards compatible).
    shadow_periods = models.PositiveSmallIntegerField(
        _("shadow periods"), default=0,
        help_text=_("Buckets on each side of the window that are depressed by pull-forward. 0 = off."),
    )
    pull_forward_pct = models.DecimalField(
        _("pull-forward %"), max_digits=7, decimal_places=4, default=Decimal("0.5"),
        help_text=_(
            "Fraction of the window's netted-out uplift that was pulled from neighbouring periods "
            "(rest is incremental). Re-added to history, dipped on the horizon. Calibrated from "
            "occurrences. Must be in [0, 1]."
        ),
    )

    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "scheme_code")]
        verbose_name = _("02-05C Sales Promotion Scheme")
        verbose_name_plural = _("02-05C Sales Promotion Schemes")

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.expected_qty_uplift_pct is not None and self.expected_qty_uplift_pct < 0:
            raise ValidationError({"expected_qty_uplift_pct": _("Cannot be negative.")})
        if self.expected_value_uplift_pct is not None and self.expected_value_uplift_pct <= Decimal("-1"):
            raise ValidationError({"expected_value_uplift_pct":
                _("Must be greater than -1.00 (a scheme cannot erase more than all revenue).")})
        if self.pull_forward_pct is not None and not (Decimal("0") <= self.pull_forward_pct <= Decimal("1")):
            raise ValidationError({"pull_forward_pct": _("Must be between 0 and 1.")})


class SalesSchemeScope(models.Model):
    """Which items/locations/customers/channels a scheme covers.

    TAXONOMY scope = every item in the planning product-hierarchy node's subtree
    (materialized-path LIKE query), mirroring how compute_series_profiles/taxon_*
    grains resolve membership. BRAND scope = every item mapped beneath a Brand node
    in the client's item taxonomy (the scheme's "vendor"); membership is the UNION
    of all ItemTaxonomyNode mappings under that node, so items spread across
    multiple planning product groups are all covered. ITEM scope = the exact item.
    Null dims mean "all".

    Membership is resolved tree-aware: each scope row expands from ITS OWN node's
    taxonomy subtree (see resolve_scheme_scope Step 2), not the planning hierarchy
    only. The planning-grain helper (_taxon_node_item_ids) stays untouched for
    forecast grains; scheme membership uses its own union resolver.
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="scopes")
    scope_type = models.CharField(_("scope type"), max_length=16,
                                  choices=SCOPE_TYPE_CHOICES)
    taxonomy_node = models.ForeignKey("mysite.TaxonomyNode", null=True, blank=True,
                                      on_delete=models.CASCADE, related_name="+")
    item = models.ForeignKey("mysite.Item", null=True, blank=True,
                             on_delete=models.CASCADE, related_name="+")
    planning_location = models.ForeignKey("mysite.demand.PlanningLocation", null=True, blank=True,
                                          on_delete=models.CASCADE, related_name="+")
    planning_customer = models.ForeignKey("mysite.demand.PlanningCustomer", null=True, blank=True,
                                          on_delete=models.CASCADE, related_name="+")
    distribution_channel = models.ForeignKey("mysite.demand.DistributionChannel", null=True, blank=True,
                                             on_delete=models.CASCADE, related_name="+")

    class Meta:
        app_label = "mysite"
        unique_together = [("scheme", "scope_type", "taxonomy_node", "item",
                            "planning_location", "planning_customer", "distribution_channel")]
        verbose_name = _("02-05C Sales Scheme Scope")

    def clean(self):
        # BRAND scoping is gated on the brand-taxonomy prerequisite.
        if self.scope_type == "BRAND":
            if not self.taxonomy_node_id:
                raise ValidationError(_("A BRAND scope must target a Brand node."))
            from mysite.models.demand.forecast import ForecastingConfig
            from mysite.models import Taxonomy, TaxonomyNode
            cfg = ForecastingConfig.get_for_client_id(self.scheme.client_id)
            slug = (cfg.brand_taxonomy or "").strip()
            if not slug:
                raise ValidationError(_(
                    "Brand scoping requires ForecastingConfig.brand_taxonomy to be set "
                    "for this client (no brand taxonomy configured)."))
            brand_tax = (Taxonomy.objects
                         .filter(Q(client_id=self.scheme.client_id) | Q(client=None), slug=slug)
                         .order_by('-client_id').first())
            if brand_tax is None or self.taxonomy_node.taxonomy_id != brand_tax.id:
                raise ValidationError(_(
                    "The BRAND scope node must belong to the client's configured brand taxonomy."))
            if not self.taxonomy_node.item_mappings.filter(
                    item__client_id=self.scheme.client_id).exists():
                raise ValidationError(_(
                    "The brand taxonomy is configured but no items are mapped beneath "
                    "this Brand node — set up the brand→item mappings first."))
        elif self.scope_type in ("TAXONOMY", "OVERALL"):
            if not self.taxonomy_node_id:
                raise ValidationError(_("A TAXONOMY/OVERALL scope must target a taxonomy node."))
        elif self.scope_type == "ITEM":
            if not self.item_id:
                raise ValidationError(_("An ITEM scope must target an item."))


class SalesSchemePeriod(models.Model):
    """One bucket covered by a scheme, at the forecast period_type.

    period_end auto-computed via compute_period_end, same as ActualSale.
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="periods")
    period_type = models.CharField(max_length=16, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField(_("period start"))
    period_end = models.DateField(_("period end"), editable=False)

    class Meta:
        app_label = "mysite"
        unique_together = [("scheme", "period_type", "period_start")]

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)


class ResolvedSalesSchemePeriod(models.Model):
    """Materialized scheme→actuals coverage, keyed to the ActualSale grain.

    Two row kinds per (scheme, item, location, customer, channel):

    * WINDOW row (is_shadow=False) — one per SalesSchemePeriod bucket. Carries
      qty_factor/value_factor = 1 + uplift. Netting DIVIDES by these.
    * SHADOW rows (is_shadow=True) — 2 × shadow_periods per WINDOW row, one
      bucket before/after the window. Netting ADDS BACK (history) or DIPS
      (horizon) a share of the window's uplift:
        addback = window_qty × (1 − 1/anchor_qty_factor) × addback_qty_weight
      anchor_*_factor copies the window's factors so each shadow row is
      self-describing; addback_weight = pull_forward_pct × side_share ×
      decay_weight(j) (pre/post share 50/50, exponential decay 1/2^j
      normalized per side).

    Built by resolve_scheme_scope on scheme save/approval. This is what makes
    query-time netting a plain LEFT JOIN — no per-row taxonomy-subtree
    computation at read time. The resolver pattern (materialize on change,
    join at read) is the same one already established by ResolvedVendorScheme /
    ResolvedSupplySource in 3C.
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="resolved_periods")
    item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE, related_name="+")
    planning_location = models.ForeignKey("mysite.demand.PlanningLocation",
                                          on_delete=models.CASCADE, related_name="+")
    planning_customer = models.ForeignKey("mysite.demand.PlanningCustomer",
                                          null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    distribution_channel = models.ForeignKey("mysite.demand.DistributionChannel",
                                             on_delete=models.CASCADE, related_name="+")
    period_type = models.CharField(max_length=16)
    period_start = models.DateField()
    period_end = models.DateField()

    # ── Window fields (WINDOW rows only) ──────────────────────────────────
    qty_factor = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))
    value_factor = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"))

    # ── Shadow fields (SHADOW rows only) ──────────────────────────────────
    is_shadow = models.BooleanField(default=False)
    shadow_side = models.CharField(max_length=4, choices=[("PRE", _("Pre")), ("POST", _("Post"))],
                                   null=True, blank=True)
    shadow_offset = models.PositiveSmallIntegerField(null=True, blank=True)
    anchor_period_start = models.DateField(null=True, blank=True)  # the window bucket this borrows from
    anchor_qty_factor = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    anchor_value_factor = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    addback_qty_weight = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text=_("pull_forward_pct × side_share × decay_weight(j)"),
    )
    addback_value_weight = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text=_("Same weight as addback_qty_weight; the anchor_value_factor drives the value add-back."),
    )

    class Meta:
        app_label = "mysite"
        unique_together = [("scheme", "item", "planning_location", "planning_customer",
                            "distribution_channel", "period_type", "period_start",
                            "is_shadow", "shadow_side", "anchor_period_start")]
        indexes = [
            models.Index(fields=["item", "planning_location", "distribution_channel",
                                 "planning_customer", "period_start", "period_type"],
                         name="ix_resolvedschemepen_grain"),
            models.Index(fields=["is_shadow", "period_type", "period_start"],
                         name="ix_resolvedschemepen_shadow"),
        ]


class SalesSchemeOccurrence(models.Model):
    """Closed-scheme record: actual uplift measured independently from actuals.

    Drives the data-check (actual vs expected) and future uplift estimation
    (median of the last few occurrences).
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="occurrences")
    period_type = models.CharField(max_length=16)
    period_start = models.DateField()
    period_end = models.DateField(editable=False)
    actual_qty_uplift_pct = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    actual_value_uplift_pct = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)
    actual_pull_forward_pct = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True,
        help_text=_("Empirically estimated pull-forward: fraction of the window uplift that appears "
                    "missing from the neighbouring (shadow) periods. Calibrates SalesScheme.pull_forward_pct."),
    )
    qty_uplift_variance = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    value_uplift_variance = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    pull_forward_variance = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("scheme", "period_type", "period_start")]
```

Add the imports at the top of `schemes.py`:

```python
from decimal import Decimal
from mysite.models.demand.actuals import (
    ActualSale, ActualSaleOutlierAdjustment, PERIOD_TYPE_CHOICES, compute_period_end,
)
```

Shadow weight helpers (single source of truth for both the resolver and the horizon factor builder):

```python
SHADOW_DECAY = Decimal("0.5")      # weight(j) ∝ decay ** j
SHADOW_PRE_SHARE = Decimal("0.5")  # pre/post split of the pulled volume

def shadow_weights(shadow_periods):
    """Return [(j, weight) ...] with per-side weights normalized to 1."""
    raw = [SHADOW_DECAY ** j for j in range(1, shadow_periods + 1)]
    total = sum(raw, Decimal("0"))
    return [(j, w / total) for j, w in zip(range(1, shadow_periods + 1), raw)]

def addback_weight(pull_forward_pct, side, j, shadow_periods):
    """Composite weight stored on a shadow row = pf × side_share × w_j."""
    share = SHADOW_PRE_SHARE if side == "PRE" else (Decimal("1") - SHADOW_PRE_SHARE)
    w_j = dict(shadow_weights(shadow_periods))[j]
    return pull_forward_pct * share * w_j
```

Period arithmetic for shadow buckets: PRE bucket `j` = `previous_period_start(period_start,
period_type, j)`; POST bucket `j` = `next_period_start(period_start, period_type, j)`. Add these two
small helpers to `utils/demand/periods.py` (post = iterate `compute_period_end(..., period_type) +
timedelta(days=1)` j times; pre = walk backwards from period_start).

Register the models in `mysite/models/demand/__init__.py` (both import and `__all__`) so they are
available as `mysite.models.demand.SalesScheme` etc.

### Step 1.2 — `ForecastingConfig` scheme flags + `ForecastLine`/`ForecastAggregate` columns

In `mysite/models/demand/forecast.py`, after the outlier netting flags:

```python
    # ── Sales promotion scheme configuration ──────────────────────────────
    scheme_net_actuals = models.BooleanField(
        default=True,
        help_text=_("Net scheme impact out of actuals (baseline = actuals − scheme − outlier)."),
    )
    scheme_apply_forecast_uplift = models.BooleanField(
        default=True,
        help_text=_("Re-add expected uplift to horizon periods covered by an ACTIVE scheme."),
    )
    # detection run-tracking (mirror the outlier fields)
    last_scheme_detection_run_at = models.DateTimeField(null=True, blank=True)
    last_scheme_detection_run_by = models.ForeignKey(
        'auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    last_scheme_detection_range_start = models.DateField(null=True, blank=True)
    last_scheme_detection_range_end = models.DateField(null=True, blank=True)
    # Brand scope prerequisite: names the taxonomy that carries the Brand level
    # (the "vendor" of a scheme). Null = brand scoping unavailable for this client.
    # Mirrors planning_producthierarchy: slug looked up as (client-specific first,
    # then shared). See SalesSchemeScope.clean() + _scheme_scope_item_ids.
    brand_taxonomy = models.CharField(
        _("brand taxonomy slug"), max_length=64, null=True, blank=True,
        help_text=_(
            "Taxonomy slug holding the Brand level used by BRAND scheme scopes. "
            "The scheme's vendor is its Brand; brand→item mappings must exist in "
            "this taxonomy for BRAND scoping to resolve."
        ),
    )
```

On `ForecastLine`, after `final_value`:

```python
    pre_scheme_statistical_qty = models.DecimalField(
        _('pre-scheme statistical qty'), max_digits=14, decimal_places=3, null=True, blank=True,
        help_text=_('Clean baseline quantity before scheme uplift. Engine output.'),
    )
    pre_scheme_statistical_value = models.DecimalField(
        _('pre-scheme statistical value'), max_digits=18, decimal_places=2, null=True, blank=True,
        help_text=_('Clean baseline value before scheme uplift.'),
    )
    scheme_id = models.ForeignKey(
        "mysite.demand.SalesScheme", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
        help_text=_("Scheme whose uplift is applied to this line."),
    )
    scheme_qty = models.DecimalField(
        _('scheme qty uplift'), max_digits=14, decimal_places=3, null=True, blank=True,
        help_text=_('Uplift delta: pre_scheme_statistical_qty × uplift_pct. NULL when no scheme.'),
    )
    scheme_value = models.DecimalField(
        _('scheme value uplift'), max_digits=18, decimal_places=2, null=True, blank=True,
        help_text=_('Value uplift delta. NULL when no scheme.'),
    )
```

Update `statistical_qty` field help_text to:
```python
    statistical_qty = models.DecimalField(
        _('statistical qty'), max_digits=14, decimal_places=3,
        help_text=_('Scheme-adjusted statistical quantity. = pre_scheme_statistical_qty + scheme_qty.'),
    )
```

On `ForecastAggregate`, mirror the clean baseline alongside the existing statistical fields:

```python
    pre_scheme_statistical_qty = models.DecimalField(
        _('pre-scheme statistical qty'), max_digits=14, decimal_places=3, null=True, blank=True,
        help_text=_('Sum of pre_scheme_statistical_qty across constituent lines.'),
    )
    pre_scheme_statistical_value = models.DecimalField(
        _('pre-scheme statistical value'), max_digits=18, decimal_places=2, null=True, blank=True,
        help_text=_('Sum of pre_scheme_statistical_value across constituent lines.'),
    )
```

Add the scheme-detection fields, the two netting flags, and `brand_taxonomy` to `ForecastingConfigAdmin`
fieldsets, and the new line/aggregate columns to the relevant admin displays.

### Step 1.3 — `scheme_management` feature key

In `utils/feature_control.py`:

```python
_FEATURE_HIERARCHY = {
    "demand_planning": frozenset({
        "actuals_upload",
        "forecast_run",
        "consensus_override",
        "forecast_approval",
        "outlier_management",
        "scheme_management",
    }),
    ...
}

def scheme_ui_visible(client) -> bool:
    if client is None:
        return False
    result = is_feature_disabled(client, 'scheme_management')
    return not result['disabled']
```

Seed the `scheme_management` key in the same place your other `ClientFeatureControl` keys are seeded.

### Step 1.4 — `resolve_scheme_scope` Celery task

Create `mysite/tasks/demand/resolve_scheme_scope.py`:

```python
@shared_task
def resolve_scheme_scope(scheme_id):
    """Materialize ResolvedSalesSchemePeriod for one scheme.

    Runs on scheme post_save when status becomes ACTIVE (and on scope/period
    edits). Deletes and rebuilds the scheme's resolved rows in one transaction.
    """
```

Algorithm (illustrative):
1. Load the scheme; bail if status != ACTIVE.
2. For each `SalesSchemeScope`, resolve the item set — **tree-aware, from the scope node's OWN taxonomy**:
   - `OVERALL` → all items for the client (`Item.objects.filter(client=client)`).
   - `TAXONOMY` → `_scheme_scope_item_ids(client_id, taxonomy_node_id)`: the **union** of every item whose
     `ItemTaxonomyNode` mapping descends from the node, resolved within the node's own taxonomy subtree
     (materialized-path `path__startswith` on the node's path). This covers planning product-group rows
     exactly as today AND works unchanged for rows pointing at any other taxonomy tree. The planning-grain
     helper `_taxon_node_item_ids` in `utils/demand/forecast_engine.py` is deliberately NOT reused here —
     it resolves via the planning-hierarchy primary-mapping only and would return zero items for a brand
     node.
   - `BRAND` → `_scheme_scope_item_ids(client_id, taxonomy_node_id)` on the brand node — same union
     resolver; `SalesSchemeScope.clean()` already guarantees the node lives in the configured
     `brand_taxonomy`. Because membership is a union of all mappings, one BRAND row covers items spread
     across many planning product groups.
   - `ITEM` → the single item.
3. **Within-scheme dedup (most-specific-wins)** — a scheme's scope rows can overlap (a BRAND row and a
   TAXONOMY row covering the same item). Collapse the per-scope item sets into a single
   `{item: scope}` map, ordered by specificity `ITEM (3) > BRAND (2) > TAXONOMY (1) > OVERALL (0)`,
   first hit per item wins. This guarantees an item is resolved exactly once per scheme — no double
   factor application. (This is per-scheme; the cross-scheme overlap rule stays in step 7.)
4. For each `(item, scope)`, cross against each `SalesSchemePeriod` and build a
   `ResolvedSalesSchemePeriod` row for every `planning_location` in scope (all locations when the scope
   has no location filter), `distribution_channel` in scope (default `'00'` when unset), and
   `planning_customer` in scope (None when unset).
5. `qty_factor = 1 + expected_qty_uplift_pct`; `value_factor = 1 + expected_value_uplift_pct`; set
   `is_shadow=False` (WINDOW row).
6. **Shadow rows** — if `scheme.shadow_periods > 0`, for each WINDOW row also build `2 × shadow_periods`
   SHADOW rows (is_shadow=True):
   - PRE bucket `j` → `period_start = previous_period_start(window.period_start, period_type, j)`;
     POST bucket `j` → `period_start = next_period_start(window.period_start, period_type, j)`.
   - Copy the window's factors onto `anchor_qty_factor` / `anchor_value_factor`; set
     `anchor_period_start = window.period_start`, `shadow_side`, `shadow_offset = j`, and
     `addback_qty_weight = addback_value_weight = addback_weight(pull_forward_pct, side, j,
     shadow_periods)`. Leave `qty_factor`/`value_factor` NULL on shadow rows (netting must never
     divide on a shadow row).
   - `period_end` auto-computed from the shadow `period_start` + `period_type`.
7. `transaction.atomic()`: `ResolvedSalesSchemePeriod.objects.filter(scheme=scheme).delete()` then
   `bulk_create(rows, batch_size=2000)`.
8. If a (item, location, customer, channel, period) resolves as a WINDOW row under >1 ACTIVE scheme, log
   a warning row (most-specific-wins: ITEM > BRAND > TAXONOMY > OVERALL; ties broken by `scheme_code`).
   This is the Phase 6 overlap path — for now log, don't fail. A period being a window for one scheme AND a
   shadow for another is expected (back-to-back schemes) and additive — no warning.

The union membership helper (new module-level function beside the task):

```python
def _scheme_scope_item_ids(client_id: int, node_id: int) -> tuple[int, ...]:
    """Union of item_ids mapped beneath node in ITS OWN taxonomy tree.

    Tree-aware: membership comes from ItemTaxonomyNode where the mapping node
    descends from `node` (materialized path). Deliberately NOT primary-mapping-only
    — a promo covers the item whether or not the node is its canonical planning
    grain. Used for both TAXONOMY and BRAND scope rows.
    """
    from mysite.models import ItemTaxonomyNode, Item, TaxonomyNode
    node = TaxonomyNode.objects.only("path").get(pk=node_id)
    mapping_node_ids = TaxonomyNode.objects.filter(
        taxonomy_id=node.taxonomy_id, path__startswith=node.path,
    ).values_list("id", flat=True)
    return tuple(
        Item.objects.filter(client_id=client_id, taxonomy_mappings__node_id__in=mapping_node_ids)
        .distinct().values_list("id", flat=True)
    )
```

The `post_save` signal on `SalesScheme` → `resolve_scheme_scope.delay` (gated on status/scope/period
changes) lives in `mysite/signals.py` — see Step 1.5. The review queue's "activate" action calls
`resolve_scheme_scope` directly (or relies on the signal); both paths are idempotent.

Migration + checkpoint:

```bash
python manage.py makemigrations mysite -n add_sales_scheme_models
python manage.py migrate
python manage.py check   # 0 issues
```

**Checkpoint:** a TAXONOMY-scoped, ITEM-scoped, and OVERALL-scoped ACTIVE scheme each materialize the
correct `ResolvedSalesSchemePeriod` WINDOW rows against the fixture actuals; **a BRAND-scoped scheme
materializes the union of items mapped beneath the brand node even though those items sit in different
planning product groups; a scheme with a BRAND row + a TAXONOMY row overlapping the same item resolves
that item once (most-specific-wins) with no duplicate factors; a BRAND row whose brand taxonomy is
unconfigured fails `SalesSchemeScope.clean()`**; a scheme with
`shadow_periods = 2` additionally materializes 2 PRE + 2 POST shadow rows per window with normalized
per-side weights `(4/6, 2/6)` (decay 1/2^j) and NULL `qty_factor`.

### Step 1.5 — Authorization & signals wiring (`mysite/signals.py`)

The scheme cluster is access-controlled by the same Guardian permission-sync machinery as every other
demand model. Two changes in `mysite/signals.py`:

1. **Model permission registration.** Add the five models to the import block
   (`ADMIN_ONLY_MODELS`'s Demand Planning group lives at the top of the file):

   ```python
   from .models import (
       SalesScheme, SalesSchemeScope, SalesSchemePeriod,
       ResolvedSalesSchemePeriod, SalesSchemeOccurrence,
   )
   ```

   and append them to `ADMIN_ONLY_MODELS`:

   ```python
   ADMIN_ONLY_MODELS = [
       ...
       # Demand Planning
       PlanningLocation, PlanningCustomer, SalesNode, SalesForecastLink, ActualSaleImport, ActualSale, ActualSaleOutlierAdjustment, ActualSaleLocation, ItemPlanningProfile,
       ForecastVersion, ForecastLine, ForecastAggregate, ForecastOverride, OverrideSplitWeight, ForecastAccuracy, AbcClassDefinition, ForecastingConfig, SeriesLevelEvaluation, SeriesProfile,
       SalesScheme, SalesSchemeScope, SalesSchemePeriod, ResolvedSalesSchemePeriod, SalesSchemeOccurrence,
   ]
   ```

   This makes `_get_model_permissions` → `_sync_user_model_perms` assign
   `view/add/change/delete_<model_name>` to the admin role (viewer/staff get none) whenever a
   membership or group is saved. The codenames resolve automatically because Django creates the
   default `add/change/delete/view` permissions at `migrate` time. Note: `ClientScopedMixin` admin
   scoping and `_user_has_admin_role` are what gate per-client rows in admin — the model perms above
   are the module-level gate.

2. **Scheme-change receiver.** Add a `post_save` receiver (mirroring
   `outlier_adjustment_status_changed` in the same file) that fires the resolver, flags stale
   DRAFT versions, and re-triggers outlier detection over the covered range:

   ```python
   @receiver(post_save, sender=SalesScheme)
   def scheme_changed(sender, instance, **kwargs):
       """ACTIVE scheme create/edit: re-materialize resolved rows, flag stale
       DRAFT versions, and re-run outlier detection on the covered range."""
       from mysite.tasks.demand.resolve_scheme_scope import resolve_scheme_scope
       from mysite.tasks.demand.detect_outliers import (
           flag_stale_forecast_versions, run_outlier_detection,
       )
       if instance.status != "ACTIVE":
           return
       update_fields = kwargs.get("update_fields")
       if update_fields is not None and not update_fields.intersection(
           {"status", "expected_qty_uplift_pct", "expected_value_uplift_pct",
            "shadow_periods", "pull_forward_pct"}):
           return
       resolve_scheme_scope.delay(scheme_id=instance.id)
       for period in instance.periods.all():     # window + shadow buckets, as resolved rows
           flag_stale_forecast_versions.delay(client_id=instance.client_id,
                                              period_type=period.period_type,
                                              period_start=period.period_start)
       run_outlier_detection.delay(client_id=instance.client_id,
                                   target_period_start=widest_covered_start(instance),
                                   target_period_end=widest_covered_end(instance))
   ```

   This requires extending `flag_stale_forecast_versions` (Phase 2, Step 2.4) to accept an optional
   `(client_id, period_type, period_start)` **range mode** — flag every DRAFT `ForecastVersion` whose
   horizon covers that period; the existing `actual_sale_id` mode stays unchanged and keeps serving
   the outlier signal. The `run_outlier_detection` re-trigger uses the widest covered span
   (window + shadow) computed from the scheme's resolved rows, same range the review queue's
   "activate" action uses. Keep the guard simple — firing on every ACTIVE-scheme save is harmless
   (idempotent), matching the outlier signal's philosophy. The review queue's `scheme_activate` view
   calls `resolve_scheme_scope` directly and lets this signal handle stale-flag + detection, so there
   is exactly one wiring path.

**Authorization checkpoint:** after migration, a non-superuser user with an `admin` role in an active
`ClientGroup` sees the five scheme models in Django admin with full CRUD; a `viewer`/`staff` user sees
none of them. Superusers bypass checks as usual.

---

## Phase 2 — Scheme-Netted Baseline + Outlier Sequencing

### Step 2.1 — Compose the baseline netting helper

Extend `utils/demand/actuals_net.py`. Keep the outlier signature working; add scheme composition in a
new function, and make `actuals_queryset_with_net` delegate to it:

```python
from django.db.models import Case, DecimalField, F, OuterRef, Subquery, Sum, Q, Value, When
from django.db.models.functions import Coalesce
from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.schemes import ResolvedSalesSchemePeriod


def _window_factors():
    """Per-row window factors via correlated Subquery (is_shadow=False).

    Overlap (Phase 6) resolves most-specific-wins by ordering on scheme_code;
    deterministic pick of the first row. NULL when the grain+period is not a
    window for any ACTIVE scheme.
    """
    qs = ResolvedSalesSchemePeriod.objects.filter(
        item=OuterRef("item"), planning_location=OuterRef("planning_location"),
        planning_customer=OuterRef("planning_customer"),
        distribution_channel=OuterRef("distribution_channel"),
        period_type=OuterRef("period_type"), period_start=OuterRef("period_start"),
        is_shadow=False,
    )
    return {
        "qty_factor": Subquery(qs.order_by("scheme__scheme_code").values("qty_factor")[:1]),
        "value_factor": Subquery(qs.order_by("scheme__scheme_code").values("value_factor")[:1]),
    }


def _shadow_addbacks():
    """Per-row shadow add-backs via a grouped correlated Subquery (is_shadow=True).

    For each matching shadow row:
        addback_qty    = window_qty    × (1 − 1/anchor_qty_factor)    × addback_qty_weight
        addback_revenue = window_revenue × (1 − 1/anchor_value_factor) × addback_value_weight
    where window_qty / window_revenue are the ANCHOR WINDOW period's raw
    actuals at the same grain. Summed across schemes (shadow overlap is
    additive). NULL when the grain+period is not a shadow for any scheme.
    """
    shadow = ResolvedSalesSchemePeriod.objects.filter(
        item=OuterRef("item"), planning_location=OuterRef("planning_location"),
        planning_customer=OuterRef("planning_customer"),
        distribution_channel=OuterRef("distribution_channel"),
        period_type=OuterRef("period_type"), period_start=OuterRef("period_start"),
        is_shadow=True,
    ).annotate(
        window_qty=Subquery(
            ActualSale.objects.filter(
                client=OuterRef("client"), item=OuterRef("item"),
                planning_location=OuterRef("planning_location"),
                planning_customer=OuterRef("planning_customer"),
                distribution_channel=OuterRef("distribution_channel"),
                period_start=OuterRef("anchor_period_start"),
            ).values("qty")[:1]
        ),
        window_revenue=Subquery(
            ActualSale.objects.filter(
                client=OuterRef("client"), item=OuterRef("item"),
                planning_location=OuterRef("planning_location"),
                planning_customer=OuterRef("planning_customer"),
                distribution_channel=OuterRef("distribution_channel"),
                period_start=OuterRef("anchor_period_start"),
            ).values("revenue")[:1]
        ),
        addback_qty=F("window_qty") * (1 - 1 / F("anchor_qty_factor")) * F("addback_qty_weight"),
        addback_revenue=F("window_revenue") * (1 - 1 / F("anchor_value_factor")) * F("addback_value_weight"),
    )
    return {
        "shadow_addback_qty": Subquery(
            shadow.values("item").annotate(total=Sum("addback_qty")).values("total")[:1]),
        "shadow_addback_revenue": Subquery(
            shadow.values("item").annotate(total=Sum("addback_revenue")).values("total")[:1]),
    }


def scheme_netted_queryset(client, use_scheme_net: bool):
    """Annotate scheme_net_qty / scheme_net_revenue on ActualSale rows.

    Window rows DIVIDE (multiplicative, uplift scales with demand level);
    shadow rows ADD BACK a share of the anchor window's uplift. A row that is
    a window for one scheme and a shadow for another gets both branches
    composed. Outlier netting runs AFTER this (subtractive).
    """
    qs = ActualSale.objects.filter(client=client)
    if not use_scheme_net:
        return qs.annotate(scheme_net_qty=F("qty"), scheme_net_revenue=F("revenue"))

    qs = qs.annotate(**_window_factors()).annotate(**_shadow_addbacks())
    return qs.annotate(
        # Division branch only when a window matches (qty_factor non-NULL);
        # COALESCE keeps non-window rows at raw qty.
        scheme_net_qty=Coalesce(
            F("qty") / F("qty_factor"), F("qty")
        ) + Coalesce(F("shadow_addback_qty"), Value(0), output_field=DecimalField()),
        scheme_net_revenue=Coalesce(
            F("revenue") / F("value_factor"), F("revenue")
        ) + Coalesce(F("shadow_addback_revenue"), Value(0), output_field=DecimalField()),
    )


def actuals_queryset_with_net(client, use_net: bool, use_scheme_net: bool = None):
    """Composed baseline netting: SCHEME FIRST, THEN OUTLIER.

    baseline_qty    = scheme_net_qty    − outlier_qty_adjustment
    baseline_revenue = scheme_net_revenue − outlier_revenue_adjustment
    """
    if use_scheme_net is None:
        use_scheme_net = getattr(getattr(client, "forecasting_config", None),
                                 "scheme_net_actuals", False)
    qs = scheme_netted_queryset(client, use_scheme_net).select_related("outlier_adjustment")

    if not use_net:
        return qs.annotate(
            net_qty=F("scheme_net_qty"),
            net_revenue=F("scheme_net_revenue"),
        )

    return qs.annotate(
        net_qty=Case(
            When(outlier_adjustment__status="CONFIRMED",
                 then=F("scheme_net_qty") - F("outlier_adjustment__qty_adjustment")),
            default=F("scheme_net_qty"),
            output_field=DecimalField(max_digits=14, decimal_places=3),
        ),
        net_revenue=Case(
            When(outlier_adjustment__status="CONFIRMED",
                 then=F("scheme_net_revenue") - Coalesce(
                     F("outlier_adjustment__revenue_adjustment"), Value(0))),
            default=F("scheme_net_revenue"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )
```

Notes:
- This deliberately uses correlated `Subquery`/`Sum` annotations instead of the `resolved_scheme_periods`
  reverse-relation join — a single actuals row can match a window for one scheme and a shadow for
  another, and a reverse join would fan out rows. The subqueries keep one row per ActualSale.
- NULL semantics: a NULL-revenue row stays NULL (`F("revenue") / factor` yields NULL, and
  `NULL + COALESCE(addback, 0)` stays NULL) — the desired "optional revenue" behaviour everywhere else.
  A shadow row whose anchor window has no actuals at the same grain gets `window_qty`/`window_revenue`
  NULL → `addback_*` NULL → `COALESCE(..., 0)` → no add-back (documented: shadow only borrows from a
  real window).

### Step 2.2 — Outlier detection reads scheme-netted series

In `mysite/tasks/demand/detect_outliers.py`, `run_outlier_detection`:

1. Build the per-series values from the SAME composed helper — do not re-implement the factors locally.
   Query `actuals_queryset_with_net(client, use_net=False, use_scheme_net=config.scheme_net_actuals)`
   (or `scheme_netted_queryset`) for the window and group by the series key, reading
   `r.scheme_net_qty` / `r.scheme_net_revenue`. This includes the shadow add-back, so window spikes AND
   pre/post dips are both absent from the detection series.
2. `values = [r.scheme_net_qty for r in series_rows]`.
3. `_suggest_adjustment_qty` / `_suggest_adjustment_revenue` operate on the same scheme-netted values
   (pass the scheme-netted qty in; the revenue prorata uses the scheme-netted revenue).
4. Keep "skip rows that already have an adjustment" and the CANDIDATE-only rule unchanged.

In `ActualSaleOutlierAdjustment.clean()`, bound the adjustments to the **scheme-netted** row value:

```python
    def clean(self):
        if self.qty_adjustment is not None and self.actual_sale_id:
            scheme_qty = self.actual_sale.scheme_net_qty  # via helper, or recompute
            if self.qty_adjustment > scheme_qty:
                raise ValidationError({"qty_adjustment": _("Cannot exceed the actual's scheme-netted qty.")})
            ...
```

### Step 2.3 — Forecast/profile/price consumers switch to the composed helper

- `utils/demand/forecast_engine.py` `build_actuals_dataframe`: it already calls
  `actuals_queryset_with_net(client, use_net)` and renames `net_qty→qty`. Pass `use_scheme_net =
  cfg.scheme_net_actuals` — the rename stays the single injection point, so nothing else in the engine
  changes. Same for `update_weighted_avg_prices` (weighted price now computed on scheme-free revenue).
- `utils/demand/compute_series_profiles.py`: same — pass `use_scheme_net`.
- Reporting / ABC classification callers of `actuals_queryset_with_net`: default `use_scheme_net` from
  `scheme_net_actuals` (same flag; the outlier feature's per-module reporting/ABC flags remain as-is —
  a client opting reporting back to raw gets raw including scheme, which is the documented intent).

### Step 2.4 — Stale-flagging on scheme change

Extend `flag_stale_forecast_versions` (in `mysite/tasks/demand/detect_outliers.py`) with an optional
**range mode** — `flag_stale_forecast_versions(client_id, period_type, period_start, actual_sale_id=None)`:
when `actual_sale_id` is omitted, flag every DRAFT `ForecastVersion` whose horizon covers the given
period. The existing `actual_sale_id` mode stays unchanged (serves the outlier signal). The wiring
itself is the `scheme_changed` receiver in `mysite/signals.py` (Step 1.5): a scheme activation/change
re-triggers outlier detection on the widest covered range (window + shadow) AND flags DRAFT versions
whose horizon covers those periods. Rebuild-on-change also fires when `resolve_scheme_scope` bulk-creates
resolved rows, but the `SalesScheme` post_save receiver is the authoritative trigger — no separate
signal on the resolved table needed (avoids double-firing).

**Checkpoint:**

```bash
python manage.py test mysite.tests.demand.test_actuals_net \
    mysite.tests.demand.test_outlier_detection
```

New unit tests (add to the suite):
- 1-for-1 scheme fixture → `net_qty == qty/2`, `net_revenue == revenue`.
- Scheme spike at product-group grain → **not** proposed as an outlier candidate by `detect_candidates`
  when run on scheme-netted series.
- Shadow fixture (`shadow_periods=1`, `pull_forward_pct=0.5`): each pre/post period nets to
  `qty + 0.5 × (window_qty × (1 − 1/qty_factor))`; the pre/post dip is **not** proposed as an outlier;
  1-for-1 value add-back == 0.
- `qty_adjustment` beyond scheme-netted qty → `clean()` raises.
- Forecast with `scheme_net_actuals=True` differs materially from `False`.
- **Brand scope:** with `brand_taxonomy` set and a Brand node + item mappings, a BRAND-scoped ACTIVE
  scheme materializes a resolved WINDOW row for every item mapped beneath the brand node even though
  the items sit in different planning product groups (union membership); netting divides those rows by
  the scheme factor.
- **Brand + group overlap (within-scheme dedup):** a scheme with a BRAND row and a TAXONOMY row covering
  the same item resolves that item exactly once per period (most-specific-wins) — the netting subquery
  applies one factor, not two.
- **Brand prerequisite:** `SalesSchemeScope.clean()` raises when `brand_taxonomy` is unset, when the
  scope node is not in the configured brand taxonomy, and when no items are mapped beneath the node.

---

## Phase 3 — Forecast-Horizon Uplift (Output)

### Step 3.1 — Factor lookup

Add to `utils/demand/forecast_engine.py`:

```python
def build_scheme_forecast_factors(client_id, period_type, period_start_to, horizon):
    """{(unique_id, period_start): overlay} for the forecast horizon.

    Two overlay shapes (only ACTIVE schemes):
      * WINDOW:  {'scheme_id', 'qty_factor', 'value_factor'} → uplift delta
                 computed as pre_scheme_statistical_qty × (qty_factor − 1).
      * SHADOW:  {'scheme_id', 'anchor_period_start', 'anchor_qty_factor',
                  'anchor_value_factor', 'addback_qty_weight',
                  'addback_value_weight'} → dip delta computed as
                  −window_pre_scheme_statistical_qty × (1 − 1/anchor_factor) × weight.
    """
```

Implementation: pull `ResolvedSalesSchemePeriod` rows (joined to item/location/customer codes) whose
`period_start` falls in the horizon, key by `(unique_id, period_start)`. For WINDOW rows the factors are
`qty_factor`/`value_factor` (already `1 + uplift`); for SHADOW rows carry the anchor fields and weights.
Build a second lookup `anchor_pre_stat_qty[(unique_id, anchor_period_start)]` from the generated forecast
lines in Step 3.2.

### Step 3.2 — Apply in `write_forecast_lines` (merge inside)

The scheme uplift is merged **inside** `write_forecast_lines`, not as a post-processing pass. The
caller passes `scheme_factors` as a parameter. For each line:

```python
    # 1. Write clean baseline from engine output
    line.pre_scheme_statistical_qty = stat_qty
    if price is not None:
        line.pre_scheme_statistical_value = (stat_qty * price).quantize(TWO_DP)

    # 2. Look up scheme factor
    key = (uid, period_start)
    sf = scheme_factors.get(key)
    if sf is None:
        # No scheme — statistical_qty = pre_scheme (unchanged)
        line.scheme_qty = None
        line.scheme_value = None
    elif "qty_factor" in sf:
        # WINDOW row — uplift delta
        line.scheme_id_id = sf['scheme_id']
        uplift_pct = Decimal(str(sf['qty_factor'])) - Decimal('1')
        line.scheme_qty = (stat_qty * uplift_pct).quantize(THREE_DP)
        if price is not None:
            value_uplift = Decimal(str(sf['value_factor'])) - Decimal('1')
            line.scheme_value = (line.pre_scheme_statistical_value * value_uplift).quantize(TWO_DP)
    else:
        # SHADOW row — dip delta anchored to the window line's pre_scheme_statistical_qty
        anchor_key = (uid, sf['anchor_period_start'])
        window_pre_stat_qty = anchor_pre_stat_qty.get(anchor_key)
        if window_pre_stat_qty is None:
            logger.warning("scheme %s shadow at %s: anchor window %s outside horizon — skipped",
                           sf['scheme_id'], period_start, sf['anchor_period_start'])
            line.pre_scheme_statistical_qty = stat_qty  # restore
            continue
        line.scheme_id_id = sf['scheme_id']
        dip_qty = (window_pre_stat_qty
                   * (Decimal('1') - Decimal('1') / Decimal(str(sf['anchor_qty_factor'])))
                   * Decimal(str(sf['addback_qty_weight']))).quantize(THREE_DP)
        line.scheme_qty = (-dip_qty).quantize(THREE_DP)  # negative = dip
        if price is not None:
            dip_value = (window_pre_stat_qty
                         * (Decimal('1') - Decimal('1') / Decimal(str(sf['anchor_value_factor'])))
                         * Decimal(str(sf['addback_value_weight']))).quantize(TWO_DP)
            line.scheme_value = (-dip_value).quantize(TWO_DP)

    # 3. Compute statistical_qty = pre_scheme + scheme_qty (always)
    line.statistical_qty = (
        line.pre_scheme_statistical_qty + (line.scheme_qty or Decimal('0'))
    ).quantize(THREE_DP)
    if price is not None:
        line.statistical_value = (
            line.pre_scheme_statistical_value + (line.scheme_value or Decimal('0'))
        ).quantize(TWO_DP)
```

`pre_scheme_statistical_qty` is always the engine's clean baseline. `scheme_qty` is the uplift delta
(positive for window, negative for shadow dip, NULL when no scheme). `statistical_qty` is always
`pre_scheme_statistical_qty + (scheme_qty or 0)`. The override system continues to work on
`statistical_qty` — no changes needed.

`anchor_pre_stat_qty` is populated in a first pass over the built lines (keyed on
`(unique_id, period_start)`) before the second pass applies the scheme overlays.

**Note on override system:** No changes needed to override disaggregation, `ForecastLine.save()`,
aggregate rollup, or revert logic. The override system continues to work on `statistical_qty` which
now includes the scheme uplift. When a scheme is modified after overrides exist, the version is flagged
as stale and the planner must re-apply overrides manually.

### Step 3.3 — Roll-ups

In `write_forecast_aggregates`, add `SUM(pre_scheme_statistical_qty)` /
`SUM(pre_scheme_statistical_value)` (DuckDB) to the `ForecastAggregate` creation, alongside the existing
`SUM(statistical_qty)` / `SUM(total_statistical_value)`. The `pre_scheme_*` fields enable both-column
display in the UI.

**Checkpoint:** a horizon period inside an ACTIVE scheme window gets the correct uplift delta (1-for-1 →
`scheme_qty = pre_scheme_statistical_qty`, `statistical_qty = 2 × pre_scheme_statistical_qty`,
`scheme_value = NULL`); a pre/post shadow period gets `scheme_qty = −window_pre_scheme_statistical_qty ×
(1 − 1/anchor_qty_factor) × weight`; a shadow whose anchor window is outside the horizon logs a warning
and is skipped; periods outside any scheme get `scheme_qty = NULL` and `statistical_qty =
pre_scheme_statistical_qty`; aggregate rows carry both `pre_scheme_statistical_qty` and `statistical_qty`.

---

## Phase 4 — Scheme Detection & Planner Review Queue

### Step 4.1 — `detect_scheme_candidates` task

Add to `mysite/tasks/demand/detect_scheme_candidates.py`:

```python
@shared_task
def detect_scheme_candidates(client_id, target_period_start, target_period_end,
                             triggered_by_user_id=None):
```

Algorithm:
1. Aggregate **raw** actuals (scheme-unadjusted) to the product-group grain (`TAXON_*`, i.e.
   item → `taxon_node_item_ids`) for the target window + lookback.
2. Run the existing `detect_candidates` (MAD + persistence) per product-group series — a candidate is a
   transient spike.
3. Skip any candidate whose (node, period) is already covered by an ACTIVE `ResolvedSalesSchemePeriod`.
4. Suggested `expected_qty_uplift_pct = period_demand / median(neighbouring periods) − 1`.
5. Record candidates on a `SalesScheme`-like proposal table (reuse a `DRAFT` `SalesScheme` with a
   `detected_by='SYSTEM'` marker, or a dedicated proposal table) → planner queue. Never auto-activate.
6. Record run identity on `ForecastingConfig.last_scheme_detection_*`.

### Step 4.2 — HTMX views (`mysite/demand_ui/views.py` + templates)

Mirror the outlier feature (`outlier_queue`, `outlier_confirm`, ...):

- `scheme_list` — ACTIVE/DRAFT schemes, filterable.
- `scheme_create` / `scheme_edit` — registration form (scope lines, periods, uplifts; pre-fill
  `expected_value_uplift_pct` from `discount_pct` via `(1+u)(1−d)−1` when the planner hasn't overridden).
  **Scope-line editor:** each line offers `scope_type` OVERALL / TAXONOMY / BRAND / ITEM. The TAXONOMY
  picker lists planning product-hierarchy nodes (as today); the **BRAND picker** lists the nodes of
  `ForecastingConfig.brand_taxonomy` for this client (a brand dropdown, the scheme's "vendor"). When
  `brand_taxonomy` is unset or has no nodes with item mappings, the BRAND option is hidden/disabled with
  a "set up the brand taxonomy (Brand nodes + item mappings) to scope schemes by brand" message — this is
  the visible prerequisite gate.
- `scheme_review_queue` — system-proposed candidates; `scheme_activate` (→ status ACTIVE + resolve),
  `scheme_reject`.
- `scheme_occurrences` — closed-scheme actual-vs-expected report.
- Nav link + candidate-count badge (mirror the outlier badge; gate on `scheme_ui_visible`).
- Templates under `templates/demand/schemes/` (extend `_base_demand.html`).

URLs in `mysite/demand_ui/urls.py` under `/schemes/`. No DRF endpoints.

### Step 4.3 — Admin

New module `mysite/admin/demand_schemes.py` (mirror the structure of `mysite/admin/demand_forecast.py`):

```python
class SalesSchemeScopeInline(admin.TabularInline):
    model = SalesSchemeScope
    extra = 0
    # fields: scope_type, taxonomy_node, item, planning_location, planning_customer,
    #         distribution_channel (raw_id_fields on the FK-heavy columns)
    # BRAND rows reuse taxonomy_node (must sit in the configured brand taxonomy —
    #   enforced by SalesSchemeScope.clean()).

class SalesSchemePeriodInline(admin.TabularInline):
    model = SalesSchemePeriod
    extra = 0                       # period_type, period_start (period_end is editable=False)

class SalesSchemeOccurrenceInline(admin.TabularInline):
    model = SalesSchemeOccurrence
    extra = 0
    readonly_fields = ['period_type', 'period_start', 'period_end', 'actual_qty_uplift_pct',
                       'actual_value_uplift_pct', 'actual_pull_forward_pct',
                       'qty_uplift_variance', 'value_uplift_variance', 'pull_forward_variance']

class SalesSchemeAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display = ['client', 'scheme_code', 'name', 'status', 'expected_qty_uplift_pct',
                    'expected_value_uplift_pct', 'shadow_periods', 'pull_forward_pct',
                    'updated_at']
    list_filter = ['client', 'status']
    search_fields = ['scheme_code', 'name']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    inlines = [SalesSchemeScopeInline, SalesSchemePeriodInline, SalesSchemeOccurrenceInline]

class ResolvedSalesSchemePeriodAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display = ['scheme', 'item', 'planning_location', 'planning_customer',
                    'distribution_channel', 'period_type', 'period_start', 'row_kind']
    list_filter = ['period_type', 'is_shadow', 'shadow_side']
    readonly_fields = [f.name for f in ResolvedSalesSchemePeriod._meta.fields]
    def row_kind(self, obj):        # WINDOW / SHADOW(pre:j) badge for the list
        ...
    def has_add_permission(self, request):
        return False                # read-only — rows are materialized by resolve_scheme_scope
```

- Register both in `mysite/admin/__init__.py` (import from `mysite.admin.demand_schemes` +
  `admin.site.register(...)`), keeping the model-permission gate from Step 1.5 authoritative.
- `ForecastingConfigAdmin` fieldsets: add `scheme_net_actuals`, `scheme_apply_forecast_uplift`,
  `brand_taxonomy`, `last_scheme_detection_run_at/by/range_start/range_end`.
- `ForecastLineAdmin` / `ForecastAggregateAdmin`: add `pre_scheme_statistical_qty` /
  `pre_scheme_statistical_value` alongside `scheme_id`/`scheme_qty`/`scheme_value` to the
  readonly/list displays.

**Checkpoint:** single-period spike not covered by a scheme → candidate with sensible implied uplift; a
tagged period never re-proposed; activating a scheme materializes resolved rows and re-triggers outlier
detection on the range; admin-role users can CRUD schemes (see Step 1.5 auth checkpoint).

---

## Phase 5 — Occurrence Data-Checking & Uplift Estimation

### Step 5.1 — `record_scheme_occurrence` task

At period-close cadence, for each ACTIVE scheme with fully elapsed periods:

```python
def record_scheme_occurrence(scheme_id, period_type, period_start):
    # 1. Baseline demand = scheme-netted actuals for the period's neighbours
    #    (median of N surrounding periods, same helper as detection).
    # 2. actual_qty_uplift_pct = (scheme_period_qty / baseline_qty) − 1
    # 3. actual_value_uplift_pct = (scheme_period_revenue / baseline_revenue) − 1
    # 4. actual_pull_forward_pct = 1 − (Δ shadow vs baseline) / (window uplift volume)
    #    where Δ shadow = Σ(shadow_period_qty − baseline_qty) over the pre/post
    #    buckets used by the scheme; 0 ≤ clamp ≤ 1. Conservation check:
    #    pulled + incremental ≈ netted-out window uplift.
    # 5. variance = actual − expected for each measure (incl. pull-forward).
    # 6. Upsert SalesSchemeOccurrence.
```

### Step 5.2 — `suggest_uplift_for_scheme` ✅ IMPLEMENTED

When a planner registers a scheme with the same `scheme_code` that has ≥2 prior occurrences, pre-fill
`expected_*_uplift_pct` **and** `pull_forward_pct` with the **median** of the prior occurrences' actuals
(same median-not-mean choice as the 3C vendor-rebate accrual estimation). Surface variance warnings when
occurrences missed expectation by a wide margin.

**Implementation:**

1. **`suggest_uplift_for_scheme(scheme_code, client_id)`** — `mysite/tasks/demand/record_scheme_occurrence.py:166`
   - Queries the last 12 `SalesSchemeOccurrence` records for the scheme_code
   - Requires ≥2 occurrences with non-null `actual_qty_uplift_pct`
   - Computes median of `actual_qty_uplift_pct`, `actual_value_uplift_pct`, `actual_pull_forward_pct`
   - **IQR variance warning**: When IQR of past occurrences > 0.15 (15%), warns that uplift varied widely
     - Shows range (min–max) and IQR value so the planner sees the spread
   - **MAD outlier detection**: Flags individual occurrences > 3×MAD from the median
   - Returns `{ suggested: {...}, occurrence_count, history: [...], warnings: [...] }`

2. **API endpoint** — `demand_ui/views.py:scheme_suggest`
   - `GET /{client_id}/demand/schemes/suggest/?code=SCHEME_CODE`
   - Returns JSON with suggestions, occurrence history, and variance warnings
   - URL name: `demand_ui:scheme_suggest`

3. **Admin form integration** — `mysite/admin/demand_schemes.py:SalesSchemeAdmin`
   - JavaScript injected on the SalesScheme **add form** via `render_change_form()`
   - On `scheme_code` field **blur**, fetches suggestions from the API
   - **Pre-fills** `expected_qty_uplift_pct`, `expected_value_uplift_pct`, `pull_forward_pct`
     with median values (only when field is at default 0.0000)
   - Filled fields get a green highlight (`#e8f5e9`)
   - **Green banner** shows occurrence count and which fields were pre-filled
   - **Orange warning banner** appears if IQR/MAD variance warnings exist

**Planner flow:**

```
1. Admin → Sales Promotion Schemes → Add
2. Enter scheme_code (e.g., "DIWALI2024") + tab out
3. JS fires blur → GET /demand/schemes/suggest/?code=DIWALI2024
4. Response: { suggested: { expected_qty_uplift_pct: "0.2500", ... },
               occurrence_count: 5,
               warnings: ["Past runs of 'qty uplift' varied widely: ..."] }
5. Fields auto-fill with median values (green highlight)
6. Warning banner appears if variance is high
7. Planner reviews, adjusts if needed, saves
```

**Checkpoint:** a closed scheme measures actual uplift independently for qty and value and estimates
actual pull-forward against its neighbours; a re-registration pre-fills uplift and `pull_forward_pct`
from the median of past occurrences, with variance warnings when history is inconsistent.

---

## Phase 6 — Hardening & Regression

- Overlap resolution: deterministic most-specific-wins when a (item, location, customer, channel, period)
  is a WINDOW row under >1 ACTIVE scheme; warning surfaced in the scheme list. A period that is a window
  under one scheme and a shadow under another is expected (back-to-back schemes) and composes — covered
  by a test, not a warning.
- Edge guards: `value_uplift ≤ −1` rejected in `clean()`; `pull_forward_pct ∉ [0,1]` rejected in
  `clean()`; zero-qty-uplift + non-zero-value-uplift scheme still nets revenue; NULL-revenue rows stay
  NULL; a shadow row with no anchor-window actuals adds nothing (COALESCE to 0); a shadow whose anchor
  window is outside the forecast horizon is skipped with a warning.
- Load check: `resolve_scheme_scope` across a full monthly import batch (10K SKU × 200 customer × 36
  month) completes within the run budget — note shadow rows multiply the resolved-row count by
  `1 + 2 × shadow_periods` per window.
- Full test suite (extend `mysite/tests/demand/`):
  - `test_scheme_netting.py` — 1-for-1, pure-price-off, buy-2-get-1-free, zero-uplift, ordering vs outlier,
    shadow add-back math (`shadow_periods=1/2`, decay weights), window+shadow same-period composition.
  - `test_scheme_detection.py` — candidate on raw, none on tagged (window OR shadow), implied uplift
    suggestion, pre/post dip not proposed as outlier.
  - `test_scheme_forecast_uplift.py` — horizon window uplift delta, horizon shadow dip delta,
    `statistical_qty = pre_scheme + scheme_qty`, anchor-outside-horizon skip + warning,
    aggregate roll-up with `pre_scheme_statistical_qty`, outside-scheme NULLs, override system
    works on `statistical_qty` (unchanged).
  - `test_scheme_occurrences.py` — actual uplift measurement, actual pull-forward estimation, median
    pre-fill incl. `pull_forward_pct`, variance warning.
  - `test_scheme_stale_flagging.py` — scheme activation flags DRAFT versions + re-triggers detection;
    scheme modification after overrides exist flags version as stale (planner must re-apply).
- `makemigrations --check` clean; `manage.py check` 0 issues.

---

## Sequencing Summary

```
Phase 1 (Models + resolve_scheme_scope)
  ├─▶ Phase 2 (Composed baseline netting + outlier basis switch)
  │     ├─▶ Phase 3 (Horizon uplift)
  │     └─▶ Phase 4 (Detection + queue) ─▶ Phase 5 (Occurrences/estimation)
  └─▶ Phase 6 (Hardening)
```

Phases 3 and 4 can start once Phase 1 lands. Phase 2 is the critical path — it changes the basis of
outlier detection, so it must complete before any production forecast run that relies on correct
baselines.

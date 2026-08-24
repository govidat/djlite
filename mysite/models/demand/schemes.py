"""
Sales Promotion Scheme Management models.

A scheme covers BOTH historical and future periods:
- Historical periods: net scheme impact out of actuals (baseline = actuals − scheme − outlier)
- Future periods: re-apply expected uplift to the forecast horizon

Ordering invariant: baseline = Actuals − scheme impact − outlier.
Scheme netting runs first; outlier detection runs on scheme-netted series.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.actuals import PERIOD_TYPE_CHOICES, compute_period_end


# ── Constants ────────────────────────────────────────────────────────────

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

SHADOW_DECAY = Decimal("0.5")      # weight(j) ∝ decay ** j
SHADOW_PRE_SHARE = Decimal("0.5")  # pre/post split of the pulled volume


# ── Shadow weight helpers ────────────────────────────────────────────────

def shadow_weights(shadow_periods):
    """Return [(j, weight) ...] with per-side weights normalized to 1."""
    raw = [SHADOW_DECAY ** j for j in range(1, shadow_periods + 1)]
    total = sum(raw, Decimal("0"))
    if total == 0:
        return []
    return [(j, w / total) for j, w in zip(range(1, shadow_periods + 1), raw)]


def addback_weight(pull_forward_pct, side, j, shadow_periods):
    """Composite weight stored on a shadow row = pf × side_share × w_j."""
    share = SHADOW_PRE_SHARE if side == "PRE" else (Decimal("1") - SHADOW_PRE_SHARE)
    w_j = dict(shadow_weights(shadow_periods))[j]
    return pull_forward_pct * share * w_j


# ── Period arithmetic for shadow buckets ─────────────────────────────────

def next_period_start(period_start, period_type, n=1):
    """Return the period_start of the nth period after period_start."""
    from utils.demand.periods import step_date
    return step_date(period_start, period_type, n)


def previous_period_start(period_start, period_type, n=1):
    """Return the period_start of the nth period before period_start."""
    from utils.demand.periods import step_date
    return step_date(period_start, period_type, -n)


# ── Models ───────────────────────────────────────────────────────────────

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

    def __str__(self):
        return f"{self.scheme_code} — {self.name} ({self.status})"

    def clean(self):
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
    (materialized-path LIKE query). BRAND scope = every item mapped beneath a Brand
    node in the client's item taxonomy (the scheme's "vendor"); membership is the
    UNION of all ItemTaxonomyNode mappings under that node. ITEM scope = the exact
    item. Null dims mean "all".

    Membership is resolved tree-aware: each scope row expands from ITS OWN node's
    taxonomy subtree (see resolve_scheme_scope Step 2), not the planning hierarchy
    only.
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="scopes")
    scope_type = models.CharField(_("scope type"), max_length=16,
                                  choices=SCOPE_TYPE_CHOICES)
    taxonomy_node = models.ForeignKey("mysite.TaxonomyNode", null=True, blank=True,
                                      on_delete=models.CASCADE, related_name="+")
    item = models.ForeignKey("mysite.Item", null=True, blank=True,
                             on_delete=models.CASCADE, related_name="+")
    planning_location = models.ForeignKey("mysite.PlanningLocation", null=True, blank=True,
                                          on_delete=models.CASCADE, related_name="+")
    planning_customer = models.ForeignKey("mysite.PlanningCustomer", null=True, blank=True,
                                          on_delete=models.CASCADE, related_name="+")
    distribution_channel = models.ForeignKey("mysite.DistributionChannel", null=True, blank=True,
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
            from mysite.models import Taxonomy
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
      (horizon) a share of the window's uplift.

    Built by resolve_scheme_scope on scheme save/approval.
    """
    scheme = models.ForeignKey(SalesScheme, on_delete=models.CASCADE,
                               related_name="resolved_periods")
    item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE, related_name="+")
    planning_location = models.ForeignKey("mysite.PlanningLocation",
                                          on_delete=models.CASCADE, related_name="+")
    planning_customer = models.ForeignKey("mysite.PlanningCustomer",
                                          null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    distribution_channel = models.ForeignKey("mysite.DistributionChannel",
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
    anchor_period_start = models.DateField(null=True, blank=True)
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

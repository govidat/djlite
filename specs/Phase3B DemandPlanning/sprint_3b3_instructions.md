# Sprint 3B.3 — Forecast Models and Version Management
## Detailed Implementation Instructions

**Dependencies:** Sprint 3B.2 complete  
**Estimated effort:** 3–4 days  
**App label:** `mysite`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Models — `forecast.py`](#2-models--forecastpy)
3. [State Machine — `ForecastVersion.status`](#3-state-machine--forecastversionstatus)
4. [Migration](#4-migration)
5. [Admin](#5-admin)
6. [Serializers](#6-serializers)
7. [Views](#7-views)
8. [URLs](#8-urls)
9. [Unit Tests](#9-unit-tests)
10. [Final Checklist](#10-final-checklist)

---

## 1. Architecture Overview

### How the six models relate to each other

```
ForecastVersion
│   One version = one planning cycle run for a client
│   (e.g. "Jan-2025 Monthly Consensus, v3")
│
├── ForecastLine  (one row per version × item × customer × location × period)
│       The atomic grain. statistical_qty comes from Celery/StatsForecast.
│       final_qty = override_qty if set, else statistical_qty.
│
├── ForecastAggregate  (one row per version × aggregation level × period)
│       Pre-rolled-up totals at Category / Region / Channel level.
│       Populated by the Celery reconciliation task in Sprint 3B.4.
│
├── ForecastOverride  (one row per planner edit)
│       Planners override at any level — SKU, Category, Region, etc.
│       The Celery disaggregation task pushes overrides down to ForecastLine.
│
│   └── OverrideSplitWeight  (one row per child node when method=CUSTOM)
│           Explicit weights for custom disaggregation splits.
│
└── ForecastAccuracy  (populated after actuals land for the forecast period)
        MAPE, bias, etc. Compared against ForecastLine.final_qty.
```

### Status lifecycle

```
DRAFT → IN_REVIEW → APPROVED → LOCKED
  │                               │
  └───────────────────────────────┘
        copy() creates new DRAFT
```

Only `DRAFT` versions accept edits and overrides.  
`LOCKED` versions are immutable — they are the baseline for PO generation.

### Period representation

Following the pattern established in `ActualSale`, periods use
`period_type` + `period_start` + `period_end` — not `year` + `month` integers.
This keeps forecast periods consistent with actuals periods and supports
any granularity (weekly, quarterly, etc.). The sprint spec mentions
`year, month` fields — these are replaced with the flexible period pattern
for consistency. The migration notes in Section 4 explain the index names
which map to this revised design.

---

## 2. Models — `forecast.py`

Create `mysite/models/demand/forecast.py` in full:

```python
"""
mysite/models/demand/forecast.py

Six models covering the full forecast lifecycle:

  ForecastVersion     — one planning run (draft → approved → locked)
  ForecastLine        — atomic SKU × customer × location × period forecast
  ForecastAggregate   — pre-rolled aggregates at any hierarchy level
  ForecastOverride    — planner consensus edits at any level
  OverrideSplitWeight — custom disaggregation weights for overrides
  ForecastAccuracy    — accuracy metrics once actuals land
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from mysite.models.demand.actuals import (
    PERIOD_TYPE_CHOICES,
    compute_period_end,
    validate_period_start,
)
from mysite.models.demand.hierarchy import (
    PlanningLocation,
    PlanningCustomer,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# 1. ForecastVersion
# ─────────────────────────────────────────────────────────────────────────────

class ForecastVersion(models.Model):
    """
    One forecast planning cycle for a client.

    Represents a complete, versioned snapshot of the demand plan:
      - statistical base (from StatsForecast)
      - planner consensus overrides applied on top
      - approval and lock workflow

    Lifecycle:  DRAFT → IN_REVIEW → APPROVED → LOCKED
    Only DRAFT versions accept edits. LOCKED versions are immutable
    and serve as the baseline for purchase orders and production plans.
    A LOCKED version can be copied into a new DRAFT via copy().
    """

    class Status(models.TextChoices):
        DRAFT     = 'DRAFT',     _('Draft')
        IN_REVIEW = 'IN_REVIEW', _('In Review')
        APPROVED  = 'APPROVED',  _('Approved')
        LOCKED    = 'LOCKED',    _('Locked')

    # Valid transitions: from_status → [allowed to_statuses]
    ALLOWED_TRANSITIONS = {
        Status.DRAFT:     [Status.IN_REVIEW],
        Status.IN_REVIEW: [Status.APPROVED, Status.DRAFT],   # DRAFT = send back
        Status.APPROVED:  [Status.LOCKED],
        Status.LOCKED:    [],                                  # terminal
    }

    class DisaggMethod(models.TextChoices):
        PROPORTIONAL = 'PROPORTIONAL', _('Proportional (historical share)')
        EQUAL        = 'EQUAL',        _('Equal split')
        CUSTOM       = 'CUSTOM',       _('Custom weights')

    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='forecast_versions',
        verbose_name=_('client'),
    )
    version_label = models.CharField(
        _('version label'),
        max_length=255,
        help_text=_('Human-readable label, e.g. "Jan-2025 Monthly Consensus v3".'),
    )
    # Period configuration
    period_type = models.CharField(
        _('period type'),
        max_length=16,
        choices=PERIOD_TYPE_CHOICES,
        default='month',
        help_text=_('Granularity of forecast periods. Must match actuals period_type.'),
    )
    base_period_end = models.DateField(
        _('base period end'),
        help_text=_(
            'Last day of the last actuals period used as the forecast base. '
            'Forecast periods start the day after this date.'
        ),
    )
    horizon_periods = models.PositiveSmallIntegerField(
        _('horizon periods'),
        default=6,
        help_text=_('Number of periods to forecast ahead (e.g. 6 months).'),
    )
    # Engine configuration — stored as JSON so it can evolve without migrations
    engine_config = models.JSONField(
        _('engine configuration'),
        default=dict,
        blank=True,
        help_text=_(
            'StatsForecast model configuration. Example: '
            '{"models": ["AutoETS", "AutoARIMA"], "season_length": 12, '
            '"reconciliation": "MinTrace_ols"}'
        ),
    )
    # Status and workflow
    status = models.CharField(
        _('status'),
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='forecast_versions_created',
        verbose_name=_('created by'),
    )
    approved_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='forecast_versions_approved',
        verbose_name=_('approved by'),
    )
    approved_at = models.DateTimeField(
        _('approved at'),
        null=True,
        blank=True,
    )
    locked_at = models.DateTimeField(
        _('locked at'),
        null=True,
        blank=True,
    )
    # Provenance: which version was this copied from?
    copied_from = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='copies',
        verbose_name=_('copied from'),
    )
    notes = models.TextField(_('notes'), blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label           = 'mysite'
        ordering            = ['-created_at']
        verbose_name        = _('03-01 Forecast Version')
        verbose_name_plural = _('03-01 Forecast Versions')
        indexes = [
            models.Index(
                fields=['client', 'status'],
                name='ix_fcstver_client_status',
            ),
            models.Index(
                fields=['client', 'period_type', 'base_period_end'],
                name='ix_fcstver_client_period',
            ),
        ]

    def __str__(self):
        return f'[{self.client_id}] {self.version_label} ({self.status})'

    # ── State machine ─────────────────────────────────────────────────────────

    @property
    def is_editable(self) -> bool:
        """Only DRAFT versions accept edits and overrides."""
        return self.status == self.Status.DRAFT

    @property
    def is_locked(self) -> bool:
        return self.status == self.Status.LOCKED

    def assert_editable(self):
        """
        Call at the start of any mutation (override save, line update).
        Raises ValidationError if the version is not in DRAFT status.
        """
        if not self.is_editable:
            raise ValidationError(
                _(
                    f'Forecast version "{self.version_label}" is {self.status} '
                    f'and cannot be edited. Only DRAFT versions accept changes.'
                )
            )

    def transition_to(self, new_status: str, user: User) -> None:
        """
        Attempt a status transition. Raises ValidationError if not allowed.

        Usage:
            version.transition_to(ForecastVersion.Status.IN_REVIEW, request.user)
        """
        allowed = self.ALLOWED_TRANSITIONS.get(self.status, [])
        if new_status not in allowed:
            raise ValidationError(
                _(
                    f'Cannot transition from {self.status} to {new_status}. '
                    f'Allowed transitions: {[s for s in allowed] or "none (terminal state)"}.'
                )
            )
        self.status = new_status
        if new_status == self.Status.APPROVED:
            self.approved_by = user
            self.approved_at = timezone.now()
        if new_status == self.Status.LOCKED:
            self.locked_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'locked_at', 'updated_at'])

    def copy(self, user: User, new_label: str = None) -> 'ForecastVersion':
        """
        Create a new DRAFT version cloned from this version.

        Copies:
          - ForecastVersion metadata (new label, status=DRAFT, copied_from=self)
          - All ForecastLine rows (statistical_qty and override_qty preserved)

        Does NOT copy:
          - ForecastAccuracy (accuracy belongs to a specific version's actuals)
          - ForecastOverride audit trail (overrides are history; the lines are the result)

        Usage:
            new_version = locked_version.copy(request.user, "Feb-2025 Plan v1")
        """
        new_label = new_label or f'{self.version_label} (copy)'

        new_version = ForecastVersion.objects.create(
            client          = self.client,
            version_label   = new_label,
            period_type     = self.period_type,
            base_period_end = self.base_period_end,
            horizon_periods = self.horizon_periods,
            engine_config   = self.engine_config,
            status          = self.Status.DRAFT,
            created_by      = user,
            copied_from     = self,
            notes           = f'Copied from: {self.version_label}',
        )

        # Clone all ForecastLine rows in bulk
        original_lines = list(self.lines.all())
        cloned_lines = [
            ForecastLine(
                version           = new_version,
                item              = line.item,
                planning_customer = line.planning_customer,
                planning_location = line.planning_location,
                period_type       = line.period_type,
                period_start      = line.period_start,
                period_end        = line.period_end,
                statistical_qty   = line.statistical_qty,
                override_qty      = line.override_qty,
                # final_qty is recomputed in save() — don't copy it directly
            )
            for line in original_lines
        ]
        ForecastLine.objects.bulk_create(cloned_lines, batch_size=500)

        return new_version


# ─────────────────────────────────────────────────────────────────────────────
# 2. ForecastLine
# ─────────────────────────────────────────────────────────────────────────────

class ForecastLine(models.Model):
    """
    Atomic forecast grain: one row per version × item × customer × location × period.

    statistical_qty: output of StatsForecast (set by Celery task, never edited by planners)
    override_qty:    planner consensus edit (set via ForecastOverride disaggregation)
    final_qty:       the agreed forecast used for PO/production planning
                     = override_qty if set, else statistical_qty
                     Auto-computed in save().
    """

    version = models.ForeignKey(
        ForecastVersion,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name=_('forecast version'),
    )
    item = models.ForeignKey(
        'mysite.Item',
        on_delete=models.PROTECT,
        related_name='forecast_lines',
        verbose_name=_('item'),
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='forecast_lines',
        verbose_name=_('planning customer'),
        help_text=_('Null = location-level forecast (no customer breakdown).'),
    )
    planning_location = models.ForeignKey(
        PlanningLocation,
        on_delete=models.PROTECT,
        related_name='forecast_lines',
        verbose_name=_('planning location'),
    )
    # Period
    period_type  = models.CharField(_('period type'),  max_length=16, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField(_('period start'))
    period_end   = models.DateField(_('period end'), editable=False)
    # Quantities
    statistical_qty = models.DecimalField(
        _('statistical qty'),
        max_digits=14,
        decimal_places=3,
        help_text=_('Output of the statistical forecasting engine. Never edited by planners.'),
    )
    override_qty = models.DecimalField(
        _('override qty'),
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=_('Planner consensus override. When set, this becomes final_qty.'),
    )
    final_qty = models.DecimalField(
        _('final qty'),
        max_digits=14,
        decimal_places=3,
        editable=False,
        help_text=_(
            'Agreed forecast quantity used for PO/production planning. '
            'Auto-computed: override_qty if set, else statistical_qty.'
        ),
    )

    class Meta:
        app_label = 'mysite'
        unique_together = [
            (
                'version', 'item', 'planning_customer',
                'planning_location', 'period_type', 'period_start',
            ),
        ]
        ordering    = ['period_start', 'planning_location', 'item']
        verbose_name        = _('03-02 Forecast Line')
        verbose_name_plural = _('03-02 Forecast Lines')

    def save(self, *args, **kwargs):
        # Compute period_end
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        # Compute final_qty
        self.final_qty = (
            self.override_qty
            if self.override_qty is not None
            else self.statistical_qty
        )
        super().save(*args, **kwargs)

    def __str__(self):
        cust = self.planning_customer or 'unattributed'
        return (
            f'{self.version.version_label} | '
            f'{self.period_type}:{self.period_start} | '
            f'{self.item} | {self.planning_location} | {cust} | '
            f'final={self.final_qty}'
        )

    def clean(self):
        # Guard: LOCKED/APPROVED/IN_REVIEW versions cannot have lines edited
        if self.pk and self.version_id:
            # Only check on update, not insert (Celery populates lines on insert)
            try:
                version = ForecastVersion.objects.get(pk=self.version_id)
                if not version.is_editable:
                    raise ValidationError(
                        _('Cannot edit lines of a non-DRAFT forecast version.')
                    )
            except ForecastVersion.DoesNotExist:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# 3. ForecastAggregate
# ─────────────────────────────────────────────────────────────────────────────

class ForecastAggregate(models.Model):
    """
    Pre-computed rollup of ForecastLine at any hierarchy level.

    agg_level: which dimension is being aggregated
      e.g. 'category', 'subcategory', 'region', 'channel', 'total'

    agg_key: JSONField identifying the specific node at that level
      e.g. {"category": "Braking Systems"}
           {"category": "Braking Systems", "subcategory": "Brake Pads"}
           {"region": "North", "location": "DEL"}

    Populated by the Celery reconciliation/rollup task (Sprint 3B.4).
    Read-only from the API — never written by planners directly.
    """

    AGG_LEVEL_CHOICES = [
        ('total',       _('Grand Total')),
        ('category',    _('Product Category')),
        ('subcategory', _('Product Sub-category')),
        ('region',      _('Location Region')),
        ('location',    _('Planning Location')),
        ('channel',     _('Sales Channel')),
        ('customer',    _('Planning Customer')),
    ]

    version = models.ForeignKey(
        ForecastVersion,
        on_delete=models.CASCADE,
        related_name='aggregates',
        verbose_name=_('forecast version'),
    )
    agg_level = models.CharField(
        _('aggregation level'),
        max_length=32,
        choices=AGG_LEVEL_CHOICES,
        db_index=True,
    )
    agg_key = models.JSONField(
        _('aggregation key'),
        help_text=_(
            'JSON identifying the specific node. '
            'e.g. {"category": "Braking Systems", "region": "North"}'
        ),
    )
    # Period
    period_type  = models.CharField(_('period type'),  max_length=16, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField(_('period start'))
    period_end   = models.DateField(_('period end'), editable=False)
    # Quantities
    statistical_qty = models.DecimalField(
        _('statistical qty'), max_digits=16, decimal_places=3,
    )
    override_qty = models.DecimalField(
        _('override qty'), max_digits=16, decimal_places=3,
        null=True, blank=True,
    )
    final_qty = models.DecimalField(
        _('final qty'), max_digits=16, decimal_places=3,
        editable=False,
    )

    class Meta:
        app_label = 'mysite'
        ordering  = ['agg_level', 'period_start']
        verbose_name        = _('03-03 Forecast Aggregate')
        verbose_name_plural = _('03-03 Forecast Aggregates')

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        self.final_qty = (
            self.override_qty
            if self.override_qty is not None
            else self.statistical_qty
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f'{self.version.version_label} | '
            f'{self.agg_level}:{self.agg_key} | '
            f'{self.period_type}:{self.period_start} | final={self.final_qty}'
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. ForecastOverride
# ─────────────────────────────────────────────────────────────────────────────

class ForecastOverride(models.Model):
    """
    A planner's consensus edit to the statistical forecast.

    Overrides can be entered at ANY level of any hierarchy:
      - SKU level        → directly updates one ForecastLine.override_qty
      - Category level   → disaggregated down to SKU lines via disagg_method
      - Region level     → disaggregated down to location lines
      - Total level      → disaggregated across everything

    The Celery disaggregation task (Sprint 3B.4) reads ForecastOverride rows
    and pushes the values down to ForecastLine.override_qty.

    override_qty and override_pct are mutually exclusive:
      - override_qty: set the absolute forecast value (e.g. "I want 500 units")
      - override_pct: adjust by percentage (e.g. "+10%" or "-5%")
    """

    class DisaggMethod(models.TextChoices):
        PROPORTIONAL = 'PROPORTIONAL', _('Proportional (historical share)')
        EQUAL        = 'EQUAL',        _('Equal split across children')
        CUSTOM       = 'CUSTOM',       _('Custom weights (see OverrideSplitWeight)')

    OVERRIDE_LEVEL_CHOICES = [
        ('sku',         _('SKU (item level)')),
        ('subcategory', _('Sub-category')),
        ('category',    _('Category')),
        ('location',    _('Location')),
        ('region',      _('Region')),
        ('customer',    _('Customer')),
        ('channel',     _('Channel')),
        ('total',       _('Grand Total')),
    ]

    version = models.ForeignKey(
        ForecastVersion,
        on_delete=models.CASCADE,
        related_name='overrides',
        verbose_name=_('forecast version'),
    )
    override_level = models.CharField(
        _('override level'),
        max_length=32,
        choices=OVERRIDE_LEVEL_CHOICES,
    )
    override_key = models.JSONField(
        _('override key'),
        help_text=_(
            'JSON identifying what is being overridden. '
            'e.g. {"item_id": "ITEM-001"} or {"category": "Braking Systems"}'
        ),
    )
    # Period
    period_type  = models.CharField(_('period type'),  max_length=16, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField(_('period start'))
    period_end   = models.DateField(_('period end'), editable=False)
    # Override value — one of these two must be set, not both
    override_qty = models.DecimalField(
        _('override quantity'),
        max_digits=14,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=_('Absolute quantity override. Mutually exclusive with override_pct.'),
    )
    override_pct = models.DecimalField(
        _('override percentage'),
        max_digits=7,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=_(
            'Percentage adjustment, e.g. 10.0 = +10%, -5.0 = -5%. '
            'Mutually exclusive with override_qty.'
        ),
    )
    disagg_method = models.CharField(
        _('disaggregation method'),
        max_length=16,
        choices=DisaggMethod.choices,
        default=DisaggMethod.PROPORTIONAL,
        help_text=_(
            'How this override is disaggregated to child levels. '
            'CUSTOM requires OverrideSplitWeight rows.'
        ),
    )
    override_note = models.TextField(
        _('override note'),
        blank=True,
        help_text=_('Reason for override. Visible in the audit trail.'),
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='forecast_overrides',
        verbose_name=_('created by'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Track whether the Celery disaggregation task has processed this override
    is_applied = models.BooleanField(
        _('is applied'),
        default=False,
        help_text=_(
            'True once the disaggregation task has pushed this override '
            'down to ForecastLine.override_qty.'
        ),
    )

    class Meta:
        app_label = 'mysite'
        ordering  = ['-created_at']
        verbose_name        = _('03-04 Forecast Override')
        verbose_name_plural = _('03-04 Forecast Overrides')
        indexes = [
            models.Index(
                fields=['version', 'override_level', 'period_start'],
                name='ix_fcastoverride_ver_level',
            ),
            models.Index(
                fields=['version', 'is_applied'],
                name='ix_fcastoverride_ver_applied',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f'{self.version.version_label} | '
            f'{self.override_level}:{self.override_key} | '
            f'{self.period_type}:{self.period_start}'
        )

    def clean(self):
        # Version must be in DRAFT
        if self.version_id:
            try:
                version = ForecastVersion.objects.get(pk=self.version_id)
                version.assert_editable()
            except ForecastVersion.DoesNotExist:
                pass

        # Exactly one of override_qty / override_pct must be set
        has_qty = self.override_qty is not None
        has_pct = self.override_pct is not None
        if has_qty and has_pct:
            raise ValidationError(
                _('Set either override_qty or override_pct, not both.')
            )
        if not has_qty and not has_pct:
            raise ValidationError(
                _('One of override_qty or override_pct must be set.')
            )

        # CUSTOM disagg requires OverrideSplitWeight rows (validated post-save)
        # Period anchor validation
        if self.period_start and self.period_type:
            try:
                validate_period_start(self.period_start, self.period_type)
            except ValueError as exc:
                raise ValidationError({'period_start': str(exc)})


# ─────────────────────────────────────────────────────────────────────────────
# 5. OverrideSplitWeight
# ─────────────────────────────────────────────────────────────────────────────

class OverrideSplitWeight(models.Model):
    """
    Explicit weight for one child node when an override uses disagg_method=CUSTOM.

    Example: A category-level override of 1000 units split CUSTOM across 3 SKUs:
      OverrideSplitWeight(override=X, child_key={"item_id": "SKU-001"}, weight=0.50)
      OverrideSplitWeight(override=X, child_key={"item_id": "SKU-002"}, weight=0.30)
      OverrideSplitWeight(override=X, child_key={"item_id": "SKU-003"}, weight=0.20)

    Weights should sum to 1.0 but this is enforced by the disaggregation task,
    not at the DB level (allows partial entry during interactive editing).
    """

    override = models.ForeignKey(
        ForecastOverride,
        on_delete=models.CASCADE,
        related_name='split_weights',
        verbose_name=_('override'),
    )
    child_key = models.JSONField(
        _('child key'),
        help_text=_(
            'JSON identifying the child node receiving this weight. '
            'e.g. {"item_id": "SKU-001"} or {"location_code": "DEL"}'
        ),
    )
    weight = models.DecimalField(
        _('weight'),
        max_digits=8,
        decimal_places=6,
        help_text=_('Proportion of the override allocated to this child. Should sum to 1.0 across all children.'),
    )

    class Meta:
        app_label = 'mysite'
        verbose_name        = _('03-05 Override Split Weight')
        verbose_name_plural = _('03-05 Override Split Weights')

    def __str__(self):
        return f'{self.override} | child={self.child_key} | weight={self.weight}'

    def clean(self):
        if self.weight is not None and (self.weight < 0 or self.weight > 1):
            raise ValidationError(
                _('Weight must be between 0 and 1.')
            )
        if self.override_id:
            override = ForecastOverride.objects.filter(pk=self.override_id).first()
            if override and override.disagg_method != ForecastOverride.DisaggMethod.CUSTOM:
                raise ValidationError(
                    _('OverrideSplitWeight only applies to overrides with disagg_method=CUSTOM.')
                )


# ─────────────────────────────────────────────────────────────────────────────
# 6. ForecastAccuracy
# ─────────────────────────────────────────────────────────────────────────────

class ForecastAccuracy(models.Model):
    """
    Accuracy metrics computed once actuals land for the forecast period.

    Populated by a Celery task (Sprint 3B.4) that joins ForecastLine.final_qty
    against ActualSale.qty for matching (item, customer, location, period).

    Metrics:
      mape  = |actual - forecast| / actual × 100  (Mean Absolute Percentage Error)
      bias  = (forecast - actual) / actual × 100  (positive = over-forecast)
    """

    version = models.ForeignKey(
        ForecastVersion,
        on_delete=models.CASCADE,
        related_name='accuracy_records',
        verbose_name=_('forecast version'),
    )
    item = models.ForeignKey(
        'mysite.Item',
        on_delete=models.PROTECT,
        related_name='forecast_accuracy',
        verbose_name=_('item'),
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='forecast_accuracy',
        verbose_name=_('planning customer'),
    )
    planning_location = models.ForeignKey(
        PlanningLocation,
        on_delete=models.PROTECT,
        related_name='forecast_accuracy',
        verbose_name=_('planning location'),
    )
    # Period
    period_type  = models.CharField(_('period type'),  max_length=16, choices=PERIOD_TYPE_CHOICES)
    period_start = models.DateField(_('period start'))
    period_end   = models.DateField(_('period end'), editable=False)
    # Values
    actual_qty   = models.DecimalField(
        _('actual qty'), max_digits=14, decimal_places=3,
    )
    forecast_qty = models.DecimalField(
        _('forecast qty'), max_digits=14, decimal_places=3,
        help_text=_('final_qty from ForecastLine at time of accuracy computation.'),
    )
    mape = models.DecimalField(
        _('MAPE (%)'), max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_('Mean Absolute Percentage Error. Null if actual_qty = 0.'),
    )
    bias = models.DecimalField(
        _('Bias (%)'), max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Forecast bias percentage. Positive = over-forecast, negative = under-forecast.'
        ),
    )
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [
            (
                'version', 'item', 'planning_customer',
                'planning_location', 'period_type', 'period_start',
            ),
        ]
        ordering    = ['period_start', 'item']
        verbose_name        = _('03-06 Forecast Accuracy')
        verbose_name_plural = _('03-06 Forecast Accuracy Records')
        indexes = [
            models.Index(
                fields=['version', 'period_start'],
                name='ix_fcastacc_ver_period',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f'{self.version.version_label} | '
            f'{self.item} | {self.period_type}:{self.period_start} | '
            f'MAPE={self.mape}%'
        )
```

---

## 3. State Machine — `ForecastVersion.status`

The state machine is implemented in `transition_to()` on the model itself (above).
Here is a summary of every guard and side effect:

```
DRAFT
  ├── Who can edit:    anyone with forecast_run permission
  ├── Can add lines:   YES (Celery task populates)
  ├── Can override:    YES (planners)
  └── Transitions to: IN_REVIEW (submit for approval)

IN_REVIEW
  ├── Who can edit:    nobody — read-only
  ├── Can add lines:   NO
  ├── Can override:    NO
  └── Transitions to: APPROVED (approver accepts)
                       DRAFT    (approver sends back with comments)

APPROVED
  ├── Who can edit:    nobody — read-only
  ├── Can add lines:   NO
  ├── Can override:    NO
  └── Transitions to: LOCKED (superadmin or auto after grace period)

LOCKED  (terminal)
  ├── Who can edit:    nobody — immutable
  ├── Can add lines:   NO
  ├── Can override:    NO
  ├── Transitions to:  (none)
  └── Can copy():      YES → produces new DRAFT
```

### Where to enforce the guard in the API

The `assert_editable()` call goes at the **top of every mutation view**,
before any other processing:

```python
# In any view that modifies a version or its children:
version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
try:
    version.assert_editable()
except ValidationError as exc:
    return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
```

---

## 4. Migration

### 4.1 Generate

```bash
python manage.py makemigrations mysite --name forecast_models
```

### 4.2 Add RunSQL indexes

Edit the generated migration and append these `RunSQL` operations at the end
of the `operations` list:

```python
migrations.RunSQL(
    sql="""
        -- ForecastLine: fast lookup by version + period
        CREATE INDEX IF NOT EXISTS ix_forecastline_version
            ON mysite_forecastline (version_id, period_start);

        -- ForecastLine: item-level time series per version
        CREATE INDEX IF NOT EXISTS ix_forecastline_item_period
            ON mysite_forecastline (version_id, item_id, period_start);

        -- ForecastLine: location drill-down
        CREATE INDEX IF NOT EXISTS ix_forecastline_location_period
            ON mysite_forecastline (version_id, planning_location_id, period_start);

        -- ForecastAggregate: version + level + period (the primary access pattern)
        CREATE INDEX IF NOT EXISTS ix_forecastaggregate_version_level
            ON mysite_forecastaggregate (version_id, agg_level, period_start);

        -- ForecastAccuracy: version + period for accuracy reports
        CREATE INDEX IF NOT EXISTS ix_forecastaccuracy_version_period
            ON mysite_forecastaccuracy (version_id, period_start);
    """,
    reverse_sql="""
        DROP INDEX IF EXISTS ix_forecastline_version;
        DROP INDEX IF EXISTS ix_forecastline_item_period;
        DROP INDEX IF EXISTS ix_forecastline_location_period;
        DROP INDEX IF EXISTS ix_forecastaggregate_version_level;
        DROP INDEX IF EXISTS ix_forecastaccuracy_version_period;
    """,
),
```

### 4.3 Apply

```bash
python manage.py migrate
python manage.py check
```

### 4.4 Wire into `demand/__init__.py`

```python
# mysite/models/demand/__init__.py — add these imports:

from mysite.models.demand.forecast import (
    ForecastVersion,
    ForecastLine,
    ForecastAggregate,
    ForecastOverride,
    OverrideSplitWeight,
    ForecastAccuracy,
)
```

---

## 5. Admin

```python
# mysite/admin/demand_forecast.py  (create this file)

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAggregate,
    ForecastOverride, OverrideSplitWeight, ForecastAccuracy,
)


# ── ForecastLine inline (read-only, paginated) ────────────────────────────────

class ForecastLineInline(admin.TabularInline):
    model          = ForecastLine
    extra          = 0
    can_delete     = False
    max_num        = 0          # no "add" button
    show_change_link = True
    fields         = [
        'period_type', 'period_start', 'item',
        'planning_location', 'planning_customer',
        'statistical_qty', 'override_qty', 'final_qty',
    ]
    readonly_fields = fields

    def get_queryset(self, request):
        # Limit inline to first 50 rows to keep admin responsive
        return (
            super().get_queryset(request)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('period_start', 'item__item_id')[:50]
        )


# ── ForecastOverride inline ───────────────────────────────────────────────────

class ForecastOverrideInline(admin.TabularInline):
    model       = ForecastOverride
    extra       = 0
    can_delete  = False
    fields      = [
        'override_level', 'override_key', 'period_start',
        'override_qty', 'override_pct', 'disagg_method',
        'is_applied', 'created_by', 'created_at',
    ]
    readonly_fields = ['is_applied', 'created_by', 'created_at']

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('created_by')
            .order_by('-created_at')[:20]
        )


# ── ForecastVersionAdmin ──────────────────────────────────────────────────────

@admin.register(ForecastVersion)
class ForecastVersionAdmin(admin.ModelAdmin):

    list_display = [
        'version_label', 'client', 'period_type',
        'base_period_end', 'horizon_periods',
        'status_badge', 'created_by', 'created_at',
    ]
    list_filter  = ['client', 'status', 'period_type']
    search_fields = ['version_label', 'client__client_id']
    readonly_fields = [
        'status', 'approved_by', 'approved_at', 'locked_at',
        'copied_from', 'created_at', 'updated_at',
    ]
    fieldsets = [
        (_('Identity'), {
            'fields': [
                'client', 'version_label', 'notes', 'copied_from',
            ],
        }),
        (_('Period Configuration'), {
            'fields': [
                'period_type', 'base_period_end', 'horizon_periods',
            ],
        }),
        (_('Engine Configuration'), {
            'fields': ['engine_config'],
            'classes': ['collapse'],
        }),
        (_('Workflow'), {
            'fields': [
                'status', 'created_by',
                'approved_by', 'approved_at', 'locked_at',
            ],
        }),
        (_('Audit'), {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse'],
        }),
    ]
    inlines = [ForecastOverrideInline, ForecastLineInline]

    @admin.display(description=_('Status'))
    def status_badge(self, obj):
        colours = {
            'DRAFT':     '#6c757d',
            'IN_REVIEW': '#fd7e14',
            'APPROVED':  '#198754',
            'LOCKED':    '#0d6efd',
        }
        colour = colours.get(obj.status, '#000')
        return format_html(
            '<span style="'
            'background:{colour};color:#fff;padding:2px 8px;'
            'border-radius:4px;font-size:11px;font-weight:bold">'
            '{label}</span>',
            colour=colour,
            label=obj.get_status_display(),
        )

    def get_readonly_fields(self, request, obj=None):
        # Once not DRAFT, make all fields read-only except notes
        if obj and not obj.is_editable:
            editable = {'notes'}
            all_fields = [f.name for f in self.model._meta.fields]
            return [f for f in all_fields if f not in editable]
        return self.readonly_fields

    admin_role_only = True


# ── ForecastLineAdmin (standalone, for direct access) ────────────────────────

@admin.register(ForecastLine)
class ForecastLineAdmin(admin.ModelAdmin):
    list_display   = [
        'version', 'period_type', 'period_start',
        'item', 'planning_location', 'planning_customer',
        'statistical_qty', 'override_qty', 'final_qty',
    ]
    list_filter    = ['version__client', 'period_type', 'version__status']
    search_fields  = [
        'item__item_id', 'item__name',
        'planning_location__code', 'planning_customer__code',
        'version__version_label',
    ]
    date_hierarchy = 'period_start'
    readonly_fields = ['period_end', 'final_qty']

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related(
                'version', 'item',
                'planning_location', 'planning_customer',
            )
        )

    admin_role_only = True


# ── ForecastAccuracyAdmin ─────────────────────────────────────────────────────

@admin.register(ForecastAccuracy)
class ForecastAccuracyAdmin(admin.ModelAdmin):
    list_display  = [
        'version', 'period_start', 'item',
        'actual_qty', 'forecast_qty', 'mape', 'bias',
    ]
    list_filter   = ['version__client', 'period_type']
    search_fields = ['item__item_id', 'version__version_label']
    readonly_fields = [
        'version', 'item', 'planning_customer', 'planning_location',
        'period_type', 'period_start', 'period_end',
        'actual_qty', 'forecast_qty', 'mape', 'bias', 'computed_at',
    ]
    admin_role_only = True
```

---

## 6. Serializers

Add to `mysite/api/demand/serializers.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Forecast serializers
# ─────────────────────────────────────────────────────────────────────────────

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine,
    ForecastAggregate, ForecastOverride,
)


class ForecastVersionSerializer(serializers.ModelSerializer):
    created_by_name  = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()
    line_count       = serializers.SerializerMethodField()
    is_editable      = serializers.BooleanField(read_only=True)

    class Meta:
        model  = ForecastVersion
        fields = [
            'id', 'version_label', 'period_type',
            'base_period_end', 'horizon_periods',
            'engine_config', 'status', 'is_editable',
            'created_by_name', 'approved_by_name',
            'approved_at', 'locked_at', 'copied_from',
            'notes', 'created_at', 'updated_at',
            'line_count',
        ]
        read_only_fields = [
            'status', 'approved_by_name', 'approved_at',
            'locked_at', 'created_at', 'updated_at', 'is_editable',
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None

    def get_approved_by_name(self, obj):
        if obj.approved_by:
            return obj.approved_by.get_full_name() or obj.approved_by.username
        return None

    def get_line_count(self, obj):
        # Use annotated value if present (avoids extra query)
        return getattr(obj, 'line_count', None)


class ForecastVersionCreateSerializer(serializers.ModelSerializer):
    """Used for POST /forecast-versions/ — fewer writable fields."""

    class Meta:
        model  = ForecastVersion
        fields = [
            'version_label', 'period_type',
            'base_period_end', 'horizon_periods',
            'engine_config', 'notes',
        ]

    def validate_base_period_end(self, value):
        import datetime
        if value > datetime.date.today():
            raise serializers.ValidationError(
                'base_period_end cannot be in the future.'
            )
        return value


class ForecastLineSerializer(serializers.ModelSerializer):
    item_id       = serializers.CharField(source='item.item_id',         read_only=True)
    item_name     = serializers.CharField(source='item.name',            read_only=True)
    location_code = serializers.CharField(
        source='planning_location.code', read_only=True
    )
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )

    class Meta:
        model  = ForecastLine
        fields = [
            'id',
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_type', 'period_start', 'period_end',
            'statistical_qty', 'override_qty', 'final_qty',
        ]
        read_only_fields = ['period_end', 'final_qty', 'statistical_qty']


class ForecastAggregateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ForecastAggregate
        fields = [
            'id', 'agg_level', 'agg_key',
            'period_type', 'period_start', 'period_end',
            'statistical_qty', 'override_qty', 'final_qty',
        ]
        read_only_fields = fields


class ForecastOverrideSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = ForecastOverride
        fields = [
            'id', 'override_level', 'override_key',
            'period_type', 'period_start',
            'override_qty', 'override_pct',
            'disagg_method', 'override_note',
            'is_applied', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['is_applied', 'created_at', 'created_by_name']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None
```

---

## 7. Views

Add to `mysite/api/demand/views.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Forecast Version views
# ─────────────────────────────────────────────────────────────────────────────

from django.db.models import Count
from django.core.paginator import Paginator, EmptyPage
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAggregate,
)
from mysite.api.demand.serializers import (
    ForecastVersionSerializer,
    ForecastVersionCreateSerializer,
    ForecastLineSerializer,
    ForecastAggregateSerializer,
)
from utils.feature_control import is_demand_feature_disabled


class ForecastVersionListCreateView(DemandFeatureMixin, APIView):
    """
    GET  /api/demand/forecast-versions/
         List all versions for the client. Filterable by status.

    POST /api/demand/forecast-versions/
         Create a new DRAFT version.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            ForecastVersion.objects
            .filter(client=request.client)
            .annotate(line_count=Count('lines'))
            .select_related('created_by', 'approved_by')
            .order_by('-created_at')
        )
        # Filter by status
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        serializer = ForecastVersionSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        # Check forecast_run feature flag
        result = is_demand_feature_disabled(request.client, 'forecast_run')
        if result['disabled']:
            return Response(
                {'detail': result['message']},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ForecastVersionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        version = serializer.save(
            client     = request.client,
            created_by = request.user,
            status     = ForecastVersion.Status.DRAFT,
        )
        return Response(
            ForecastVersionSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )


class ForecastVersionDetailView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/
        Retrieve a single version with metadata.
    """
    permission_classes = [IsAuthenticated]

    def _get_version(self, request, pk):
        return get_object_or_404(
            ForecastVersion
            .objects
            .annotate(line_count=Count('lines'))
            .select_related('created_by', 'approved_by'),
            pk=pk,
            client=request.client,
        )

    def get(self, request, pk):
        version = self._get_version(request, pk)
        return Response(ForecastVersionSerializer(version).data)


class ForecastVersionLinesView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/lines/

    Paginated, filterable list of ForecastLine rows for a version.

    Query params:
        item_id         — filter by Item.item_id
        location_code   — filter by PlanningLocation.code
        customer_code   — filter by PlanningCustomer.code
        period_start    — ISO date, filter period_start >= value
        period_end      — ISO date, filter period_end <= value
        has_override    — true/false, filter lines with/without override_qty
        page            — default 1
        page_size       — default 100, max 500
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import datetime

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        qs = (
            ForecastLine.objects
            .filter(version=version)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('period_start', 'planning_location__code', 'item__item_id')
        )

        p = request.query_params

        if p.get('item_id'):
            qs = qs.filter(item__item_id=p['item_id'])
        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])
        if p.get('customer_code'):
            qs = qs.filter(planning_customer__code=p['customer_code'])
        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response(
                    {'period_start': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                return Response(
                    {'period_end': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('has_override') == 'true':
            qs = qs.filter(override_qty__isnull=False)
        elif p.get('has_override') == 'false':
            qs = qs.filter(override_qty__isnull=True)

        try:
            page_size = min(int(p.get('page_size', 100)), 500)
            page_num  = int(p.get('page', 1))
        except ValueError:
            page_size, page_num = 100, 1

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        return Response({
            'version_id':   version.pk,
            'version_label': version.version_label,
            'count':    paginator.count,
            'next':     self._page_url(request, page_num + 1, paginator.num_pages),
            'previous': self._page_url(request, page_num - 1, paginator.num_pages),
            'results':  ForecastLineSerializer(page.object_list, many=True).data,
        })

    def _page_url(self, request, page_num, num_pages):
        if page_num < 1 or page_num > num_pages:
            return None
        params = request.query_params.copy()
        params['page'] = page_num
        return request.build_absolute_uri(f'?{params.urlencode()}')


class ForecastVersionAggregatesView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/aggregates/

    Query params:
        agg_level   — filter by level (category, region, total, etc.)
        period_start — ISO date
        period_end   — ISO date
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import datetime

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        qs = (
            ForecastAggregate.objects
            .filter(version=version)
            .order_by('agg_level', 'period_start')
        )

        p = request.query_params
        if p.get('agg_level'):
            qs = qs.filter(agg_level=p['agg_level'])
        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response(
                    {'period_start': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                return Response(
                    {'period_end': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(ForecastAggregateSerializer(qs, many=True).data)


class ForecastVersionApproveView(DemandFeatureMixin, APIView):
    """
    POST /api/demand/forecast-versions/{id}/approve/

    Body (JSON):
        {
            "action":  "submit" | "approve" | "reject" | "lock" | "copy",
            "note":    "optional reason or label for copy action"
        }

    Action → transition map:
        submit  → DRAFT → IN_REVIEW
        approve → IN_REVIEW → APPROVED
        reject  → IN_REVIEW → DRAFT
        lock    → APPROVED → LOCKED
        copy    → LOCKED (any) → new DRAFT  (returns new version)

    Returns the updated (or new) ForecastVersion.
    """
    permission_classes = [IsAuthenticated]

    ACTION_TRANSITIONS = {
        'submit':  ForecastVersion.Status.IN_REVIEW,
        'approve': ForecastVersion.Status.APPROVED,
        'reject':  ForecastVersion.Status.DRAFT,
        'lock':    ForecastVersion.Status.LOCKED,
    }

    def post(self, request, pk):
        # Feature gate
        result = is_demand_feature_disabled(request.client, 'forecast_approval')
        if result['disabled']:
            return Response(
                {'detail': result['message']},
                status=status.HTTP_403_FORBIDDEN,
            )

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        action = request.data.get('action', '').strip().lower()
        note   = request.data.get('note', '').strip()

        # ── copy action ───────────────────────────────────────────────────────
        if action == 'copy':
            new_label   = note or f'{version.version_label} (copy)'
            new_version = version.copy(user=request.user, new_label=new_label)
            return Response(
                ForecastVersionSerializer(new_version).data,
                status=status.HTTP_201_CREATED,
            )

        # ── transition actions ────────────────────────────────────────────────
        if action not in self.ACTION_TRANSITIONS:
            return Response(
                {
                    'detail': (
                        f'Unknown action "{action}". '
                        f'Valid: submit, approve, reject, lock, copy.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = self.ACTION_TRANSITIONS[action]

        try:
            version.transition_to(new_status, user=request.user)
        except DjangoValidationError as exc:
            return Response(
                {'detail': exc.message},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Append note to version notes if provided
        if note:
            version.notes = (version.notes + f'\n[{action}] {note}').strip()
            version.save(update_fields=['notes'])

        version.refresh_from_db()
        return Response(ForecastVersionSerializer(version).data)
```

---

## 8. URLs

Add to `mysite/api/demand/urls.py`:

```python
# Append to existing urlpatterns list:

from mysite.api.demand import views

urlpatterns += [
    # ── Forecast Versions ──────────────────────────────────────────────────
    path(
        'forecast-versions/',
        views.ForecastVersionListCreateView.as_view(),
        name='demand-forecast-versions',
    ),
    path(
        'forecast-versions/<int:pk>/',
        views.ForecastVersionDetailView.as_view(),
        name='demand-forecast-version-detail',
    ),
    path(
        'forecast-versions/<int:pk>/lines/',
        views.ForecastVersionLinesView.as_view(),
        name='demand-forecast-version-lines',
    ),
    path(
        'forecast-versions/<int:pk>/aggregates/',
        views.ForecastVersionAggregatesView.as_view(),
        name='demand-forecast-version-aggregates',
    ),
    path(
        'forecast-versions/<int:pk>/approve/',
        views.ForecastVersionApproveView.as_view(),
        name='demand-forecast-version-approve',
    ),
]
```

---

## 9. Unit Tests

```python
# mysite/tests/demand/test_forecast.py

import pytest
import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine,
    ForecastOverride, OverrideSplitWeight,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def staff_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='planner', password='pw',
        first_name='Test', last_name='Planner',
    )


@pytest.fixture
def approver_user(db, django_user_model):
    return django_user_model.objects.create_user(
        username='approver', password='pw',
    )


@pytest.fixture
def draft_version(db, client_obj, staff_user):
    return ForecastVersion.objects.create(
        client          = client_obj,
        version_label   = 'Jan-2025 Monthly v1',
        period_type     = 'month',
        base_period_end = datetime.date(2024, 12, 31),
        horizon_periods = 6,
        status          = ForecastVersion.Status.DRAFT,
        created_by      = staff_user,
    )


@pytest.fixture
def forecast_line(db, draft_version, active_item, leaf_location, planning_customer):
    return ForecastLine.objects.create(
        version           = draft_version,
        item              = active_item,
        planning_location = leaf_location,
        planning_customer = planning_customer,
        period_type       = 'month',
        period_start      = datetime.date(2025, 1, 1),
        statistical_qty   = Decimal('480.000'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: final_qty computation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastLineFinalQty:

    def test_final_qty_equals_statistical_when_no_override(self, forecast_line):
        """final_qty = statistical_qty when override_qty is None."""
        assert forecast_line.override_qty is None
        assert forecast_line.final_qty == Decimal('480.000')

    def test_final_qty_equals_override_when_set(self, forecast_line):
        """final_qty = override_qty when override_qty is set."""
        forecast_line.override_qty = Decimal('550.000')
        forecast_line.save()
        forecast_line.refresh_from_db()

        assert forecast_line.final_qty == Decimal('550.000')
        assert forecast_line.statistical_qty == Decimal('480.000')  # unchanged

    def test_final_qty_reverts_when_override_cleared(self, forecast_line):
        """Clearing override_qty causes final_qty to revert to statistical_qty."""
        forecast_line.override_qty = Decimal('600.000')
        forecast_line.save()

        forecast_line.override_qty = None
        forecast_line.save()
        forecast_line.refresh_from_db()

        assert forecast_line.final_qty == Decimal('480.000')

    def test_final_qty_zero_override_is_valid(self, forecast_line):
        """override_qty=0 is a valid override (e.g. planner sets demand to zero)."""
        forecast_line.override_qty = Decimal('0.000')
        forecast_line.save()
        forecast_line.refresh_from_db()

        # 0 is not None, so final_qty should be 0, not statistical_qty
        assert forecast_line.final_qty == Decimal('0.000')

    def test_period_end_auto_computed(self, forecast_line):
        """period_end is auto-computed from period_type + period_start."""
        assert forecast_line.period_end == datetime.date(2025, 1, 31)


# ─────────────────────────────────────────────────────────────────────────────
# Test: State machine transitions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastVersionStateMachine:

    def test_draft_transitions_to_in_review(self, draft_version, staff_user):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.refresh_from_db()
        assert draft_version.status == ForecastVersion.Status.IN_REVIEW

    def test_in_review_transitions_to_approved(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.refresh_from_db()

        assert draft_version.status == ForecastVersion.Status.APPROVED
        assert draft_version.approved_by == approver_user
        assert draft_version.approved_at is not None

    def test_approved_transitions_to_locked(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)
        draft_version.refresh_from_db()

        assert draft_version.status == ForecastVersion.Status.LOCKED
        assert draft_version.locked_at is not None

    def test_locked_rejects_all_transitions(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        with pytest.raises(ValidationError):
            draft_version.transition_to(ForecastVersion.Status.DRAFT, staff_user)

    def test_invalid_transition_raises_validation_error(
        self, draft_version, staff_user
    ):
        """DRAFT cannot jump directly to APPROVED."""
        with pytest.raises(ValidationError):
            draft_version.transition_to(ForecastVersion.Status.APPROVED, staff_user)

    def test_in_review_can_be_sent_back_to_draft(
        self, draft_version, staff_user, approver_user
    ):
        """Approver can send back to DRAFT for rework."""
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.DRAFT, approver_user)
        draft_version.refresh_from_db()
        assert draft_version.status == ForecastVersion.Status.DRAFT


# ─────────────────────────────────────────────────────────────────────────────
# Test: LOCKED version rejects edits via API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLockedVersionRejectsEdits:

    def _lock_version(self, version, staff_user, approver_user):
        version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        version.transition_to(ForecastVersion.Status.LOCKED, approver_user)
        version.refresh_from_db()

    def test_locked_version_is_not_editable(
        self, draft_version, staff_user, approver_user
    ):
        self._lock_version(draft_version, staff_user, approver_user)
        assert not draft_version.is_editable
        assert draft_version.is_locked

    def test_assert_editable_raises_on_locked_version(
        self, draft_version, staff_user, approver_user
    ):
        self._lock_version(draft_version, staff_user, approver_user)
        with pytest.raises(ValidationError):
            draft_version.assert_editable()

    def test_api_returns_403_on_locked_version(
        self, draft_version, staff_user, approver_user, client_obj,
        django_user_model
    ):
        """POST to approve/ on a LOCKED version returns 403."""
        from rest_framework.test import APIClient
        from django.urls import reverse

        self._lock_version(draft_version, staff_user, approver_user)

        api = APIClient()
        api.force_authenticate(user=staff_user)

        url = reverse('demand-forecast-version-approve', kwargs={'pk': draft_version.pk})
        response = api.post(url, {'action': 'submit'}, format='json')

        # submit from LOCKED is an invalid transition → 403
        assert response.status_code == 403

    def test_override_on_locked_version_raises(
        self, draft_version, staff_user, approver_user,
        active_item, leaf_location
    ):
        """Creating a ForecastOverride on a LOCKED version raises ValidationError."""
        self._lock_version(draft_version, staff_user, approver_user)

        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = Decimal('600'),
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Version copy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastVersionCopy:

    def test_copy_creates_new_draft(
        self, draft_version, forecast_line,
        staff_user, approver_user
    ):
        """copy() produces a new DRAFT version."""
        # Lock the original
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version = draft_version.copy(user=staff_user, new_label='Feb-2025 Plan v1')

        assert new_version.status == ForecastVersion.Status.DRAFT
        assert new_version.version_label == 'Feb-2025 Plan v1'
        assert new_version.copied_from == draft_version
        assert new_version.client == draft_version.client

    def test_copy_clones_all_lines(
        self, draft_version, forecast_line,
        staff_user, approver_user,
        active_item, leaf_location, planning_customer
    ):
        """Copied version has same number of ForecastLine rows."""
        # Add a second line
        ForecastLine.objects.create(
            version           = draft_version,
            item              = active_item,
            planning_location = leaf_location,
            planning_customer = None,
            period_type       = 'month',
            period_start      = datetime.date(2025, 2, 1),
            statistical_qty   = Decimal('320.000'),
        )
        original_count = draft_version.lines.count()

        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version = draft_version.copy(user=staff_user)
        assert new_version.lines.count() == original_count

    def test_copy_preserves_override_qty(
        self, draft_version, forecast_line,
        staff_user, approver_user
    ):
        """Copied lines preserve override_qty and recompute final_qty."""
        forecast_line.override_qty = Decimal('550.000')
        forecast_line.save()

        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version  = draft_version.copy(user=staff_user)
        cloned_line  = new_version.lines.first()

        assert cloned_line.override_qty == Decimal('550.000')
        assert cloned_line.final_qty    == Decimal('550.000')
        assert cloned_line.statistical_qty == Decimal('480.000')

    def test_copy_of_draft_also_works(self, draft_version, forecast_line, staff_user):
        """copy() works from any status, not just LOCKED."""
        new_version = draft_version.copy(user=staff_user, new_label='Draft Copy')
        assert new_version.status == ForecastVersion.Status.DRAFT
        assert new_version.lines.count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastOverride validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastOverrideValidation:

    def test_cannot_set_both_qty_and_pct(self, draft_version, staff_user):
        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = Decimal('500'),
            override_pct   = Decimal('10'),
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()

    def test_must_set_one_of_qty_or_pct(self, draft_version, staff_user):
        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = None,
            override_pct   = None,
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()
```

---

## 10. Final Checklist

- [ ] `mysite/models/demand/forecast.py` created with all six models
- [ ] `demand/__init__.py` updated to import all six models
- [ ] `python manage.py makemigrations mysite --name forecast_models`
- [ ] `RunSQL` index block added to generated migration
- [ ] `python manage.py migrate` — clean
- [ ] `python manage.py check` — 0 issues
- [ ] Admin file created and registered; `ForecastVersionAdmin` shows status badge
- [ ] Serializers added to `mysite/api/demand/serializers.py`
- [ ] Five views added to `mysite/api/demand/views.py`
- [ ] Five URL patterns added to `mysite/api/demand/urls.py`
- [ ] `GET /api/demand/forecast-versions/` returns empty list for new client
- [ ] `POST /api/demand/forecast-versions/` creates DRAFT version
- [ ] `POST /api/demand/forecast-versions/{id}/approve/` with `action=submit` moves to IN_REVIEW
- [ ] `POST /api/demand/forecast-versions/{id}/approve/` with `action=copy` on LOCKED returns new DRAFT
- [ ] `GET /api/demand/forecast-versions/{id}/lines/` returns paginated results
- [ ] All unit tests pass: `pytest mysite/tests/demand/test_forecast.py -v`

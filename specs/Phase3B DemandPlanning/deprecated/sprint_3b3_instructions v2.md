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

  SeriesProfile       - New Addition
"""
from __future__ import annotations
from typing import TYPE_CHECKING
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
if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

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

    def transition_to(self, new_status: str, user: AbstractBaseUser) -> None:
    #def transition_to(self, new_status: str, user: User) -> None:
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

    def copy(self, user: AbstractBaseUser, new_label: str = None) -> ForecastVersion:
    #def copy(self, user: User, new_label: str = None) -> 'ForecastVersion':
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
    # Add to ForecastLine, after override_qty:

    forecast_level = models.CharField(
        _('forecast level'),
        max_length=32,
        blank=True,
        default='sku_customer_location',
        help_text=_(
            'The aggregation level at which the statistical forecast was actually '
            'computed before disaggregation. '
            'e.g. "sku_customer_location" (atomic), "sku_location" (no customer), '
            '"location" (all items aggregated to location).'
        ),
    )
    model_used = models.CharField(
        _('model used'),
        max_length=32,
        blank=True,
        help_text=_(
            'The StatsForecast model that produced statistical_qty. '
            'e.g. "AutoETS", "CrostonSBA", "MovingAverage".'
        ),
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

class SeriesProfile(models.Model):
    """
    Computed demand characteristics for one (item, customer, location) series.

    Populated by a Celery task that runs before forecast generation.
    The forecasting engine reads this to decide:
      a) which model to use (AutoETS vs Croston vs aggregate)
      b) at what level to forecast (SKU×Customer×Location vs SKU×Location vs Location)

    Metrics follow the Syntetos-Boylan (2005) classification framework.
    """

    class DemandClass(models.TextChoices):
        SMOOTH       = 'SMOOTH',       _('Smooth — regular frequent demand')
        ERRATIC      = 'ERRATIC',      _('Erratic — frequent but variable quantity')
        INTERMITTENT = 'INTERMITTENT', _('Intermittent — sparse but stable quantity')
        LUMPY        = 'LUMPY',        _('Lumpy — sparse and variable quantity')
        INSUFFICIENT = 'INSUFFICIENT', _('Insufficient data — fewer than min_obs non-zero periods')
        ZERO         = 'ZERO',         _('Zero demand — no non-zero observations')

    class ForecastStrategy(models.TextChoices):
        # Forecast at this exact granularity using the named model
        AUTOETS      = 'AUTOETS',      _('AutoETS (smooth/erratic series)')
        AUTOARIMA    = 'AUTOARIMA',    _('AutoARIMA (erratic series)')
        CROSTON      = 'CROSTON',      _('Croston SBA (intermittent series)')
        # Aggregate before forecasting, then disaggregate back
        AGG_LOCATION = 'AGG_LOCATION', _('Aggregate to Location level, then disaggregate')
        AGG_ITEM     = 'AGG_ITEM',     _('Aggregate to Item level (across locations)')
        AGG_TOTAL    = 'AGG_TOTAL',    _('Aggregate to client total')
        # No statistical forecast — use historical average or manual
        MOVING_AVG   = 'MOVING_AVG',  _('Simple moving average (lumpy / low volume)')
        MANUAL       = 'MANUAL',      _('Manual — no statistical forecast recommended')

    client            = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_profiles',
    )
    item              = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
        help_text=_('Null = location-level series (no customer breakdown).'),
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    period_type       = models.CharField(
        max_length=16, choices=PERIOD_TYPE_CHOICES,
    )
    # ── Window of analysis ────────────────────────────────────────────────────
    analysis_from  = models.DateField(
        help_text=_('Start of the actuals window used for classification.'),
    )
    analysis_to    = models.DateField(
        help_text=_('End of the actuals window used for classification.'),
    )
    computed_at    = models.DateTimeField(auto_now=True)

    # ── Raw counts ────────────────────────────────────────────────────────────
    total_periods  = models.PositiveSmallIntegerField(
        help_text=_('Total number of periods in the analysis window.'),
    )
    nonzero_periods = models.PositiveSmallIntegerField(
        help_text=_('Number of periods with qty > 0.'),
    )
    total_qty      = models.DecimalField(
        max_digits=16, decimal_places=3,
        help_text=_('Sum of all qty over the analysis window.'),
    )

    # ── Syntetos-Boylan metrics ───────────────────────────────────────────────
    adi = models.DecimalField(
        _('ADI'),
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Average Demand Interval. '
            'total_periods / nonzero_periods. '
            'Null if nonzero_periods = 0.'
        ),
    )
    cv2 = models.DecimalField(
        _('CV²'),
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Squared Coefficient of Variation of non-zero demand quantities. '
            '(std / mean)² of non-zero qty. '
            'Null if fewer than 2 non-zero periods.'
        ),
    )
    zero_rate = models.DecimalField(
        _('zero rate'),
        max_digits=5, decimal_places=4,
        help_text=_('Fraction of periods with zero demand. 0.0–1.0.'),
    )

    # ── Classification result ─────────────────────────────────────────────────
    demand_class = models.CharField(
        _('demand class'),
        max_length=16,
        choices=DemandClass.choices,
    )
    recommended_strategy = models.CharField(
        _('recommended strategy'),
        max_length=16,
        choices=ForecastStrategy.choices,
    )

    # ── Planner override of the recommendation ────────────────────────────────
    # Planners can disagree with the auto-classification and pin a strategy
    override_strategy = models.CharField(
        _('override strategy'),
        max_length=16,
        choices=ForecastStrategy.choices,
        blank=True,
        help_text=_(
            'If set, the forecast engine uses this strategy instead of '
            'recommended_strategy. Set by a planner or superadmin.'
        ),
    )
    override_note = models.TextField(blank=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [
            ('client', 'item', 'planning_customer',
             'planning_location', 'period_type'),
        ]
        ordering = ['item__item_id', 'planning_location__code']
        verbose_name        = _('03-07 Series Profile')
        verbose_name_plural = _('03-07 Series Profiles')
        indexes = [
            models.Index(
                fields=['client', 'demand_class'],
                name='ix_seriesprofile_client_class',
            ),
            models.Index(
                fields=['client', 'recommended_strategy'],
                name='ix_seriesprofile_client_strategy',
            ),
        ]

    def __str__(self):
        cust = self.planning_customer or 'all'
        return (
            f'{self.item.item_id} | {self.planning_location.code} | '
            f'{cust} | {self.demand_class}'
        )

    @property
    def effective_strategy(self) -> str:
        """The strategy the forecast engine should actually use."""
        return self.override_strategy or self.recommended_strategy

    @classmethod
    def classify(
        cls,
        qty_series: list,          # list of Decimal, one per period, zeros included
        adi_threshold: float = 1.32,
        cv2_threshold: float = 0.49,
        min_nonzero: int = 6,      # minimum non-zero periods for any statistical model
    ) -> dict:
        """
        Compute metrics and classify a demand series.

        Args:
            qty_series:     list of qty values (including zeros), ordered by period
            adi_threshold:  Syntetos-Boylan ADI cutoff (default 1.32)
            cv2_threshold:  Syntetos-Boylan CV² cutoff (default 0.49)
            min_nonzero:    minimum non-zero observations required for
                            statistical modelling (default 6)

        Returns dict with keys:
            total_periods, nonzero_periods, total_qty,
            adi, cv2, zero_rate,
            demand_class, recommended_strategy
        """
        import statistics
        from decimal import Decimal

        total_periods   = len(qty_series)
        nonzero_vals    = [q for q in qty_series if q > 0]
        nonzero_periods = len(nonzero_vals)
        total_qty       = sum(qty_series)
        zero_rate       = Decimal(
            1 - nonzero_periods / total_periods
        ) if total_periods > 0 else Decimal('1')

        # ── Edge cases ────────────────────────────────────────────────────────
        if nonzero_periods == 0:
            return {
                'total_periods':   total_periods,
                'nonzero_periods': 0,
                'total_qty':       Decimal('0'),
                'adi':             None,
                'cv2':             None,
                'zero_rate':       Decimal('1'),
                'demand_class':    cls.DemandClass.ZERO,
                'recommended_strategy': cls.ForecastStrategy.MANUAL,
            }

        if nonzero_periods < min_nonzero:
            adi = Decimal(str(round(total_periods / nonzero_periods, 4)))
            return {
                'total_periods':   total_periods,
                'nonzero_periods': nonzero_periods,
                'total_qty':       total_qty,
                'adi':             adi,
                'cv2':             None,
                'zero_rate':       zero_rate,
                'demand_class':    cls.DemandClass.INSUFFICIENT,
                'recommended_strategy': cls.ForecastStrategy.MOVING_AVG,
            }

        # ── Compute ADI and CV² ───────────────────────────────────────────────
        adi  = Decimal(str(round(total_periods / nonzero_periods, 4)))
        mean = statistics.mean(float(v) for v in nonzero_vals)
        std  = statistics.stdev(float(v) for v in nonzero_vals) if len(nonzero_vals) > 1 else 0.0
        cv2  = Decimal(str(round((std / mean) ** 2, 4))) if mean > 0 else Decimal('0')

        adi_f = float(adi)
        cv2_f = float(cv2)

        # ── Syntetos-Boylan classification ────────────────────────────────────
        if adi_f < adi_threshold and cv2_f < cv2_threshold:
            demand_class = cls.DemandClass.SMOOTH
            strategy     = cls.ForecastStrategy.AUTOETS

        elif adi_f < adi_threshold and cv2_f >= cv2_threshold:
            demand_class = cls.DemandClass.ERRATIC
            strategy     = cls.ForecastStrategy.AUTOARIMA

        elif adi_f >= adi_threshold and cv2_f < cv2_threshold:
            demand_class = cls.DemandClass.INTERMITTENT
            strategy     = cls.ForecastStrategy.CROSTON

        else:  # adi_f >= adi_threshold and cv2_f >= cv2_threshold
            demand_class = cls.DemandClass.LUMPY
            # Lumpy: try aggregating to location level first
            strategy     = cls.ForecastStrategy.AGG_LOCATION

        return {
            'total_periods':        total_periods,
            'nonzero_periods':      nonzero_periods,
            'total_qty':            total_qty,
            'adi':                  adi,
            'cv2':                  cv2,
            'zero_rate':            zero_rate,
            'demand_class':         demand_class,
            'recommended_strategy': strategy,
        }

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
        CREATE INDEX IF NOT EXISTS ix_fcstagg_version_level
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

    SeriesProfile
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

- [x] `mysite/models/demand/forecast.py` created with all six models
- [x] `demand/__init__.py` updated to import all six models
- [x] `python manage.py makemigrations mysite --name forecast_models`
- [x] `RunSQL` index block added to generated migration
- [x] `python manage.py migrate` — clean
- [x] `python manage.py check` — 0 issues
- [x] Admin file created and registered; `ForecastVersionAdmin` shows status badge
- [x] Serializers added to `mysite/api/demand/serializers.py`
- [x] Five views added to `mysite/api/demand/views.py`
- [x] Five URL patterns added to `mysite/api/demand/urls.py`
- [ ] `GET /api/demand/forecast-versions/` returns empty list for new client
- [ ] `POST /api/demand/forecast-versions/` creates DRAFT version
- [ ] `POST /api/demand/forecast-versions/{id}/approve/` with `action=submit` moves to IN_REVIEW
- [ ] `POST /api/demand/forecast-versions/{id}/approve/` with `action=copy` on LOCKED returns new DRAFT
- [ ] `GET /api/demand/forecast-versions/{id}/lines/` returns paginated results
- [ ] All unit tests pass: `pytest mysite/tests/demand/test_forecast.py -v`

## 11. Additional point - forecast level selection or intermittency classification.
The Core Problem
When you try to forecast a C-class item with sporadic demand at SKU × Customer × Location level, you get a time series that looks like this:
Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
 0    0    12   0    0    0    8    0    0    0    0    15

 Statistical models like AutoETS and AutoARIMA are designed for smooth, regular series. They will produce poor forecasts on this — often worse than a simple average. The right response is either to use a specialist intermittency model (Croston, TSB) or to aggregate the series up to a level where demand becomes smoother.

Established Measures for This Decision
There are three standard metrics used in the literature (Syntetos, Boylan, Croston):
### 1. ADI — Average Demand Interval
Average number of periods between non-zero demand observations.
ADI = total periods / number of non-zero periods

ADI = 1.0  → demand every period (smooth)
ADI = 4.0  → demand every 4 periods on average (intermittent)

### 2. CV² — Squared Coefficient of Variation of Non-Zero Demand
Measures how lumpy the non-zero demand quantities are.

CV² = (std of non-zero qty / mean of non-zero qty)²

CV² = 0.0  → non-zero quantities are always the same (regular)
CV² = 1.5  → non-zero quantities vary wildly (lumpy)

### 3. The Syntetos-Boylan Classification Matrix
These two measures together classify every series into four quadrants:
CV² < 0.49          CV² ≥ 0.49
                ┌───────────────────┬───────────────────┐
  ADI < 1.32   │    SMOOTH         │    ERRATIC        │
               │  → AutoETS        │  → AutoETS/ARIMA  │
               │  → AutoARIMA      │  (volatile but     │
               │  (regular demand) │   frequent)        │
               ├───────────────────┼───────────────────┤
  ADI ≥ 1.32   │    INTERMITTENT   │    LUMPY          │
               │  → Croston / TSB  │  → CrostonSBA     │
               │  (sparse but      │  → Aggregate up   │
               │   stable qty)     │  (worst case)     │
               └───────────────────┴───────────────────┘

The thresholds ADI=1.32 and CV²=0.49 come from Syntetos & Boylan (2005) and are widely used in industry. They are not sacred — some practitioners use ADI=1.5 or CV²=0.5.

### 4. Additional Measures Worth Computing
Metric              Formula                 Threshold               Meaning
Zero rate           zero periods / 
                    total periods            > 0.7               More than 70% zeros — strongly consider aggregating

Min observations    count of non-zero periods< 12                Too few data points for any model to learn from

Total volume        sum of all qty          < client-defined     C-class by volume — candidate for aggregation

How to Handle This in the Model
There are three things to add:

A SeriesProfile model that stores computed metrics per series
A classification result that maps to a recommended forecast strategy
A forecast_level field on ForecastLine / ForecastVersion that records what level was actually used


Addition                        Where               Purpose     
SeriesProfile model             forecast.py         Stores ADI, CV², zero_rate, demand_class, 
                                                    recommended_strategy per series

SeriesProfile.classify()        classmethod         Pure function — computes metrics from a qty list, 
                                                    returns classification dict
ForecastLine.forecast_level     forecast.py         Records what aggregation level was used when forecasting this line
ForecastLine.model_used         forecast.py         Records which StatsForecast model produced statistical_qty  

compute_series_profiles         Celery task         Runs before forecast task; classifies all series and
                                                    writes SeriesProfile

The key design principle is that classification is separated from forecasting. SeriesProfile is computed once per planning cycle and can be reviewed by planners (via admin or a future UI screen) before the forecast runs. A planner who disagrees with the auto-classification can set override_strategy on a specific series. The forecast task always reads effective_strategy (which honours the planner override), never recommended_strategy directly.

# Sprint 3B.3 — SeriesProfile Section (Final Revised)
## Dynamic Hierarchy, Flexible ABC Classes, Configurable Time Horizons

**Replaces:** `sprint_3b3_seriesprofile_revised.md` in full  
**Scope:** Models, Celery task, Admin, Serializer, API  

---

## 0. Business Flow Summary (Plain Language)

### The Planning Matrix

Every item gets **two independent scores at every level evaluated**:

**ABC — How important is this item?**
Based on its share of total demand *value* among all items at the level
being evaluated. The number of classes and their thresholds are
configurable per client via `AbcClassDefinition`. Client A might use
A/B/C (3 classes), Client B might use A/B/C/D (4 classes).
An item can be **C** client-wide but **A** at a specific location.

**Syntetos-Boylan Class — How forecastable is this item at this level?**
Based on ADI (how often demand occurs) and CV² (how variable non-zero
quantities are). Thresholds are configurable per client via
`ForecastingConfig`. Results: SMOOTH / ERRATIC / INTERMITTENT / LUMPY.

### The Classification Search — Dynamic, Not Hardcoded

The search path is derived at runtime from the client's actual data:

- **Location hierarchy depth** — read from `PlanningLocation` tree
  (how many levels exist for this client)
- **Product hierarchy levels** — read from the client's `TaxonomyNode`
  tree for the `product_planning` taxonomy
- **Time horizon steps** — configured in `ForecastingConfig.time_horizon_steps`
  (how many levels up to try). The actual periods are derived automatically
  from the base `period_type`:
  - Monthly base → [quarter, half-year, year]
  - Daily base   → [week, fortnight, month]
  - Weekly base  → [month, quarter]
  - etc.

### The Search Flow

```
For every item:

Step 0: Item × Client Total
  → SMOOTH / ERRATIC / INTERMITTENT?
       → These are PART A items. Continue drilling DOWN location hierarchy.
  → LUMPY / INSUFFICIENT / ZERO?
       → These are PART B items. Skip PART A. Go directly to PART B.

─────────────────────────────────────────────────────────────────────
PART A — Item is forecastable at Client level.
Drill DOWN through location hierarchy levels (derived from PlanningLocation tree).
Goal: find the FINEST level at which the item stays forecastable.
─────────────────────────────────────────────────────────────────────

Step A1: Item × Level-1 of location tree (e.g. Region)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step A2
  → LUMPY?
       → STOP. USE Step 0 level (Item × Client Total) for this location group.
              Mark: chosen_grain = item_client

Step A2: Item × Level-2 of location tree (e.g. Zone)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step A3
  → LUMPY?
       → STOP. USE Step A1 level (Item × Region).
              Mark: chosen_grain = item_location_level_1

... repeat for each level in the location tree ...

Step An: Item × Leaf Location (finest location grain, all customers)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step An+1 (customer level)
  → LUMPY?
       → STOP. USE previous level (Item × Level n-1).

Step An+1: Item × Leaf Location × Planning Customer (atomic grain)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → USE THIS LEVEL. Mark: chosen_grain = item_cust_location
  → LUMPY?
       → USE previous level (Item × Leaf Location).
              Mark: chosen_grain = item_location_leaf

─────────────────────────────────────────────────────────────────────
PART B — Item is LUMPY at Client level.
Roll UP through product hierarchy (from ForecastingConfig taxonomy levels).
─────────────────────────────────────────────────────────────────────

Step B1: Level-1 product group × Client
         (first level above Item in product_planning taxonomy)
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Step B2

Step B2: Level-2 product group × Client
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Step B3

... repeat for each level in product taxonomy ...

Step Bn: Highest product group × Client (root of taxonomy)
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Go to PART C

─────────────────────────────────────────────────────────────────────
PART C — LUMPY at all product levels.
Try TIME AGGREGATION in combination with product levels.
Time horizons are derived from period_type + time_horizon_steps config.
─────────────────────────────────────────────────────────────────────

  For each time horizon H (from finest to coarsest):
    Step C-H-0: Item × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → next product level

    Step C-H-1: Product Level 1 × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → next product level

    ... repeat through product levels for this time horizon ...

    Step C-H-n: Highest Product Level × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → try next coarser time horizon

  Step Z: MANUAL — no level found anywhere.
    statistical_qty = 0. ForecastLine written with model_used='None'.
    Planner enters override.

At EVERY step: ABC class, ADI, CV², demand_class are stored in
SeriesLevelEvaluation so planners can see the full audit trail.
```

### Disaggregation Conflict Resolution

When an item has its own forecast at a fine grain (Part A) AND its product
group also has a forecast (Part B, because some sibling items were LUMPY):

- **Both forecasts are always stored** in `SeriesLevelEvaluation`
- `ForecastVersion.engine_config["disagg_conflict_resolution"]` controls
  which one becomes `ForecastLine.final_qty`:
  - `"retain_lower"` (default) — finer-grain wins, product-group
    disaggregation does not overwrite it
  - `"use_upper"` — product-group disaggregation overwrites everything
- `ForecastVersion.engine_config["store_all_level_forecasts"]` (default `true`)
  — when true, a `ForecastLine` is written for every evaluated level,
  tagged with `forecast_level`. Enables post-run comparison without re-running.

---

## 1. Helper: Time Horizon Derivation 

Add to `mysite/models/demand/actuals.py` alongside `PERIOD_FREQ_MAP`:

```python
# Time horizons above each base period type.
# Ordered from immediate-next to coarsest.
PERIOD_HIGHER_HORIZONS: dict[str, list[str]] = {
    'second':   ['minute', 'hour', 'day'],
    'minute':   ['hour', 'day', 'week'],
    'hour':     ['day', 'week', 'month'],
    'day':      ['week', 'fortnight', 'month'],
    'week':     ['month', 'quarter'],
    'month':    ['quarter', 'halfyear', 'year'],
    'bimonth':  ['quarter', 'halfyear', 'year'],
    'quarter':  ['halfyear', 'year'],
    'halfyear': ['year'],
    'year':     [],
}

# Add 'fortnight' to PERIOD_FREQ_MAP
PERIOD_FREQ_MAP['fortnight'] = '2W-MON'

# Add 'fortnight' to PERIOD_TYPE_CHOICES
# (append to existing list)
# ('fortnight', _('Fortnight (2 weeks)')),
```

Add a pure helper function — no DB access:

```python
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
```

---

## 2. Helper: Location Hierarchy Introspection

Add to `utils/demand/hierarchy_utils.py` (new file):

```python
# utils/demand/hierarchy_utils.py
"""
Runtime introspection of PlanningLocation and TaxonomyNode trees.
Pure DB queries — no business logic.
"""
from __future__ import annotations
from collections import defaultdict


def get_location_levels(client_id: int) -> list[dict]:
    """
    Return the location hierarchy levels for a client, ordered from
    root (level 0 = client total) to leaves.

    Returns list of dicts:
        [
            {'depth': 0, 'level_label': 'Client Total',
             'location_ids': None},         # virtual — all locations
            {'depth': 1, 'level_label': 'Region',
             'location_ids': [1, 2, 3]},
            {'depth': 2, 'level_label': 'Zone',
             'location_ids': [4, 5, 6, 7]},
            {'depth': 3, 'level_label': 'Branch',
             'location_ids': [8, 9, ...], 'is_leaf': True},
        ]

    Depth 0 is the virtual "Client Total" (no model row — just the aggregate).
    Actual PlanningLocation nodes start at depth 1.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    locations = list(
        PlanningLocation.objects
        .filter(client_id=client_id, is_active=True)
        .values('id', 'code', 'name', 'level_label', 'parent_id', 'is_leaf', 'path')
        .order_by('path')
    )

    if not locations:
        return [{'depth': 0, 'level_label': 'Client Total',
                 'location_ids': None, 'is_leaf': False}]

    # Compute depth from path (path = "1/4/12/" → depth = 2)
    def _depth(loc: dict) -> int:
        return loc['path'].count('/') - 1

    by_depth: dict[int, list] = defaultdict(list)
    for loc in locations:
        d = _depth(loc)
        by_depth[d].append(loc)

    max_depth = max(by_depth.keys())

    # Level 0 is always the virtual Client Total
    levels = [{'depth': 0, 'level_label': 'Client Total',
                'location_ids': None, 'is_leaf': False}]

    for depth in range(0, max_depth + 1):
        locs = by_depth.get(depth, [])
        if not locs:
            continue
        label = locs[0]['level_label'] or f'Level {depth}'
        levels.append({
            'depth': depth + 1,   # +1 because 0 is Client Total
            'level_label': label,
            'location_ids': [l['id'] for l in locs],
            'location_codes': [l['code'] for l in locs],
            'is_leaf': all(l['is_leaf'] for l in locs),
        })

    return levels


def get_location_children_map(client_id: int) -> dict[int | None, list[int]]:
    """
    Returns dict: {parent_id → [child_ids]}.
    parent_id=None means root nodes (direct children of client total).
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result: dict[int | None, list[int]] = defaultdict(list)
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'parent_id'):
        result[loc['parent_id']].append(loc['id'])
    return dict(result)


def get_location_ancestor_map(client_id: int) -> dict[int, list[int]]:
    """
    Returns dict: {location_id → [ancestor_ids from root to parent]}.
    Used to find the region/zone a leaf belongs to.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result = {}
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'path'):
        parts = [p for p in loc['path'].split('/') if p]
        ancestor_ids = [int(p) for p in parts[:-1]]
        result[loc['id']] = ancestor_ids
    return result


def get_product_hierarchy_levels(client_id: int) -> list[dict]:
    """
    Return the product taxonomy levels for the 'product_planning' taxonomy,
    ordered from leaf (SKU) to root (highest category).

    Returns list of dicts ordered from FINEST to COARSEST:
        [
            {'depth': 3, 'level_label': 'SKU',       'node_ids': [...]},
            {'depth': 2, 'level_label': 'Brand',      'node_ids': [...]},
            {'depth': 1, 'level_label': 'Sub-cat',    'node_ids': [...]},
            {'depth': 0, 'level_label': 'Category',   'node_ids': [...]},
        ]

    The leaf level (SKUs) is excluded from Part B evaluation — Part B starts
    one level above the leaf.
    """
    from mysite.models import TaxonomyNode, Taxonomy

    try:
        taxonomy = Taxonomy.objects.get(
            client_id=client_id, slug='product_planning'
        )
    except Taxonomy.DoesNotExist:
        return []

    nodes = list(
        TaxonomyNode.objects
        .filter(taxonomy=taxonomy)
        .values('id', 'name', 'parent_id', 'depth')
        .order_by('depth')
    )

    if not nodes:
        return []

    max_depth = max(n['depth'] for n in nodes)
    by_depth: dict[int, list] = defaultdict(list)
    for n in nodes:
        by_depth[n['depth']].append(n)

    # Return from leaf-1 up to root (skip leaf level — those are the items)
    levels = []
    for depth in range(max_depth - 1, -1, -1):
        group = by_depth.get(depth, [])
        if not group:
            continue
        label = group[0].get('level_label') or f'Level {depth}'
        levels.append({
            'depth':      depth,
            'level_label': label,
            'node_ids':   [n['id'] for n in group],
            'node_names': [n['name'] for n in group],
        })

    return levels
```

---

## 3. Model: `AbcClassDefinition` (flexible ABC subtable)

Replaces the two hardcoded threshold fields on `ForecastingConfig`.
Add to `mysite/models/demand/forecast.py` **before** `ForecastingConfig`:

```python
class AbcClassDefinition(models.Model):
    """
    One row per ABC class tier for a client.

    Supports any number of classes: A/B/C (3 tiers), A/B/C/D (4 tiers), etc.
    Each row defines one class tier with a cumulative value share upper bound.

    Example for 3-tier client (standard):
        rank=1  label='A'  cumulative_upper_pct=70.0   → top 70% of value
        rank=2  label='B'  cumulative_upper_pct=90.0   → next 20%
        rank=3  label='C'  cumulative_upper_pct=100.0  → bottom 10%

    Example for 4-tier client:
        rank=1  label='A'  cumulative_upper_pct=60.0
        rank=2  label='B'  cumulative_upper_pct=80.0
        rank=3  label='C'  cumulative_upper_pct=95.0
        rank=4  label='D'  cumulative_upper_pct=100.0

    Rules enforced in clean():
      - Ranks must be contiguous starting at 1.
      - cumulative_upper_pct must be strictly increasing.
      - The highest rank must have cumulative_upper_pct = 100.0.
    """

    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='abc_class_definitions',
        verbose_name=_('client'),
    )
    rank = models.PositiveSmallIntegerField(
        _('rank'),
        help_text=_(
            'Display and evaluation order. 1 = most important class (e.g. A).'
        ),
    )
    label = models.CharField(
        _('label'),
        max_length=8,
        help_text=_('Class label shown to planners. e.g. "A", "B", "Gold", "Tier1".'),
    )
    cumulative_upper_pct = models.DecimalField(
        _('cumulative upper % (inclusive)'),
        max_digits=6,
        decimal_places=3,
        help_text=_(
            'Items whose cumulative demand value share (at the level being '
            'evaluated) falls at or below this % receive this class. '
            'Must be 100.0 for the last rank. Must be strictly increasing.'
        ),
    )
    description = models.CharField(
        _('description'),
        max_length=255,
        blank=True,
        help_text=_('Optional description shown in reports.'),
    )

    class Meta:
        app_label   = 'mysite'
        unique_together = [('client', 'rank'), ('client', 'label')]
        ordering    = ['client', 'rank']
        verbose_name        = _('03-00A ABC Class Definition')
        verbose_name_plural = _('03-00A ABC Class Definitions')

    def __str__(self):
        return f'{self.client} | rank={self.rank} label={self.label} ≤{self.cumulative_upper_pct}%'

    def clean(self):
        if self.cumulative_upper_pct is not None:
            if self.cumulative_upper_pct <= 0 or self.cumulative_upper_pct > 100:
                raise ValidationError(
                    _('cumulative_upper_pct must be between 0.001 and 100.')
                )

    @classmethod
    def get_or_create_defaults(cls, client) -> list['AbcClassDefinition']:
        """
        Return existing definitions or create standard A/B/C defaults.
        Safe to call from Celery tasks.
        """
        existing = list(
            cls.objects.filter(client=client).order_by('rank')
        )
        if existing:
            return existing

        defaults = [
            cls(client=client, rank=1, label='A',
                cumulative_upper_pct=Decimal('70.000'),
                description='High value — top 70% of demand value'),
            cls(client=client, rank=2, label='B',
                cumulative_upper_pct=Decimal('90.000'),
                description='Medium value — next 20%'),
            cls(client=client, rank=3, label='C',
                cumulative_upper_pct=Decimal('100.000'),
                description='Low value — remaining 10%'),
        ]
        cls.objects.bulk_create(defaults)
        return defaults

    @classmethod
    def compute_class(
        cls,
        item_value: float,
        all_values_sorted_desc: list[float],
        definitions: list['AbcClassDefinition'],
    ) -> dict:
        """
        Classify one item given sorted values for all items at the same level
        and the client's class definitions.

        Returns:
            {'abc_class': str, 'value_share_pct': Decimal, 'rank': int}

        This is a pure function — no DB access after definitions are loaded.
        """
        total = sum(all_values_sorted_desc) or 1.0
        share_pct = item_value / total * 100

        # Compute cumulative % up to and including this item's value
        cumulative = 0.0
        for v in all_values_sorted_desc:
            cumulative += v / total * 100
            if v <= item_value + 1e-9:
                break

        # Find which class this cumulative % falls into
        for defn in definitions:
            if cumulative <= float(defn.cumulative_upper_pct):
                return {
                    'abc_class':       defn.label,
                    'rank':            defn.rank,
                    'value_share_pct': Decimal(str(round(share_pct, 4))),
                    'cumulative_pct':  Decimal(str(round(cumulative, 4))),
                }

        # Fallback to lowest rank (should not happen if 100% is defined)
        last = definitions[-1]
        return {
            'abc_class':       last.label,
            'rank':            last.rank,
            'value_share_pct': Decimal(str(round(share_pct, 4))),
            'cumulative_pct':  Decimal('100'),
        }
```

---

## 4. Model: `ForecastingConfig` (revised — no hardcoded hierarchy)

```python
class ForecastingConfig(models.Model):
    """
    Client-level configuration for the forecasting classification engine.

    One row per client. Created with defaults on first forecast run.

    What is NOT here (derived at runtime instead):
      - Location hierarchy depth → read from PlanningLocation tree
      - Product hierarchy levels → read from product_planning TaxonomyNode tree
      - ABC thresholds           → stored in AbcClassDefinition subtable
    """

    client = models.OneToOneField(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='forecasting_config',
        verbose_name=_('client'),
    )

    # ── Syntetos-Boylan thresholds ────────────────────────────────────────────
    adi_threshold = models.DecimalField(
        _('ADI threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('1.3200'),
        help_text=_(
            'Average Demand Interval cutoff. Series with ADI ≥ this value '
            'are INTERMITTENT or LUMPY. Syntetos-Boylan (2005) default: 1.32.'
        ),
    )
    cv2_threshold = models.DecimalField(
        _('CV² threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('0.4900'),
        help_text=_(
            'Squared Coefficient of Variation cutoff for non-zero demand. '
            'Series with CV² ≥ this value are ERRATIC or LUMPY. '
            'Syntetos-Boylan (2005) default: 0.49.'
        ),
    )
    min_nonzero_periods = models.PositiveSmallIntegerField(
        _('minimum non-zero periods'),
        default=6,
        help_text=_(
            'Minimum non-zero demand periods required before any statistical '
            'model is attempted. Series below this are INSUFFICIENT.'
        ),
    )

    # ── Time horizon aggregation ──────────────────────────────────────────────
    time_horizon_steps = models.PositiveSmallIntegerField(
        _('time horizon steps'),
        default=2,
        help_text=_(
            'How many coarser time periods to try in Part C when an item is '
            'LUMPY at all location and product levels.\n'
            'The actual period types are derived automatically from the '
            'ForecastVersion.period_type:\n'
            '  period_type=month, steps=2 → tries [quarter, halfyear]\n'
            '  period_type=day,   steps=3 → tries [week, fortnight, month]\n'
            '  period_type=week,  steps=1 → tries [month]\n'
            '0 = do not try time aggregation at all.'
        ),
    )

    # ── Include customer dimension ─────────────────────────────────────────────
    evaluate_customer_grain = models.BooleanField(
        _('evaluate customer grain'),
        default=True,
        help_text=_(
            'If True, Part A evaluation drills down to '
            'Item × Leaf Location × Planning Customer '
            'as the finest possible grain. '
            'If False, the finest grain is Item × Leaf Location.'
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label           = 'mysite'
        verbose_name        = _('03-00 Forecasting Config')
        verbose_name_plural = _('03-00 Forecasting Configs')

    def __str__(self):
        return (
            f'{self.client} | ADI≥{self.adi_threshold} '
            f'CV²≥{self.cv2_threshold} | time_steps={self.time_horizon_steps}'
        )

    @classmethod
    def get_for_client(cls, client) -> 'ForecastingConfig':
        config, _ = cls.objects.get_or_create(client=client)
        return config
```

---

## 5. Model: `SeriesLevelEvaluation` (revised — dynamic grain)

The `grain` field now uses a flexible string rather than a fixed enum
so it can represent any depth in any hierarchy without code changes.

```python
class SeriesLevelEvaluation(models.Model):
    """
    One row per (item, evaluated level). The full audit trail.

    grain encodes WHAT was aggregated and HOW:
        'item_client'               — item across all locations
        'item_loc_depth_{n}'        — item at location hierarchy depth n
                                      (n=1 is root children, n=max is leaves)
        'item_cust_location'        — item × customer × leaf location (atomic)
        'taxon_{node_id}_client'    — TaxonomyNode {node_id} × client
        'item_client_{period}'      — item × client at a coarser period type
        'taxon_{node_id}_{period}'  — TaxonomyNode × client at coarser period

    evaluation_key is a JSONField with the specific node values:
        item_client:
            {'grain': 'item_client'}
        item_loc_depth_1:
            {'grain': 'item_loc_depth_1', 'location_id': 4,
             'location_code': 'NORTH', 'level_label': 'Region'}
        item_cust_location:
            {'grain': 'item_cust_location', 'location_id': 12,
             'location_code': 'DEL-01', 'customer_id': 7,
             'customer_code': 'CUST-001'}
        taxon_5_client:
            {'grain': 'taxon_5_client', 'node_id': 5,
             'node_name': 'Brake Pads', 'level_label': 'Sub-category'}
        item_client_quarter:
            {'grain': 'item_client_quarter', 'period_type': 'quarter'}
        taxon_3_quarter:
            {'grain': 'taxon_3_quarter', 'node_id': 3,
             'node_name': 'Braking Systems', 'period_type': 'quarter'}
    """

    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_level_evaluations',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_level_evaluations',
    )
    # planning_customer only set for item_cust_location grain
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_level_evaluations',
    )
    period_type = models.CharField(
        _('base period type'),
        max_length=16, choices=PERIOD_TYPE_CHOICES,
        help_text=_('The ForecastVersion base period type, not the evaluation period.'),
    )

    # ── Which level ───────────────────────────────────────────────────────────
    grain = models.CharField(
        _('evaluation grain'),
        max_length=64,
        db_index=True,
        help_text=_(
            'String encoding the aggregation dimension. '
            'e.g. "item_client", "item_loc_depth_2", '
            '"taxon_5_client", "item_client_quarter".'
        ),
    )
    evaluation_key = models.JSONField(
        _('evaluation key'),
        help_text=_('Identifies the specific node at this grain.'),
    )
    # The evaluation period type (may differ from period_type in Part C)
    eval_period_type = models.CharField(
        _('evaluation period type'),
        max_length=16, choices=PERIOD_TYPE_CHOICES,
        help_text=_(
            'The period type used for THIS evaluation. '
            'Equals period_type for Parts A and B. '
            'Coarser (e.g. quarter) for Part C.'
        ),
    )

    # ── Analysis window ───────────────────────────────────────────────────────
    analysis_from = models.DateField()
    analysis_to   = models.DateField()

    # ── Raw metrics ───────────────────────────────────────────────────────────
    total_periods   = models.PositiveSmallIntegerField()
    nonzero_periods = models.PositiveSmallIntegerField()
    total_qty       = models.DecimalField(max_digits=18, decimal_places=3)
    total_value     = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )

    # ── Syntetos-Boylan ───────────────────────────────────────────────────────
    adi       = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    cv2       = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    zero_rate = models.DecimalField(max_digits=5, decimal_places=4)

    # ── ABC at this level ─────────────────────────────────────────────────────
    abc_class = models.CharField(
        _('ABC class at this level'),
        max_length=8,          # supports longer labels like 'Gold', 'Tier1'
        blank=True,
    )
    value_share_pct_at_level = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True,
    )
    value_rank_at_level = models.PositiveIntegerField(null=True, blank=True)

    # ── Syntetos-Boylan classification ────────────────────────────────────────
    demand_class = models.CharField(
        _('demand class'),
        max_length=16,
        choices=[
            ('SMOOTH',       _('Smooth')),
            ('ERRATIC',      _('Erratic')),
            ('INTERMITTENT', _('Intermittent')),
            ('LUMPY',        _('Lumpy')),
            ('INSUFFICIENT', _('Insufficient data')),
            ('ZERO',         _('Zero demand')),
        ],
    )

    # ── Decision ──────────────────────────────────────────────────────────────
    is_accepted = models.BooleanField(
        _('accepted'),
        default=False,
        db_index=True,
    )
    rejection_reason = models.CharField(
        max_length=255, blank=True,
    )
    recommended_strategy = models.CharField(
        max_length=16, blank=True,
        choices=[
            ('AUTOETS',    'AutoETS'),
            ('AUTOARIMA',  'AutoARIMA'),
            ('CROSTON',    'Croston SBA'),
            ('MOVING_AVG', 'Moving Average'),
            ('MANUAL',     'Manual'),
        ],
    )

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'mysite'
        ordering  = ['item__item_id', 'grain']
        verbose_name        = _('03-06 Series Level Evaluation')
        verbose_name_plural = _('03-06 Series Level Evaluations')
        indexes = [
            models.Index(
                fields=['client', 'grain', 'demand_class'],
                name='ix_sleveval_grain_cls',
            ),
            models.Index(
                fields=['client', 'is_accepted'],
                name='ix_sleveval_accepted',
            ),
            models.Index(
                fields=['client', 'item', 'is_accepted'],
                name='ix_sleveval_item_accepted',
            ),
        ]

    def __str__(self):
        status = 'ACCEPTED' if self.is_accepted else 'rejected'
        return (
            f'{self.item.item_id} | {self.grain} | '
            f'{self.demand_class} | {status}'
        )
```

---

## 6. Model: `SeriesProfile` (revised — references dynamic grain)

```python
class SeriesProfile(models.Model):
    """
    Forecast level selection summary for one atomic series
    (item, customer, location). One row per unique atomic combination.

    chosen_evaluation FK points to the accepted SeriesLevelEvaluation row.
    chosen_grain is denormalised for fast filter/display without a join.
    """

    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_profiles',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    period_type = models.CharField(max_length=16, choices=PERIOD_TYPE_CHOICES)

    # ── Analysis window ───────────────────────────────────────────────────────
    analysis_from = models.DateField()
    analysis_to   = models.DateField()
    computed_at   = models.DateTimeField(auto_now=True)

    # ── Metrics at atomic grain ───────────────────────────────────────────────
    total_periods    = models.PositiveSmallIntegerField()
    nonzero_periods  = models.PositiveSmallIntegerField()
    total_qty        = models.DecimalField(max_digits=16, decimal_places=3)
    total_value      = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    adi              = models.DecimalField(
        _('ADI at atomic grain'),
        max_digits=8, decimal_places=4, null=True, blank=True,
    )
    cv2              = models.DecimalField(
        _('CV² at atomic grain'),
        max_digits=8, decimal_places=4, null=True, blank=True,
    )
    zero_rate        = models.DecimalField(max_digits=5, decimal_places=4)
    demand_class_atomic = models.CharField(max_length=16, blank=True)
    abc_class_atomic    = models.CharField(max_length=8, blank=True)

    # ── Chosen evaluation ─────────────────────────────────────────────────────
    chosen_evaluation = models.ForeignKey(
        SeriesLevelEvaluation,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
        verbose_name=_('chosen evaluation'),
    )
    # Denormalised fields from chosen_evaluation for fast access
    chosen_grain         = models.CharField(max_length=64, blank=True, db_index=True)
    chosen_demand_class  = models.CharField(max_length=16, blank=True)
    chosen_strategy      = models.CharField(max_length=16, blank=True)
    chosen_eval_period   = models.CharField(
        _('chosen evaluation period type'),
        max_length=16, blank=True,
        help_text=_(
            'The period type used at the chosen level. '
            'May differ from period_type when time aggregation was applied.'
        ),
    )

    # ── Planner overrides ─────────────────────────────────────────────────────
    override_grain = models.CharField(
        _('override grain'),
        max_length=64, blank=True,
        help_text=_(
            'Planner-specified grain string. Must match a valid grain from '
            'SeriesLevelEvaluation for this item. '
            'The forecast engine reads effective_grain.'
        ),
    )
    override_strategy = models.CharField(max_length=16, blank=True)
    override_note     = models.TextField(blank=True)
    override_set_by   = models.ForeignKey(
        'auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    override_set_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [
            ('client', 'item', 'planning_customer',
             'planning_location', 'period_type'),
        ]
        ordering = ['item__item_id', 'planning_location__code']
        verbose_name        = _('03-07 Series Profile')
        verbose_name_plural = _('03-07 Series Profiles')
        indexes = [
            models.Index(fields=['client', 'chosen_grain'],      name='ix_seriespro_grain'),
            models.Index(fields=['client', 'demand_class_atomic'], name='ix_seriespro_cls'),
            models.Index(fields=['client', 'abc_class_atomic'],   name='ix_seriespro_abc'),
        ]

    def __str__(self):
        cust = self.planning_customer or 'all'
        return (
            f'{self.item.item_id} | {self.planning_location.code} | {cust} | '
            f'atomic={self.demand_class_atomic} | chosen={self.chosen_grain}'
        )

    @property
    def effective_grain(self) -> str:
        return self.override_grain or self.chosen_grain or 'item_client'

    @property
    def effective_strategy(self) -> str:
        return self.override_strategy or self.chosen_strategy or 'AUTOETS'

    @property
    def effective_eval_period(self) -> str:
        return self.chosen_eval_period or self.period_type

    @property
    def is_overridden(self) -> bool:
        return bool(self.override_grain or self.override_strategy)

    # ── Classification pure functions ─────────────────────────────────────────

    @classmethod
    def compute_syntetos_boylan(
        cls,
        qty_series: list,
        adi_threshold: float,
        cv2_threshold: float,
        min_nonzero: int,
    ) -> dict:
        """
        Compute ADI, CV², zero_rate and Syntetos-Boylan demand class.
        Pure function — no DB access.
        """
        import statistics

        total_periods   = len(qty_series)
        nonzero_vals    = [q for q in qty_series if q > 0]
        nonzero_periods = len(nonzero_vals)
        total_qty       = sum(qty_series)
        zero_rate       = Decimal(
            str(round(1 - nonzero_periods / total_periods, 4))
        ) if total_periods > 0 else Decimal('1')

        if nonzero_periods == 0:
            return {
                'total_periods': total_periods, 'nonzero_periods': 0,
                'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                'zero_rate': Decimal('1'), 'demand_class': 'ZERO',
                'recommended_strategy': 'MANUAL',
            }

        if nonzero_periods < min_nonzero:
            adi = Decimal(str(round(total_periods / nonzero_periods, 4)))
            return {
                'total_periods': total_periods, 'nonzero_periods': nonzero_periods,
                'total_qty': total_qty, 'adi': adi, 'cv2': None,
                'zero_rate': zero_rate, 'demand_class': 'INSUFFICIENT',
                'recommended_strategy': 'MOVING_AVG',
            }

        adi  = Decimal(str(round(total_periods / nonzero_periods, 4)))
        mean = statistics.mean(float(v) for v in nonzero_vals)
        std  = statistics.stdev(float(v) for v in nonzero_vals) \
               if len(nonzero_vals) > 1 else 0.0
        cv2  = Decimal(str(round((std / mean) ** 2, 4))) if mean > 0 else Decimal('0')

        adi_f, cv2_f = float(adi), float(cv2)

        if   adi_f < adi_threshold and cv2_f < cv2_threshold:
            demand_class = 'SMOOTH';       strategy = 'AUTOETS'
        elif adi_f < adi_threshold:
            demand_class = 'ERRATIC';      strategy = 'AUTOARIMA'
        elif cv2_f < cv2_threshold:
            demand_class = 'INTERMITTENT'; strategy = 'CROSTON'
        else:
            demand_class = 'LUMPY';        strategy = ''

        return {
            'total_periods': total_periods, 'nonzero_periods': nonzero_periods,
            'total_qty': total_qty, 'adi': adi, 'cv2': cv2,
            'zero_rate': zero_rate, 'demand_class': demand_class,
            'recommended_strategy': strategy,
        }
```

---

## 7. Revised Celery Task: `compute_series_profiles`

```python
# mysite/tasks/demand/compute_series_profiles.py

import logging
from collections import defaultdict
from decimal import Decimal

import duckdb
import pandas as pd
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from mysite.models.demand.actuals import ActualSale, get_higher_period_types
from mysite.models.demand.forecast import (
    AbcClassDefinition, ForecastingConfig,
    SeriesLevelEvaluation, SeriesProfile,
)

logger = logging.getLogger(__name__)

LUMPY_CLASSES = {'LUMPY', 'INSUFFICIENT', 'ZERO'}


@shared_task(bind=True)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Full multi-level classification: dynamic location depth,
    dynamic product hierarchy, dynamic time horizons.
    """
    from mysite.models import Client
    from utils.demand.hierarchy_utils import (
        get_location_levels,
        get_product_hierarchy_levels,
    )

    client = Client.objects.get(pk=client_id)
    config = ForecastingConfig.get_for_client(client)
    abc_defs = AbcClassDefinition.get_or_create_defaults(client)

    adi_thr = float(config.adi_threshold)
    cv2_thr = float(config.cv2_threshold)
    min_nz  = config.min_nonzero_periods

    # ── Derive search space from client's actual hierarchies ──────────────────

    # Location levels: [{depth, level_label, location_ids, is_leaf}]
    loc_levels = get_location_levels(client_id)
    # loc_levels[0] is always Client Total (virtual).
    # loc_levels[1..n] are actual PlanningLocation levels from the DB.

    # Product levels: [{depth, level_label, node_ids}] — finest to coarsest
    prod_levels = get_product_hierarchy_levels(client_id)
    # prod_levels[0] is the level just above SKU (e.g. Brand or SubCategory).
    # prod_levels[-1] is the root (Category or similar).

    # Time horizons: list of period_type strings coarser than base
    time_horizons = get_higher_period_types(period_type, config.time_horizon_steps)

    logger.info(
        f'compute_series_profiles: client={client_id} period={period_type}\n'
        f'  location levels: {[l["level_label"] for l in loc_levels]}\n'
        f'  product levels: {[l["level_label"] for l in prod_levels]}\n'
        f'  time horizons: {time_horizons}\n'
        f'  ADI≥{adi_thr} CV²≥{cv2_thr} min_nz={min_nz}'
    )

    # ── Pull actuals ──────────────────────────────────────────────────────────
    qs = (
        ActualSale.objects
        .filter(client=client, period_type=period_type)
        .select_related(
            'item',
            'planning_location',
            'planning_customer',
        )
        .values(
            'item_id', 'item__item_id',
            'planning_customer_id', 'planning_customer__code',
            'planning_location_id', 'planning_location__code',
            'planning_location__path',    # materialized path for ancestor lookup
            'period_start', 'qty', 'revenue',
        )
        .order_by('period_start')
    )

    if not qs.exists():
        logger.info(f'compute_series_profiles: no actuals for client {client_id}')
        return

    df = pd.DataFrame(list(qs))
    df['qty']     = df['qty'].astype(float)
    df['revenue'] = df['revenue'].fillna(0).astype(float)
    df['cust_code'] = df['planning_customer__code'].fillna('__NULL__')

    # Build ancestor lookup from materialized path
    # path = "1/4/12/" → ancestors at depth 1 = node 1, depth 2 = node 4
    def _ancestor_at_depth(path: str, target_depth: int) -> int | None:
        """Return the location_id at target_depth in the path, or None."""
        parts = [p for p in path.split('/') if p]
        # parts[0] is depth-1 node, parts[1] is depth-2, etc.
        idx = target_depth - 1
        return int(parts[idx]) if idx < len(parts) else None

    # Build location_id → location_id-at-depth-n lookup
    # Used to group locations by their ancestor at each level
    loc_id_to_path = df.groupby('planning_location_id')['planning_location__path'].first().to_dict()

    def _loc_ancestor(loc_id: int, depth: int) -> int | None:
        path = loc_id_to_path.get(loc_id, '')
        return _ancestor_at_depth(path, depth)

    # For each location_id, build its ancestor at each location level depth
    all_loc_ids = df['planning_location_id'].unique()
    loc_ancestor: dict[int, dict[int, int | None]] = {}
    for loc_id in all_loc_ids:
        loc_ancestor[loc_id] = {
            level['depth']: _loc_ancestor(loc_id, level['depth'])
            for level in loc_levels[1:]  # skip virtual level 0
        }

    # Add ancestor columns to df
    for level in loc_levels[1:]:
        d = level['depth']
        col = f'anc_depth_{d}'
        df[col] = df['planning_location_id'].map(
            lambda lid, d=d: loc_ancestor.get(int(lid), {}).get(d)
        )

    # ── Build time spine ──────────────────────────────────────────────────────
    all_periods   = sorted(df['period_start'].unique().tolist())
    analysis_from = all_periods[0]
    analysis_to   = all_periods[-1]

    # ── DuckDB aggregations ───────────────────────────────────────────────────
    con = duckdb.connect()
    con.register('actuals', df)

    def _agg_sql(group_cols: list[str], extra_cols: str = '') -> str:
        """Build a GROUP BY aggregation SQL."""
        gc = ', '.join(group_cols)
        return f"""
            SELECT {gc},
                   period_start,
                   SUM(qty) AS qty,
                   SUM(revenue) AS revenue
                   {', ' + extra_cols if extra_cols else ''}
            FROM actuals
            GROUP BY {gc}, period_start
        """

    # Level 0: Item × Client (virtual — all locations)
    df_item_client = con.execute(_agg_sql(['item_id'])).df()

    # Levels 1..n: Item × Location ancestor at each depth
    df_by_depth: dict[int, pd.DataFrame] = {}
    for level in loc_levels[1:]:
        d = level['depth']
        anc_col = f'anc_depth_{d}'
        if anc_col in df.columns:
            df_by_depth[d] = con.execute(
                _agg_sql(['item_id', anc_col])
            ).df().rename(columns={anc_col: 'loc_ancestor_id'})

    # Item × Leaf Location (all customers)
    df_item_loc = con.execute(
        _agg_sql(['item_id', 'planning_location_id',
                  'planning_location__code'])
    ).df()

    # Atomic: Item × Customer × Leaf Location
    df_atomic = con.execute(
        _agg_sql(['item_id', 'cust_code', 'planning_customer_id',
                  'planning_location_id', 'planning_location__code'])
    ).df()

    # Quarterly aggregations for Part C time horizons
    df_time_agg: dict[str, pd.DataFrame] = {}
    for h_period in time_horizons:
        from mysite.models.demand.actuals import PERIOD_FREQ_MAP
        freq = PERIOD_FREQ_MAP.get(h_period)
        if not freq:
            continue
        try:
            tmp = df[['item_id', 'period_start', 'qty', 'revenue']].copy()
            tmp['period_start'] = pd.to_datetime(tmp['period_start'])
            agg = (
                tmp.groupby(['item_id', pd.Grouper(key='period_start', freq=freq)])
                .agg({'qty': 'sum', 'revenue': 'sum'})
                .reset_index()
            )
            agg['period_start'] = agg['period_start'].dt.date
            df_time_agg[h_period] = agg
        except Exception as exc:
            logger.warning(f'Time agg failed for {h_period}: {exc}')

    # ── Helper: build qty series from filtered DataFrame ──────────────────────
    def _qty_series(filtered: pd.DataFrame, periods: list) -> list[float]:
        pq = dict(zip(filtered['period_start'], filtered['qty']))
        return [pq.get(p, 0.0) for p in periods]

    def _value_series(filtered: pd.DataFrame) -> float:
        return float(filtered['revenue'].sum())

    # ── Helper: classify ──────────────────────────────────────────────────────
    def _classify(qty_list: list) -> dict:
        series = [Decimal(str(q)) for q in qty_list]
        return SeriesProfile.compute_syntetos_boylan(
            series, adi_thr, cv2_thr, min_nz
        )

    # ── Helper: ABC at a level ────────────────────────────────────────────────
    def _compute_abc_at_level(
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        """
        Compute ABC for item_value given all items' values in level_df.
        level_df must contain a 'revenue' column grouped by item_id.
        """
        all_values = level_df.groupby('item_id')['revenue'].sum().sort_values(ascending=False).tolist()
        return AbcClassDefinition.compute_class(
            item_value, all_values, abc_defs
        )

    # ── Helper: build SeriesLevelEvaluation dict ──────────────────────────────
    def _eval_dict(
        grain: str,
        key: dict,
        eval_period: str,
        qty_list: list,
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        m   = _classify(qty_list)
        abc = _compute_abc_at_level(item_value, level_df)
        return {
            'grain':           grain,
            'evaluation_key':  key,
            'eval_period':     eval_period,
            'metrics':         m,
            'abc':             abc,
            'total_value':     item_value,
            'is_forecastable': m['demand_class'] not in LUMPY_CLASSES,
        }

    # ── Main per-series loop ──────────────────────────────────────────────────
    evaluations_to_create: list[SeriesLevelEvaluation] = []
    profiles_to_upsert: list[dict] = []

    # Get unique atomic series
    atomic_groups = df_atomic.groupby(
        ['item_id', 'cust_code', 'planning_customer_id',
         'planning_location_id', 'planning_location__code']
    )

    for keys, _ in atomic_groups:
        item_id   = keys[0]
        cust_code = keys[1]
        cust_id   = keys[2]
        loc_id    = keys[3]
        loc_code  = keys[4]
        cust_id_int = None if pd.isna(cust_id) else int(cust_id)

        evals: list[dict] = []
        chosen: dict | None = None

        # ── Step 0: Item × Client ─────────────────────────────────────────────
        ic_rows = df_item_client[df_item_client['item_id'] == item_id]
        ic_qty  = _qty_series(ic_rows, all_periods)
        ic_val  = _value_series(ic_rows)
        e0 = _eval_dict(
            grain='item_client',
            key={'grain': 'item_client'},
            eval_period=period_type,
            qty_list=ic_qty,
            item_value=ic_val,
            level_df=df_item_client,
        )
        evals.append(e0)

        if e0['is_forecastable']:
            # ── PART A: drill DOWN location hierarchy ─────────────────────────
            prev_accepted = e0  # last forecastable level

            for level in loc_levels[1:]:
                d       = level['depth']
                anc_id  = loc_ancestor.get(int(loc_id), {}).get(d)
                if anc_id is None:
                    continue  # this location has no ancestor at this depth

                level_df_d = df_by_depth.get(d)
                if level_df_d is None:
                    continue

                rows_d = level_df_d[
                    (level_df_d['item_id'] == item_id) &
                    (level_df_d['loc_ancestor_id'] == anc_id)
                ]
                if rows_d.empty:
                    continue

                val_d = _value_series(rows_d)
                e_d = _eval_dict(
                    grain=f'item_loc_depth_{d}',
                    key={'grain': f'item_loc_depth_{d}',
                         'location_id': int(anc_id),
                         'level_label': level['level_label']},
                    eval_period=period_type,
                    qty_list=_qty_series(rows_d, all_periods),
                    item_value=val_d,
                    level_df=level_df_d,
                )
                evals.append(e_d)

                if e_d['is_forecastable']:
                    prev_accepted = e_d   # keep drilling
                else:
                    # Hit LUMPY — step back
                    chosen = prev_accepted
                    break

            else:
                # Finished all location levels without going LUMPY
                # Now try customer grain if config says so
                if config.evaluate_customer_grain:
                    leaf_rows = df_item_loc[
                        (df_item_loc['item_id'] == item_id) &
                        (df_item_loc['planning_location_id'] == loc_id)
                    ]
                    at_rows = df_atomic[
                        (df_atomic['item_id'] == item_id) &
                        (df_atomic['planning_location_id'] == loc_id) &
                        (df_atomic['cust_code'] == cust_code)
                    ]
                    if not at_rows.empty:
                        at_val = _value_series(at_rows)
                        e_at = _eval_dict(
                            grain='item_cust_location',
                            key={'grain': 'item_cust_location',
                                 'location_id': int(loc_id),
                                 'location_code': loc_code,
                                 'customer_code': cust_code},
                            eval_period=period_type,
                            qty_list=_qty_series(at_rows, all_periods),
                            item_value=at_val,
                            level_df=df_atomic[
                                df_atomic['planning_location_id'] == loc_id
                            ],
                        )
                        evals.append(e_at)
                        if e_at['is_forecastable']:
                            prev_accepted = e_at

                if chosen is None:
                    chosen = prev_accepted

        else:
            # ── PART B: Item is LUMPY at client level ─────────────────────────
            # Roll UP through product hierarchy

            for prod_level in prod_levels:
                # Build series: sum all items in the same product group
                # at this level that belong to this item
                # (requires ItemTaxonomyMapping join — simplified here)
                node_ids = prod_level.get('node_ids', [])
                if not node_ids:
                    continue

                # Placeholder: extend with actual taxonomy lookup
                # For each node in prod_level that contains item_id:
                # sum actuals of all items in that node
                node_id = None  # resolve item → node at this level
                if node_id is None:
                    continue

                # Build aggregated series for this product group
                # (requires a pre-built item → node_id mapping per level)
                # Omitted here — wire in your ItemTaxonomyMapping query
                pass  # replace with actual implementation

            # ── PART C: time aggregation ──────────────────────────────────────
            for h_period in time_horizons:
                if chosen:
                    break
                h_df = df_time_agg.get(h_period)
                if h_df is None:
                    continue
                h_periods = sorted(h_df['period_start'].unique().tolist())
                if len(h_periods) < min_nz:
                    continue

                # Step C-H-0: Item × Client × Time Horizon
                ic_h_rows = h_df[h_df['item_id'] == item_id]
                if not ic_h_rows.empty:
                    ic_h_qty = _qty_series(ic_h_rows, h_periods)
                    ic_h_val = _value_series(ic_h_rows)
                    e_ch = _eval_dict(
                        grain=f'item_client_{h_period}',
                        key={'grain': f'item_client_{h_period}',
                             'period_type': h_period},
                        eval_period=h_period,
                        qty_list=ic_h_qty,
                        item_value=ic_h_val,
                        level_df=h_df,
                    )
                    evals.append(e_ch)
                    if e_ch['is_forecastable']:
                        chosen = e_ch
                        break

                # Step C-H-n: product hierarchy × time horizon
                # (extend with actual taxonomy loop — same pattern as Part B)

            # Final fallback: MANUAL
            if not chosen:
                e_manual = {
                    'grain':          'item_client',
                    'evaluation_key': {'grain': 'item_client', 'note': 'MANUAL'},
                    'eval_period':    period_type,
                    'metrics': {
                        'demand_class': 'LUMPY', 'recommended_strategy': 'MANUAL',
                        'total_periods': len(all_periods), 'nonzero_periods': 0,
                        'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                        'zero_rate': Decimal('1'),
                    },
                    'abc':         e0['abc'],
                    'total_value': ic_val,
                    'is_forecastable': False,
                }
                evals.append(e_manual)
                chosen = e_manual

        # Mark chosen and build rejection reasons
        for ev in evals:
            ev['is_accepted'] = (ev is chosen)
            if not ev['is_accepted']:
                m = ev['metrics']
                ev['rejection_reason'] = (
                    f"{m['demand_class']} (ADI={m.get('adi','—')}, "
                    f"CV²={m.get('cv2','—')})"
                    if m['demand_class'] in LUMPY_CLASSES else ''
                )
            else:
                ev['rejection_reason'] = ''

        # Build SeriesLevelEvaluation objects
        for ev in evals:
            m = ev['metrics']
            evaluations_to_create.append(
                SeriesLevelEvaluation(
                    client_id=client_id,
                    item_id=item_id,
                    planning_customer_id=(
                        cust_id_int
                        if ev['grain'] == 'item_cust_location'
                        else None
                    ),
                    period_type=period_type,
                    grain=ev['grain'],
                    evaluation_key=ev['evaluation_key'],
                    eval_period_type=ev.get('eval_period', period_type),
                    analysis_from=analysis_from,
                    analysis_to=analysis_to,
                    total_periods=m['total_periods'],
                    nonzero_periods=m['nonzero_periods'],
                    total_qty=m['total_qty'],
                    total_value=Decimal(str(round(ev.get('total_value', 0), 2))),
                    adi=m.get('adi'),
                    cv2=m.get('cv2'),
                    zero_rate=m['zero_rate'],
                    abc_class=ev['abc'].get('abc_class', ''),
                    value_share_pct_at_level=ev['abc'].get('value_share_pct'),
                    demand_class=m['demand_class'],
                    is_accepted=ev.get('is_accepted', False),
                    rejection_reason=ev.get('rejection_reason', ''),
                    recommended_strategy=m.get('recommended_strategy', ''),
                )
            )

        # Build SeriesProfile summary
        chosen_m = chosen['metrics'] if chosen else {}
        atom_rows = df_atomic[
            (df_atomic['item_id'] == item_id) &
            (df_atomic['planning_location_id'] == loc_id) &
            (df_atomic['cust_code'] == cust_code)
        ]
        atom_qty = _qty_series(atom_rows, all_periods)
        atom_m   = _classify(atom_qty)
        atom_val = _value_series(atom_rows)
        atom_abc = _compute_abc_at_level(atom_val, df_atomic)

        profiles_to_upsert.append({
            'client_id':             client_id,
            'item_id':               item_id,
            'planning_customer_id':  cust_id_int,
            'planning_location_id':  int(loc_id),
            'period_type':           period_type,
            'analysis_from':         analysis_from,
            'analysis_to':           analysis_to,
            'total_periods':         atom_m['total_periods'],
            'nonzero_periods':       atom_m['nonzero_periods'],
            'total_qty':             atom_m['total_qty'],
            'total_value':           Decimal(str(round(atom_val, 2))),
            'adi':                   atom_m.get('adi'),
            'cv2':                   atom_m.get('cv2'),
            'zero_rate':             atom_m['zero_rate'],
            'demand_class_atomic':   atom_m['demand_class'],
            'abc_class_atomic':      atom_abc.get('abc_class', ''),
            'chosen_grain':          chosen['grain'] if chosen else '',
            'chosen_demand_class':   chosen_m.get('demand_class', ''),
            'chosen_strategy':       chosen_m.get('recommended_strategy', 'MANUAL'),
            'chosen_eval_period':    chosen.get('eval_period', period_type) if chosen else period_type,
        })

    # ── Persist ────────────────────────────────────────────────────────────────
    with transaction.atomic():
        SeriesLevelEvaluation.objects.filter(
            client_id=client_id, period_type=period_type
        ).delete()

        SeriesLevelEvaluation.objects.bulk_create(
            evaluations_to_create, batch_size=500, ignore_conflicts=True
        )

        # Re-query to get PKs (bulk_create doesn't return PKs on all DB backends)
        eval_pk_map = {
            (e.item_id, e.grain, str(e.evaluation_key)): e.pk
            for e in SeriesLevelEvaluation.objects.filter(
                client_id=client_id, period_type=period_type, is_accepted=True
            )
        }

        for p in profiles_to_upsert:
            update_fields = {k: v for k, v in p.items()
                             if k not in ('client_id', 'item_id',
                                          'planning_customer_id',
                                          'planning_location_id', 'period_type')}
            # Find chosen_evaluation FK
            # (match by item_id + chosen_grain from accepted evaluations)
            chosen_eval_pk = eval_pk_map.get(
                (p['item_id'], p['chosen_grain'],
                 str({'grain': p['chosen_grain']}))
            )
            if chosen_eval_pk:
                update_fields['chosen_evaluation_id'] = chosen_eval_pk

            SeriesProfile.objects.update_or_create(
                client_id=p['client_id'],
                item_id=p['item_id'],
                planning_customer_id=p['planning_customer_id'],
                planning_location_id=p['planning_location_id'],
                period_type=p['period_type'],
                defaults=update_fields,
            )

    from collections import Counter
    grain_counts = Counter(p['chosen_grain'] for p in profiles_to_upsert)
    class_counts = Counter(p['demand_class_atomic'] for p in profiles_to_upsert)
    logger.info(
        f'compute_series_profiles: client={client_id} '
        f'total={len(profiles_to_upsert)} '
        f'chosen_grain={dict(grain_counts)} '
        f'atomic_class={dict(class_counts)}'
    )
```

---

## 8. Migration

```bash
python manage.py makemigrations mysite \
    --name forecasting_config_abc_defs_series_level_eval
python manage.py migrate
python manage.py check
```

**New tables:**
- `mysite_forecastingconfig` — one row per client, ADI/CV²/time thresholds
- `mysite_abcclassdefinition` — subtable, N rows per client defining ABC tiers
- `mysite_seriesleveleval` — one row per (item, grain evaluated), full audit

**Modified table:**
- `mysite_seriesprofile` — new fields: `chosen_evaluation_id`,
  `chosen_grain`, `chosen_demand_class`, `chosen_strategy`,
  `chosen_eval_period`, `demand_class_atomic`, `abc_class_atomic`,
  `total_value`, `override_grain`, `override_set_by_id`, `override_set_at`

**Notes for Sprint 3B.4:**
The task receives `SeriesProfile.effective_grain` and
`SeriesProfile.effective_eval_period`. The grain string is sufficient
to know WHAT to aggregate and at WHAT time bucket. No hardcoded level
names exist in the forecast engine — it reads grain strings produced
here and acts accordingly.

# Sprint 3B.3 SeriesProfile — Admin, Serializers, and `engine_config` Additions

**Applies to:** The final model design in `sprint_3b3_seriesprofile_final.md`  
**Models covered:** `AbcClassDefinition`, `ForecastingConfig`,  
`SeriesLevelEvaluation`, `SeriesProfile`

---

## 1. Admin

### 1.1 File location

All four registrations go in `mysite/admin/demand_forecast.py`,
below the existing `ForecastVersionAdmin` block.

```python
# mysite/admin/demand_forecast.py
# Add these imports at the top alongside existing imports

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.urls import reverse
from django.utils.safestring import mark_safe

from mysite.models.demand.forecast import (
    AbcClassDefinition,
    ForecastingConfig,
    SeriesLevelEvaluation,
    SeriesProfile,
)
```

---

### 1.2 `AbcClassDefinitionInline` + `ForecastingConfigAdmin`

`AbcClassDefinition` rows belong to a client and are best managed as
an inline inside `ForecastingConfigAdmin`. A planner sets up their
A/B/C/D tiers directly on the config page.

```python
class AbcClassDefinitionInline(admin.TabularInline):
    """
    Inline editor for a client's ABC tier definitions.
    Displayed inside ForecastingConfigAdmin.

    The planner sees a table:
        rank | label | cumulative_upper_pct | description
        1    | A     | 70.000               | High value items
        2    | B     | 90.000               | Medium value items
        3    | C     | 100.000              | Low value items

    Rules enforced by the model's clean():
      - Ranks must be unique per client.
      - cumulative_upper_pct must be strictly increasing.
      - Last rank must be exactly 100.000.
    """
    model   = AbcClassDefinition
    extra   = 0
    min_num = 2          # at minimum 2 tiers (e.g. A and B/C)
    max_num = 10         # unlikely to need more than 10 tiers
    fields  = ['rank', 'label', 'cumulative_upper_pct', 'description']
    ordering = ['rank']

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('rank')


@admin.register(ForecastingConfig)
class ForecastingConfigAdmin(admin.ModelAdmin):
    """
    One row per client. Superadmin sets thresholds; planners see read-only view.

    The ABC class tiers are managed via the AbcClassDefinitionInline below.
    """

    list_display = [
        'client',
        'adi_threshold', 'cv2_threshold', 'min_nonzero_periods',
        'time_horizon_steps',
        'evaluate_customer_grain',
        'abc_tier_summary',
        'updated_at',
    ]
    list_filter  = ['client']
    search_fields = ['client__client_id', 'client__name']

    fieldsets = [
        (None, {
            'fields': ['client'],
        }),
        (_('Syntetos-Boylan Classification Thresholds'), {
            'fields': [
                'adi_threshold', 'cv2_threshold', 'min_nonzero_periods',
            ],
            'description': _(
                'ADI ≥ threshold → series is INTERMITTENT or LUMPY. '
                'CV² ≥ threshold → series is ERRATIC or LUMPY. '
                'Published defaults (Syntetos-Boylan 2005): ADI=1.32, CV²=0.49. '
                'Only change these if you have a strong reason to deviate.'
            ),
        }),
        (_('Time Horizon Aggregation (Part C)'), {
            'fields': ['time_horizon_steps'],
            'description': _(
                'Number of coarser time periods to try when an item is LUMPY '
                'at all location and product levels. '
                'The actual periods are derived automatically from the '
                'ForecastVersion period_type:\n'
                '  Monthly → [Quarter, Half-Year, Year] (steps=3 tries all)\n'
                '  Daily   → [Week, Fortnight, Month]\n'
                '  Weekly  → [Month, Quarter]\n'
                'Set to 0 to disable time aggregation entirely.'
            ),
        }),
        (_('Grain Options'), {
            'fields': ['evaluate_customer_grain'],
            'description': _(
                'If enabled, Part A drills down to '
                'Item × Leaf Location × Planning Customer as the finest grain. '
                'Disable if customer-level actuals are not available or reliable.'
            ),
        }),
    ]

    inlines = [AbcClassDefinitionInline]

    @admin.display(description='ABC Tiers')
    def abc_tier_summary(self, obj):
        """
        Show a compact summary of the client's ABC tiers in the list view.
        e.g.  A≤70% · B≤90% · C≤100%
        """
        tiers = AbcClassDefinition.objects.filter(
            client=obj.client
        ).order_by('rank')
        if not tiers:
            return mark_safe('<span style="color:#dc3545">No tiers defined</span>')
        parts = [
            f'<b>{t.label}</b>≤{t.cumulative_upper_pct}%'
            for t in tiers
        ]
        return mark_safe(' · '.join(parts))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    admin_role_only = True
```

---

### 1.3 `SeriesLevelEvaluationAdmin`

Read-only — rows are created by the Celery task only.
Planners use this to understand why each level was accepted or rejected.

```python
@admin.register(SeriesLevelEvaluation)
class SeriesLevelEvaluationAdmin(admin.ModelAdmin):
    """
    Audit trail of every level evaluated for every series.
    Read-only — populated by the compute_series_profiles Celery task.

    Planners use filters to answer questions like:
      "Which items are LUMPY at location level but forecastable at client level?"
      "Which items ended up needing quarterly aggregation?"
    """

    list_display = [
        'item_code',
        'grain_display',
        'eval_period_type',
        'demand_class_badge',
        'abc_class_badge',
        'adi', 'cv2',
        'nonzero_periods', 'total_periods',
        'value_share_pct_at_level',
        'accepted_badge',
        'rejection_reason',
        'computed_at',
    ]
    list_filter = [
        'client',
        'period_type',
        'eval_period_type',
        'demand_class',
        'abc_class',
        'is_accepted',
        ('grain', admin.AllValuesFieldListFilter),
    ]
    search_fields = [
        'item__item_id',
        'item__name',
        'planning_customer__code',
        'rejection_reason',
    ]
    date_hierarchy = 'computed_at'
    ordering = ['item__item_id', 'grain']

    # All fields are read-only — this is an audit log
    readonly_fields = [
        f.name for f in SeriesLevelEvaluation._meta.get_fields()
        if hasattr(f, 'name')
    ]

    fieldsets = [
        (_('Identity'), {
            'fields': [
                'client', 'item', 'planning_customer',
                'period_type', 'eval_period_type',
            ],
        }),
        (_('Evaluated Level'), {
            'fields': ['grain', 'evaluation_key'],
        }),
        (_('Analysis Window'), {
            'fields': ['analysis_from', 'analysis_to', 'computed_at'],
        }),
        (_('Demand Metrics'), {
            'fields': [
                'total_periods', 'nonzero_periods', 'total_qty',
                'adi', 'cv2', 'zero_rate',
            ],
        }),
        (_('Value and ABC'), {
            'fields': [
                'total_value',
                'abc_class',
                'value_share_pct_at_level',
                'value_rank_at_level',
            ],
        }),
        (_('Classification and Decision'), {
            'fields': [
                'demand_class',
                'is_accepted',
                'rejection_reason',
                'recommended_strategy',
            ],
        }),
    ]

    # ── Custom display columns ────────────────────────────────────────────────

    @admin.display(description='Item', ordering='item__item_id')
    def item_code(self, obj):
        return obj.item.item_id

    @admin.display(description='Grain')
    def grain_display(self, obj):
        """
        Format the grain string for readability.
        'item_loc_depth_2' → 'Item × Depth 2'
        'item_client_quarter' → 'Item × Client (Quarter)'
        'taxon_5_client' → 'Product Group × Client'
        """
        g = obj.grain
        if g == 'item_client':
            return 'Item × Client'
        if g == 'item_cust_location':
            return 'Item × Customer × Location'
        if g.startswith('item_loc_depth_'):
            depth = g.split('_')[-1]
            key   = obj.evaluation_key or {}
            label = key.get('level_label', f'Depth {depth}')
            return f'Item × {label}'
        if g.startswith('item_client_'):
            period = g.replace('item_client_', '')
            return f'Item × Client ({period.title()})'
        if g.startswith('taxon_') and '_client' in g:
            key   = obj.evaluation_key or {}
            label = key.get('node_name', 'Product Group')
            return f'{label} × Client'
        if g.startswith('taxon_') and '_' in g:
            key    = obj.evaluation_key or {}
            label  = key.get('node_name', 'Product Group')
            period = g.split('_')[-1]
            return f'{label} × Client ({period.title()})'
        return g

    @admin.display(description='Demand Class')
    def demand_class_badge(self, obj):
        colours = {
            'SMOOTH':       '#198754',
            'ERRATIC':      '#fd7e14',
            'INTERMITTENT': '#0dcaf0',
            'LUMPY':        '#dc3545',
            'INSUFFICIENT': '#6c757d',
            'ZERO':         '#212529',
        }
        c = colours.get(obj.demand_class, '#000')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 7px;'
            'border-radius:3px;font-size:11px;font-weight:bold">{l}</span>',
            c=c, l=obj.demand_class,
        )

    @admin.display(description='ABC')
    def abc_class_badge(self, obj):
        if not obj.abc_class:
            return '—'
        colours = {
            'A': '#0d6efd',
            'B': '#0dcaf0',
            'C': '#6c757d',
            'D': '#adb5bd',
        }
        c = colours.get(obj.abc_class, '#6c757d')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 7px;'
            'border-radius:3px;font-size:12px;font-weight:bold">{l}</span>',
            c=c, l=obj.abc_class,
        )

    @admin.display(description='Decision', boolean=False)
    def accepted_badge(self, obj):
        if obj.is_accepted:
            return format_html(
                '<span style="color:#198754;font-weight:bold">✓ Accepted</span>'
            )
        return format_html(
            '<span style="color:#dc3545">✗ Rejected</span>'
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False   # fully read-only

    admin_role_only = True
```

---

### 1.4 `SeriesProfileAdmin`

The summary view. The only editable fields are the planner override fields.
Clicking through to the detail view shows the evaluation log as a formatted
HTML table via `SeriesLevelEvaluation` inline.

```python
class SeriesLevelEvaluationReadOnlyInline(admin.TabularInline):
    """
    Shows the full evaluation log for this series inside SeriesProfileAdmin.
    Ordered from Step 0 (coarsest) to the accepted level.
    Read-only.
    """
    model        = SeriesLevelEvaluation
    extra        = 0
    can_delete   = False
    max_num      = 0
    show_change_link = True

    fields = [
        'grain_display_inline',
        'eval_period_type',
        'demand_class_badge_inline',
        'abc_class',
        'adi', 'cv2',
        'nonzero_periods',
        'value_share_pct_at_level',
        'accepted_badge_inline',
        'rejection_reason',
    ]
    readonly_fields = fields

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Order: accepted row last, rest by grain so the search path
        # reads top-to-bottom in the order it was evaluated
        return qs.order_by('is_accepted', 'grain')

    @admin.display(description='Level Evaluated')
    def grain_display_inline(self, obj):
        # Reuse same logic as SeriesLevelEvaluationAdmin
        g = obj.grain
        key = obj.evaluation_key or {}
        if g == 'item_client':
            return 'Item × Client'
        if g == 'item_cust_location':
            return 'Item × Customer × Location'
        if g.startswith('item_loc_depth_'):
            label = key.get('level_label', g.split('_')[-1])
            return f'Item × {label}'
        if g.startswith('item_client_'):
            period = g.replace('item_client_', '')
            return f'Item × Client ({period.title()})'
        if g.startswith('taxon_'):
            label  = key.get('node_name', 'Product Group')
            period = key.get('period_type', '')
            return f'{label} × Client' + (f' ({period.title()})' if period else '')
        return g

    @admin.display(description='Class')
    def demand_class_badge_inline(self, obj):
        colours = {
            'SMOOTH': '#198754', 'ERRATIC': '#fd7e14',
            'INTERMITTENT': '#0dcaf0', 'LUMPY': '#dc3545',
            'INSUFFICIENT': '#6c757d', 'ZERO': '#212529',
        }
        c = colours.get(obj.demand_class, '#000')
        return format_html(
            '<span style="background:{c};color:#fff;padding:1px 6px;'
            'border-radius:3px;font-size:11px">{l}</span>',
            c=c, l=obj.demand_class,
        )

    @admin.display(description='Decision')
    def accepted_badge_inline(self, obj):
        if obj.is_accepted:
            return format_html(
                '<b style="color:#198754">✓ CHOSEN</b>'
            )
        return format_html('<span style="color:#6c757d">✗</span>')


@admin.register(SeriesProfile)
class SeriesProfileAdmin(admin.ModelAdmin):
    """
    Summary of the level-selection decision per series.

    List view: planners scan items by ABC class, chosen grain, and demand class.
    Detail view: shows the full evaluation log as an inline table, then the
                 planner override section.

    Only override_grain, override_strategy, and override_note are editable.
    All classification fields are read-only (set by the Celery task).
    """

    list_display = [
        'item_code',
        'location_code',
        'customer_code',
        'period_type',
        'abc_class_badge',
        'demand_class_badge',
        'adi', 'cv2', 'nonzero_periods',
        'chosen_grain_display',
        'chosen_eval_period',
        'chosen_strategy',
        'effective_grain_display',
        'computed_at',
    ]
    list_filter = [
        'client',
        'period_type',
        'abc_class_atomic',
        'demand_class_atomic',
        'chosen_grain',
        'chosen_eval_period',
        'chosen_strategy',
        ('override_grain', admin.EmptyFieldListFilter),
    ]
    search_fields = [
        'item__item_id',
        'item__name',
        'planning_location__code',
        'planning_customer__code',
    ]
    date_hierarchy = 'computed_at'

    # Editable fields are ONLY the three planner override fields
    readonly_fields = [
        'client', 'item', 'planning_customer', 'planning_location',
        'period_type',
        'analysis_from', 'analysis_to', 'computed_at',
        'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
        'adi', 'cv2', 'zero_rate',
        'demand_class_atomic', 'abc_class_atomic',
        'chosen_evaluation',
        'chosen_grain', 'chosen_demand_class',
        'chosen_strategy', 'chosen_eval_period',
        'override_set_by', 'override_set_at',
        'effective_grain_display',
    ]

    fieldsets = [
        (_('Series Identity'), {
            'fields': [
                ('client', 'period_type'),
                ('item', 'planning_location', 'planning_customer'),
                ('analysis_from', 'analysis_to', 'computed_at'),
            ],
        }),
        (_('Metrics at Atomic Grain (Item × Customer × Location)'), {
            'fields': [
                ('total_periods', 'nonzero_periods', 'total_qty', 'total_value'),
                ('adi', 'cv2', 'zero_rate'),
            ],
            'classes': ['collapse'],
        }),
        (_('Classification at Atomic Grain'), {
            'fields': [
                ('demand_class_atomic', 'abc_class_atomic'),
            ],
        }),
        (_('Chosen Forecast Level (set by classification engine)'), {
            'fields': [
                'chosen_evaluation',
                ('chosen_grain', 'chosen_eval_period'),
                ('chosen_demand_class', 'chosen_strategy'),
                'effective_grain_display',
            ],
        }),
        (_('Planner Override'), {
            'fields': [
                'override_grain',
                'override_strategy',
                'override_note',
                ('override_set_by', 'override_set_at'),
            ],
            'description': _(
                'Set override_grain to force a specific aggregation level. '
                'The grain string must match one of the evaluated levels '
                'shown in the Evaluation Log below. '
                'Leave blank to use the engine\'s chosen level.'
            ),
        }),
    ]

    inlines = [SeriesLevelEvaluationReadOnlyInline]

    # ── Custom display columns ────────────────────────────────────────────────

    @admin.display(description='Item', ordering='item__item_id')
    def item_code(self, obj):
        return obj.item.item_id

    @admin.display(description='Location', ordering='planning_location__code')
    def location_code(self, obj):
        return obj.planning_location.code

    @admin.display(description='Customer')
    def customer_code(self, obj):
        return obj.planning_customer.code if obj.planning_customer else '—'

    @admin.display(description='ABC', ordering='abc_class_atomic')
    def abc_class_badge(self, obj):
        colours = {
            'A': '#0d6efd', 'B': '#0dcaf0',
            'C': '#6c757d', 'D': '#adb5bd',
        }
        val = obj.abc_class_atomic
        c   = colours.get(val, '#6c757d')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 8px;'
            'border-radius:3px;font-size:12px;font-weight:bold">{l}</span>',
            c=c, l=val or '—',
        )

    @admin.display(description='Demand Class', ordering='demand_class_atomic')
    def demand_class_badge(self, obj):
        colours = {
            'SMOOTH': '#198754', 'ERRATIC': '#fd7e14',
            'INTERMITTENT': '#0dcaf0', 'LUMPY': '#dc3545',
            'INSUFFICIENT': '#6c757d', 'ZERO': '#212529',
        }
        c = colours.get(obj.demand_class_atomic, '#000')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 7px;'
            'border-radius:3px;font-size:11px;font-weight:bold">{l}</span>',
            c=c, l=obj.demand_class_atomic or '—',
        )

    @admin.display(description='Chosen Grain', ordering='chosen_grain')
    def chosen_grain_display(self, obj):
        """Human-readable chosen grain with period type if different from base."""
        g = obj.chosen_grain or '—'
        if obj.chosen_eval_period and obj.chosen_eval_period != obj.period_type:
            return format_html(
                '{} <span style="color:#6c757d;font-size:11px">({})</span>',
                g, obj.chosen_eval_period,
            )
        return g

    @admin.display(description='Effective Grain')
    def effective_grain_display(self, obj):
        """Shows effective grain and flags when a planner override is active."""
        if obj.override_grain:
            return format_html(
                '<span style="color:#dc3545;font-weight:bold">{}</span> '
                '<span style="background:#dc3545;color:#fff;padding:1px 5px;'
                'border-radius:3px;font-size:10px">OVERRIDE</span>',
                obj.override_grain,
            )
        return format_html(
            '<span style="color:#198754">{}</span>',
            obj.chosen_grain or '—',
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related(
                'item', 'planning_location',
                'planning_customer', 'chosen_evaluation',
            )
        )

    def save_model(self, request, obj, form, change):
        """Stamp who set the override and when."""
        if 'override_grain' in form.changed_data or \
           'override_strategy' in form.changed_data:
            obj.override_set_by  = request.user
            obj.override_set_at  = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return False   # populated by Celery task only

    def has_delete_permission(self, request, obj=None):
        return False   # audit record — never delete

    admin_role_only = True
```

---

## 2. Serializers

### 2.1 File location

All additions go in `mysite/api/demand/serializers.py`.
Add the imports at the top alongside existing imports.

```python
from mysite.models.demand.forecast import (
    AbcClassDefinition,
    ForecastingConfig,
    SeriesLevelEvaluation,
    SeriesProfile,
)
```

---

### 2.2 `AbcClassDefinitionSerializer`

```python
class AbcClassDefinitionSerializer(serializers.ModelSerializer):
    """
    One ABC tier for a client.
    Read-only via the profile endpoints; editable via admin.
    """

    class Meta:
        model  = AbcClassDefinition
        fields = [
            'id', 'rank', 'label',
            'cumulative_upper_pct', 'description',
        ]
        read_only_fields = fields
```

---

### 2.3 `ForecastingConfigSerializer`

Two variants: a read-only summary (used inside profile responses)
and a full writable version (used on the config endpoint for superadmin).

```python
class ForecastingConfigSerializer(serializers.ModelSerializer):
    """
    Full config including ABC tiers.
    Writable — superadmin can update thresholds via PATCH.
    ABC tiers are read-only here; manage them via admin.
    """
    abc_class_definitions = AbcClassDefinitionSerializer(
        source='client.abc_class_definitions',
        many=True,
        read_only=True,
    )
    derived_time_horizons = serializers.SerializerMethodField()

    class Meta:
        model  = ForecastingConfig
        fields = [
            'id',
            'adi_threshold', 'cv2_threshold', 'min_nonzero_periods',
            'time_horizon_steps',
            'evaluate_customer_grain',
            'abc_class_definitions',
            'derived_time_horizons',
            'updated_at',
        ]
        read_only_fields = [
            'id', 'abc_class_definitions',
            'derived_time_horizons', 'updated_at',
        ]

    def get_derived_time_horizons(self, obj) -> list[str]:
        """
        Show the planner which time periods will actually be tried in Part C,
        given the version's period_type and this config's time_horizon_steps.

        Reads period_type from query param if available, else returns
        the monthly default.
        """
        from mysite.models.demand.actuals import get_higher_period_types
        request      = self.context.get('request')
        period_type  = (
            request.query_params.get('period_type', 'month')
            if request else 'month'
        )
        return get_higher_period_types(period_type, obj.time_horizon_steps)
```

---

### 2.4 `SeriesLevelEvaluationSerializer`

Used two ways:
1. As a nested list inside `SeriesProfileSerializer` (full audit trail)
2. Standalone for the `/series-profiles/{id}/evaluations/` endpoint

```python
class SeriesLevelEvaluationSerializer(serializers.ModelSerializer):
    """
    One evaluated level in the classification search for an item.
    Read-only — created by the Celery task.
    """
    item_id      = serializers.CharField(source='item.item_id', read_only=True)
    grain_label  = serializers.SerializerMethodField()

    class Meta:
        model  = SeriesLevelEvaluation
        fields = [
            'id',
            'item_id',
            'grain', 'grain_label',
            'evaluation_key',
            'period_type', 'eval_period_type',
            'analysis_from', 'analysis_to',
            # Metrics
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            # ABC
            'abc_class',
            'value_share_pct_at_level',
            'value_rank_at_level',
            # Classification
            'demand_class',
            'recommended_strategy',
            # Decision
            'is_accepted',
            'rejection_reason',
            'computed_at',
        ]
        read_only_fields = fields

    def get_grain_label(self, obj) -> str:
        """
        Human-readable label for the grain string.
        Mirrors the admin grain_display logic so the API and admin
        always show the same labels.
        """
        g   = obj.grain
        key = obj.evaluation_key or {}

        if g == 'item_client':
            return 'Item × Client Total'
        if g == 'item_cust_location':
            loc  = key.get('location_code', '?')
            cust = key.get('customer_code', '?')
            return f'Item × {loc} × {cust}'
        if g.startswith('item_loc_depth_'):
            label = key.get('level_label', g.split('_')[-1])
            node  = key.get('location_code') or key.get('location_id', '')
            return f'Item × {label} ({node})'
        if g.startswith('item_client_'):
            period = g.replace('item_client_', '')
            return f'Item × Client ({period.title()})'
        if g.startswith('taxon_') and g.endswith('_client'):
            name = key.get('node_name', 'Product Group')
            return f'{name} × Client'
        if g.startswith('taxon_'):
            name   = key.get('node_name', 'Product Group')
            period = key.get('period_type', '')
            suffix = f' ({period.title()})' if period else ''
            return f'{name} × Client{suffix}'
        return g
```

---

### 2.5 `SeriesProfileSerializer`

The main response object. Returns:
- Atomic grain metrics (the raw series at finest level)
- Chosen level (summary fields, denormalised for speed)
- Full evaluation log as nested list
- Override fields (writable)
- Computed `effective_grain` and `effective_strategy` properties

```python
class SeriesProfileSerializer(serializers.ModelSerializer):
    """
    Full series profile. Used for GET list and GET detail.

    Read-only fields: everything except override_grain, override_strategy,
    override_note.

    PATCH is the only mutating method. The PATCH view enforces that only
    the three override fields are writable.
    """

    # FK resolution
    item_id       = serializers.CharField(source='item.item_id',            read_only=True)
    item_name     = serializers.CharField(source='item.name',               read_only=True)
    location_code = serializers.CharField(source='planning_location.code',  read_only=True)
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )

    # Computed properties from model
    effective_grain    = serializers.CharField(read_only=True)
    effective_strategy = serializers.CharField(read_only=True)
    effective_eval_period = serializers.CharField(read_only=True)
    is_overridden      = serializers.BooleanField(read_only=True)
    is_manual          = serializers.BooleanField(read_only=True)

    # Override_set_by name (display only)
    override_set_by_name = serializers.SerializerMethodField()

    # Full evaluation log nested
    evaluations = serializers.SerializerMethodField()

    class Meta:
        model  = SeriesProfile
        fields = [
            'id',
            # Identity
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_type',
            'analysis_from', 'analysis_to', 'computed_at',
            # Atomic grain metrics
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            # Classification at atomic grain
            'demand_class_atomic', 'abc_class_atomic',
            # Chosen level (engine decision)
            'chosen_grain', 'chosen_demand_class',
            'chosen_strategy', 'chosen_eval_period',
            # Planner override (writable)
            'override_grain', 'override_strategy', 'override_note',
            'override_set_by_name', 'override_set_at',
            # Computed effective values
            'effective_grain', 'effective_strategy',
            'effective_eval_period',
            'is_overridden', 'is_manual',
            # Full audit trail
            'evaluations',
        ]
        read_only_fields = [
            'id',
            'item_id', 'item_name', 'location_code', 'customer_code',
            'period_type', 'analysis_from', 'analysis_to', 'computed_at',
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            'demand_class_atomic', 'abc_class_atomic',
            'chosen_grain', 'chosen_demand_class',
            'chosen_strategy', 'chosen_eval_period',
            'override_set_by_name', 'override_set_at',
            'effective_grain', 'effective_strategy',
            'effective_eval_period',
            'is_overridden', 'is_manual',
            'evaluations',
        ]
        # Writable: override_grain, override_strategy, override_note

    def get_override_set_by_name(self, obj) -> str | None:
        if obj.override_set_by:
            return (
                obj.override_set_by.get_full_name()
                or obj.override_set_by.username
            )
        return None

    def get_evaluations(self, obj) -> list:
        """
        Return all SeriesLevelEvaluation rows for this item, ordered
        so the evaluation search path reads top-to-bottom:
        rejected levels first (in evaluation order), accepted level last.
        """
        evals = (
            SeriesLevelEvaluation.objects
            .filter(
                client=obj.client,
                item=obj.item,
                period_type=obj.period_type,
            )
            .order_by('is_accepted', 'grain')
        )
        return SeriesLevelEvaluationSerializer(evals, many=True).data

    def validate_override_grain(self, value: str) -> str:
        """
        Validate that the override_grain matches an evaluated level
        for this item. Prevents planners from entering arbitrary strings.
        """
        if not value:
            return value

        # Get the instance being updated (PATCH context)
        instance = self.instance
        if instance is None:
            return value

        valid_grains = list(
            SeriesLevelEvaluation.objects
            .filter(
                client=instance.client,
                item=instance.item,
                period_type=instance.period_type,
            )
            .values_list('grain', flat=True)
        )

        if value not in valid_grains:
            raise serializers.ValidationError(
                f'"{value}" is not a valid grain for this series. '
                f'Valid grains: {", ".join(sorted(valid_grains))}'
            )
        return value

    def validate_override_strategy(self, value: str) -> str:
        valid = {'AUTOETS', 'AUTOARIMA', 'CROSTON', 'MOVING_AVG', 'MANUAL', ''}
        if value not in valid:
            raise serializers.ValidationError(
                f'"{value}" is not a valid strategy. '
                f'Valid values: {", ".join(sorted(valid - {""}))}.'
            )
        return value


class SeriesProfileListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for the list endpoint.
    Does NOT include the nested evaluations (too expensive for 10k+ rows).
    Use the detail endpoint for the full evaluation log.
    """
    item_id       = serializers.CharField(source='item.item_id',           read_only=True)
    location_code = serializers.CharField(source='planning_location.code', read_only=True)
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )
    effective_grain    = serializers.CharField(read_only=True)
    effective_strategy = serializers.CharField(read_only=True)
    is_overridden      = serializers.BooleanField(read_only=True)
    is_manual          = serializers.BooleanField(read_only=True)

    class Meta:
        model  = SeriesProfile
        fields = [
            'id',
            'item_id', 'location_code', 'customer_code',
            'period_type',
            # Key metrics for list scanning
            'abc_class_atomic', 'demand_class_atomic',
            'adi', 'cv2', 'nonzero_periods',
            # Level decision
            'chosen_grain', 'chosen_eval_period', 'chosen_strategy',
            # Override status
            'effective_grain', 'effective_strategy',
            'is_overridden', 'is_manual',
            'computed_at',
        ]
        read_only_fields = fields
```

---

## 3. Views (updated `SeriesProfileDetailView` and `SeriesProfileListView`)

Two changes from the earlier draft:

1. List view uses `SeriesProfileListSerializer` (no nested evaluations)
2. Detail view uses `SeriesProfileSerializer` (includes nested evaluations)
3. A new `SeriesProfileEvaluationsView` serves the evaluation log separately

```python
# In mysite/api/demand/views.py — replace the existing two SeriesProfile views

from mysite.api.demand.serializers import (
    SeriesProfileListSerializer,
    SeriesProfileSerializer,
    SeriesLevelEvaluationSerializer,
    ForecastingConfigSerializer,
)
from mysite.models.demand.forecast import (
    SeriesProfile, SeriesLevelEvaluation, ForecastingConfig,
)


class SeriesProfileListView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/series-profiles/

    Paginated list. Uses lightweight serializer — no nested evaluations.
    Use /series-profiles/{id}/ for the full detail including evaluation log.

    Query params:
        demand_class        — SMOOTH | ERRATIC | INTERMITTENT | LUMPY |
                              INSUFFICIENT | ZERO
        abc_class           — A | B | C | D (matches client's AbcClassDefinition labels)
        chosen_grain        — filter by chosen_grain value
        has_override        — true | false
        is_manual           — true  → only series needing planner input
        location_code       — filter by PlanningLocation.code
        period_type         — filter by period type
        page / page_size    — pagination (default 100, max 500)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            SeriesProfile.objects
            .filter(client=request.client)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('abc_class_atomic', 'demand_class_atomic', 'item__item_id')
        )

        p = request.query_params

        if p.get('demand_class'):
            qs = qs.filter(demand_class_atomic=p['demand_class'].upper())
        if p.get('abc_class'):
            qs = qs.filter(abc_class_atomic=p['abc_class'].upper())
        if p.get('chosen_grain'):
            qs = qs.filter(chosen_grain=p['chosen_grain'])
        if p.get('has_override') == 'true':
            qs = qs.exclude(override_grain='').exclude(override_strategy='')
        elif p.get('has_override') == 'false':
            qs = qs.filter(override_grain='', override_strategy='')
        if p.get('is_manual') == 'true':
            qs = qs.filter(chosen_strategy='MANUAL')
        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])
        if p.get('period_type'):
            qs = qs.filter(period_type=p['period_type'])

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
            'count':    paginator.count,
            'next':     self._page_url(request, page_num + 1, paginator.num_pages),
            'previous': self._page_url(request, page_num - 1, paginator.num_pages),
            'results':  SeriesProfileListSerializer(page.object_list, many=True).data,
        })

    def _page_url(self, request, page_num, num_pages):
        if page_num < 1 or page_num > num_pages:
            return None
        params = request.query_params.copy()
        params['page'] = page_num
        return request.build_absolute_uri(f'?{params.urlencode()}')


class SeriesProfileDetailView(DemandFeatureMixin, APIView):
    """
    GET   /api/demand/series-profiles/{id}/
          Full detail including nested evaluation log.

    PATCH /api/demand/series-profiles/{id}/
          Set override_grain / override_strategy / override_note.
          Only these three fields are accepted. All others rejected with 400.
    """
    permission_classes = [IsAuthenticated]

    def _get_profile(self, request, pk):
        return get_object_or_404(
            SeriesProfile.objects.select_related(
                'item', 'planning_location',
                'planning_customer', 'override_set_by',
            ),
            pk=pk, client=request.client,
        )

    def get(self, request, pk):
        profile = self._get_profile(request, pk)
        return Response(
            SeriesProfileSerializer(profile, context={'request': request}).data
        )

    def patch(self, request, pk):
        result = is_demand_feature_disabled(request.client, 'consensus_override')
        if result['disabled']:
            return Response(
                {'detail': result['message']},
                status=status.HTTP_403_FORBIDDEN,
            )

        profile = self._get_profile(request, pk)

        # Enforce that ONLY these three fields are patched
        allowed_fields = {'override_grain', 'override_strategy', 'override_note'}
        disallowed = set(request.data.keys()) - allowed_fields
        if disallowed:
            return Response(
                {
                    'detail': (
                        f'Fields not writable: {", ".join(sorted(disallowed))}. '
                        f'Only override_grain, override_strategy, and '
                        f'override_note may be updated.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SeriesProfileSerializer(
            profile, data=request.data, partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(
                serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )

        # Stamp override metadata
        from django.utils import timezone
        instance = serializer.save()
        instance.override_set_by  = request.user
        instance.override_set_at  = timezone.now()
        instance.save(update_fields=['override_set_by', 'override_set_at'])

        return Response(
            SeriesProfileSerializer(instance, context={'request': request}).data
        )


class SeriesProfileEvaluationsView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/series-profiles/{id}/evaluations/

    Returns the complete evaluation log for one series profile —
    every level that was tried, in search order, with metrics and decision.

    This is the same data as the nested 'evaluations' field on the detail
    endpoint, but available separately for clients that want to lazy-load it.

    Response:
        [
            {
                "grain":         "item_client",
                "grain_label":   "Item × Client Total",
                "demand_class":  "LUMPY",
                "abc_class":     "B",
                "adi":           "2.4000",
                "cv2":           "0.8100",
                "is_accepted":   false,
                "rejection_reason": "LUMPY (ADI=2.4, CV²=0.81)"
            },
            {
                "grain":         "item_loc_depth_1",
                "grain_label":   "Item × Region (NORTH)",
                "demand_class":  "INTERMITTENT",
                "abc_class":     "A",
                "adi":           "1.5000",
                "cv2":           "0.3200",
                "is_accepted":   true,
                "rejection_reason": ""
            }
        ]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        profile = get_object_or_404(
            SeriesProfile, pk=pk, client=request.client
        )
        evals = (
            SeriesLevelEvaluation.objects
            .filter(
                client=request.client,
                item=profile.item,
                period_type=profile.period_type,
            )
            .order_by('is_accepted', 'grain')
        )
        return Response(
            SeriesLevelEvaluationSerializer(evals, many=True).data
        )


class ForecastingConfigView(DemandFeatureMixin, APIView):
    """
    GET   /api/demand/forecasting-config/
          Return the client's ForecastingConfig including ABC tier definitions
          and derived time horizons for the requested period_type.

    PATCH /api/demand/forecasting-config/
          Update thresholds. ABC tiers must be managed via admin.
          Superadmin only.

    Query param:
        period_type — used to compute derived_time_horizons (default: month)
    """
    permission_classes = [IsAuthenticated]

    def _get_config(self, request):
        return ForecastingConfig.get_for_client(request.client)

    def get(self, request):
        config = self._get_config(request)
        return Response(
            ForecastingConfigSerializer(
                config, context={'request': request}
            ).data
        )

    def patch(self, request):
        # Superadmin only
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only staff users may update forecasting config.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        config = self._get_config(request)
        serializer = ForecastingConfigSerializer(
            config, data=request.data, partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)
```

---

## 4. URL additions

Add to `mysite/api/demand/urls.py`:

```python
path(
    'series-profiles/',
    views.SeriesProfileListView.as_view(),
    name='demand-series-profiles',
),
path(
    'series-profiles/<int:pk>/',
    views.SeriesProfileDetailView.as_view(),
    name='demand-series-profile-detail',
),
path(
    'series-profiles/<int:pk>/evaluations/',
    views.SeriesProfileEvaluationsView.as_view(),
    name='demand-series-profile-evaluations',
),
path(
    'forecasting-config/',
    views.ForecastingConfigView.as_view(),
    name='demand-forecasting-config',
),
```

---

## 5. `engine_config` Additions on `ForecastVersion`

The following keys are now formally documented on `ForecastVersion.engine_config`.
Update the `help_text` on the field:

```python
engine_config = models.JSONField(
    _('engine configuration'),
    default=dict,
    blank=True,
    help_text=_(
        'JSON object controlling the forecast engine. Supported keys:\n\n'
        '── MODEL SELECTION ─────────────────────────────────────────\n'
        '"models": ["AutoETS", "AutoARIMA"]\n'
        '    List of StatsForecast models to try. The engine picks the\n'
        '    best by cross-validation MAPE. Default: ["AutoETS"].\n\n'
        '"season_length": 12\n'
        '    Number of periods per seasonal cycle. Default: 12 for monthly.\n\n'
        '── RECONCILIATION ──────────────────────────────────────────\n'
        '"reconciliation": "MinTrace_ols"\n'
        '    Hierarchical reconciliation method. Options:\n'
        '    "BottomUp", "MinTrace_ols", "MinTrace_wls_struct".\n'
        '    Default: "MinTrace_ols".\n\n'
        '── DISAGGREGATION CONFLICT RESOLUTION ──────────────────────\n'
        '"disagg_conflict_resolution": "retain_lower"\n'
        '    Controls what happens when an item has its own forecast\n'
        '    at a fine grain (Part A) AND its product group also has\n'
        '    a forecast (Part B, because sibling items were LUMPY).\n'
        '    "retain_lower" (default): the finer-grain forecast wins.\n'
        '        The product-group disaggregation does not overwrite it.\n'
        '    "use_upper": the product-group disaggregation overwrites\n'
        '        all constituent items including those with their own\n'
        '        forecast. Use when you want a fully top-down plan.\n\n'
        '── FORECAST STORAGE ────────────────────────────────────────\n'
        '"store_all_level_forecasts": true\n'
        '    When true, a ForecastLine row is written for EVERY level\n'
        '    evaluated (not just the chosen one). Each row carries a\n'
        '    forecast_level tag. Enables post-run comparison without\n'
        '    re-running. Default: true. Set false to save storage.\n\n'
        '── LEVEL SELECTION OVERRIDES (run-level) ───────────────────\n'
        '"force_grain": null\n'
        '    When set to a grain string (e.g. "item_client"), ALL\n'
        '    series use this grain regardless of SeriesProfile.\n'
        '    Used for scenario runs: "what if we forecast everything\n'
        '    at client level?" Default: null (use SeriesProfile).\n\n'
        '"min_nonzero_override": null\n'
        '    Override ForecastingConfig.min_nonzero_periods for this\n'
        '    specific run. Useful for short-history pilots.\n\n'
        '── ACCURACY COMPUTATION ────────────────────────────────────\n'
        '"accuracy_lookback_periods": 6\n'
        '    How many past periods to include in ForecastAccuracy\n'
        '    computation for this version. Default: 6.\n'
    ),
)
```

### Valid `engine_config` example for reference

```json
{
    "models":                    ["AutoETS", "AutoARIMA"],
    "season_length":             12,
    "reconciliation":            "MinTrace_ols",
    "disagg_conflict_resolution": "retain_lower",
    "store_all_level_forecasts": true,
    "force_grain":               null,
    "min_nonzero_override":      null,
    "accuracy_lookback_periods": 6
}
```

### How `engine_config` is read in Sprint 3B.4 tasks

```python
# In run_forecast Celery task:

cfg = version.engine_config

reconciliation       = cfg.get('reconciliation', 'MinTrace_ols')
disagg_conflict      = cfg.get('disagg_conflict_resolution', 'retain_lower')
store_all_levels     = cfg.get('store_all_level_forecasts', True)
force_grain          = cfg.get('force_grain')          # None = use SeriesProfile
min_nonzero_override = cfg.get('min_nonzero_override') # None = use ForecastingConfig
season_length        = cfg.get('season_length', 12)
models               = cfg.get('models', ['AutoETS'])

# For each series:
grain_to_use = force_grain or profile.effective_grain

# After forecasting at all grains:
if disagg_conflict == 'retain_lower':
    # Do not overwrite fine-grain forecasts with product-group disaggregation
    pass
else:
    # use_upper: product-group disaggregation overwrites everything
    pass
```

---

## 6. Migration

```bash
python manage.py makemigrations mysite \
    --name abc_defs_forecasting_config_series_level_eval

python manage.py migrate
python manage.py check
```

**New tables:**
- `mysite_abcclassdefinition` — N rows per client defining ABC tiers
- `mysite_forecastingconfig` — one row per client
- `mysite_seriesleveleval` — one row per (item, level tried)

**Modified:**
- `mysite_seriesprofile` — new fields as listed in section 6 of
  `sprint_3b3_seriesprofile_final.md`
- `mysite_forecastversion.engine_config` — no schema change,
  help_text updated only (no migration needed for help_text)

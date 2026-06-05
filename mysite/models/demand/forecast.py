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

"""

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
        -- ForecastLine: fast lookup by version + period
        #""CREATE INDEX IF NOT EXISTS ix_fcstline_ver ON mysite_forecastline (version_id, period_start)#"",

        -- ForecastLine: item-level time series per version
        #""CREATE INDEX IF NOT EXISTS ix_fcstline_item_period ON mysite_forecastline (version_id, item_id, period_start)#"",

        -- ForecastLine: location drill-down
        #""CREATE INDEX IF NOT EXISTS ix_fcstline_loc_period ON mysite_forecastline (version_id, planning_location_id, period_start)#"",

        -- ForecastAggregate: version + level + period (the primary access pattern)
        #""CREATE INDEX IF NOT EXISTS ix_fcstagg_ver_level ON mysite_forecastaggregate (version_id, agg_level, period_start)#"",

        -- ForecastAccuracy: version + period for accuracy reports
        #""CREATE INDEX IF NOT EXISTS ix_fcstacc_ver_period ON mysite_forecastaccuracy (version_id, period_start)#"",


    ]
    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS ix_fcstline_ver', 
        'DROP INDEX IF EXISTS ix_fcstline_item_period',
        'DROP INDEX IF EXISTS ix_fcstline_loc_period',
        'DROP INDEX IF EXISTS ix_fcstagg_ver_level',
        'DROP INDEX IF EXISTS ix_fcstacc_ver_period', 
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
mysite/models/demand/forecast.py

Populated in Sprint 3B.1:
  ForecastVersion, ForecastLine, ForecastAggregate,
  ForecastOverride, OverrideSplitWeight, ForecastAccuracy
"""
# Models will be added in Sprint 3B.1.

"""
mysite/models/demand/forecast.py

Six models covering the full forecast lifecycle:

  ForecastVersion     — one planning run (draft → approved → locked)
  ForecastLine        — atomic SKU × customer × location × period forecast
  ForecastAggregate   — pre-rolled aggregates at any hierarchy level
  ForecastOverride    — planner consensus edits at any level
  OverrideSplitWeight — custom disaggregation weights for overrides
  ForecastAccuracy    — accuracy metrics once actuals land

  AbcClassDefinition
  ForecastingConfig
  SeriesLelvelEvaluation
  SeriesProfile       - New Addition
"""

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
    """
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
    """

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
    celery_task_id = models.CharField(
        _('celery task ID'),
        max_length=255,
        blank=True,
        help_text=_('ID of the Celery task chain currently running for this version.'),
    )
    run_status = models.CharField(
        _('run status'),
        max_length=16,
        blank=True,
        choices=[
            ('',             _('Not started')),
            ('QUEUED',       _('Queued')),
            ('PROFILING',    _('Profiling series')),
            ('RUNNING',      _('Running forecast')),
            ('RECONCILING',  _('Reconciling')),
            ('AGGREGATING',  _('Building aggregates')),
            ('COMPLETE',     _('Complete')),
            ('FAILED',       _('Failed')),
        ],
        help_text=_(
            'Granular progress state of the forecast run task. '
            'Separate from the version status workflow (DRAFT/IN_REVIEW/etc.).'
        ),
    )
    run_error = models.TextField(
        _('run error'),
        blank=True,
        help_text=_('Traceback if run_status=FAILED.'),
    )    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        app_label           = 'mysite'
        ordering            = ['-created_at']
        verbose_name        = _('02-15 Forecast Version')
        verbose_name_plural = _('02-15 Forecast Versions')
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

    price_used = models.DecimalField(
        _('price used'),
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_(
            'The ItemPlanningProfile.effective_price at the time the forecast '
            'was computed. Stored for audit — price may change after the run.'
        ),
    )
    statistical_value = models.DecimalField(
        _('statistical value'),
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('statistical_qty × price_used. Computed by the forecast engine.'),
    )
    override_value = models.DecimalField(
        _('override value'),
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_('override_qty × price_used. Null when no override is set.'),
    )
    final_value = models.DecimalField(
        _('final value'),
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        editable=False,
        help_text=_(
            'final_qty × price_used. Auto-computed in save(). '
            'Used for value-based disaggregation at product hierarchy levels '
            'and for aggregate rollups shown to planners.'
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
        verbose_name        = _('02-16 Forecast Line')
        verbose_name_plural = _('02-16 Forecast Lines')

    def save(self, *args, **kwargs):
        # Compute period_end
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)

        # Compute final_qty: override wins over statistical
        self.final_qty = (
            self.override_qty
            if self.override_qty is not None
            else self.statistical_qty
        )

        # Compute value fields when price is available
        if self.price_used is not None:
            two_dp = Decimal('0.01')
            self.statistical_value = (
                self.statistical_qty * self.price_used
            ).quantize(two_dp)
            self.override_value = (
                (self.override_qty * self.price_used).quantize(two_dp)
                if self.override_qty is not None else None
            )
            self.final_value = (
                self.final_qty * self.price_used
            ).quantize(two_dp)

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

    total_statistical_value = models.DecimalField(
        _('total statistical value'),
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            'Sum of ForecastLine.statistical_value across all constituent lines. '
            'This is the value the statistical engine produced before any overrides.'
        ),
    )
    total_override_value = models.DecimalField(
        _('total override value'),
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            'Sum of ForecastLine.override_value for lines that have an override. '
            'Null when no overrides exist in this aggregate node.'
        ),
    )
    total_final_value = models.DecimalField(
        _('total final value'),
        max_digits=20,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            'Sum of ForecastLine.final_value across all constituent lines. '
            'This is the primary value figure shown to planners at aggregate level. '
            'Used as the basis for value-based override disaggregation: '
            'a planner sets a target ₹ value here; the engine converts it to '
            'qty deltas per item using each item\'s price_used.'
        ),
    )

    # Used to convert a value-based planner override back to a qty delta
    # when the override is entered at aggregate level.
    weighted_avg_price = models.DecimalField(
        _('weighted average price'),
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        help_text=_(
            'sum(final_value) / sum(final_qty) across constituent lines. '
            'Computed by the rollup task. '
            'When a planner overrides total_final_value at this level, the '
            'engine computes: implied_qty = override_value / weighted_avg_price, '
            'then disaggregates the qty delta proportionally.'
        ),
    )

    class Meta:
        app_label = 'mysite'
        ordering  = ['agg_level', 'period_start']
        verbose_name        = _('02-17 Forecast Aggregate')
        verbose_name_plural = _('02-17 Forecast Aggregates')



    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        self.final_qty = (
            self.override_qty
            if self.override_qty is not None
            else self.statistical_qty
        )
        super().save(*args, **kwargs)

    # Note: total_statistical_value, total_override_value, total_final_value,
    # and weighted_avg_price are NOT computed in save() — they are set by the
    # Celery rollup task (write_forecast_aggregates in forecast_engine.py)
    # which aggregates ForecastLine rows in bulk using DuckDB.
    # Computing them in save() would require loading all constituent lines
    # on every aggregate save, which is prohibitively expensive.

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

    override_value = models.DecimalField(
        _('override value (₹)'),
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_(
            'Value-based override at aggregate levels. '
            'Mutually exclusive with override_qty and override_pct. '
            'Used when a planner sets a ₹ target for a product group or region. '
            'The engine converts this to a qty delta using '
            'ForecastAggregate.weighted_avg_price, then disaggregates '
            'the qty delta to constituent ForecastLine rows.'
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
        verbose_name        = _('02-18 Forecast Override')
        verbose_name_plural = _('02-18 Forecast Overrides')
        indexes = [
            models.Index(
                fields=['version', 'override_level', 'period_start'],
                name='ix_fcstovr_ver_level',
            ),
            models.Index(
                fields=['version', 'is_applied'],
                name='ix_fcstovr_ver_applied',
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

        # Exactly one of override_qty / override_pct / override_value must be set
        has_qty   = self.override_qty   is not None
        has_pct   = self.override_pct   is not None
        has_value = self.override_value is not None

        set_count = sum([has_qty, has_pct, has_value])

        if set_count > 1:
            raise ValidationError(
                _(
                    'Set exactly one of override_qty, override_pct, or '
                    'override_value — not multiple.'
                )
            )
        if set_count == 0:
            raise ValidationError(
                _(
                    'One of override_qty, override_pct, or override_value '
                    'must be set.'
                )
            )

        # override_value is only valid at aggregate levels — not SKU level
        if has_value and self.override_level == 'sku':
            raise ValidationError(
                _(
                    'override_value cannot be used at SKU level. '
                    'Use override_qty to set an absolute quantity, or '
                    'override_pct to adjust by percentage.'
                )
            )

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
        verbose_name        = _('02-19 Override Split Weight')
        verbose_name_plural = _('02-19 Override Split Weights')

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
        verbose_name        = _('02-20 Forecast Accuracy')
        verbose_name_plural = _('02-20 Forecast Accuracy Records')
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

# ─────────────────────────────────────────────────────────────────────────────
# 7. SeriesProfile
# ─────────────────────────────────────────────────────────────────────────────

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
        verbose_name        = _('02-11 ABC Class Definition')
        verbose_name_plural = _('02-11 ABC Class Definitions')

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
        verbose_name        = _('02-12 Forecasting Config')
        verbose_name_plural = _('02-12 Forecasting Configs')

    def __str__(self):
        return (
            f'{self.client} | ADI≥{self.adi_threshold} '
            f'CV²≥{self.cv2_threshold} | time_steps={self.time_horizon_steps}'
        )

    @classmethod
    def get_for_client(cls, client) -> 'ForecastingConfig':
        config, _ = cls.objects.get_or_create(client=client)
        return config
    

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
        verbose_name        = _('02-13 Series Level Evaluation')
        verbose_name_plural = _('02-13 Series Level Evaluations')
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

class SeriesProfile(models.Model):
    """
    Forecast level selection summary for one atomic series
    (item, customer, location). One row per unique atomic combination.

    chosen_evaluation FK points to the accepted SeriesLevelEvaluation row.
    chosen_grain is denormalised for fast filter/display without a join.

        Computed demand characteristics for one (item, customer, location) series.

    Populated by a Celery task that runs before forecast generation.
    The forecasting engine reads this to decide:
      a) which model to use (AutoETS vs Croston vs aggregate)
      b) at what level to forecast (SKU×Customer×Location vs SKU×Location vs Location)

    Metrics follow the Syntetos-Boylan (2005) classification framework.

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
        verbose_name        = _('02-14 Series Profile')
        verbose_name_plural = _('02-14 Series Profiles')
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


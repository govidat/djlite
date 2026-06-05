# Admin: ItemPlanningProfile, ForecastAggregate, ForecastOverride, OverrideSplitWeight
# Add to mysite/admin/demand_forecast.py

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe

from mysite.models.demand.actuals import ItemPlanningProfile
from mysite.models.demand.forecast import (
    ForecastAggregate,
    ForecastOverride,
    OverrideSplitWeight,
)
 

# ═════════════════════════════════════════════════════════════════════════════
# 1. ItemPlanningProfile
# ═════════════════════════════════════════════════════════════════════════════

@admin.register(ItemPlanningProfile)
class ItemPlanningProfileAdmin(admin.ModelAdmin):
    """
    Planners maintain standard_price here for every active item.
    weighted_avg_price and price_updated_at are read-only — set by the
    compute_series_profiles Celery task from ActualSale revenue data.

    Price resolution used by the forecast engine:
        1. weighted_avg_price  (preferred — actuals-derived)
        2. standard_price      (fallback — planner-set)

    Planners should review items where:
        - standard_price is set but weighted_avg_price is null
          (item has no revenue history — price is a pure estimate)
        - weighted_avg_price diverges significantly from standard_price
          (price has shifted — consider updating standard_price)
    """

    list_display = [
        'item_code',
        'client',
        'standard_price',
        'weighted_avg_price',
        'effective_price_display',
        'price_divergence_flag',
        'price_updated_at',
        'updated_at',
    ]
    list_filter  = ['client']
    search_fields = [
        'item__item_id',
        'item__name',
        'client__client_id',
    ]
    ordering = ['client', 'item__item_id']

    # ── Field layout ──────────────────────────────────────────────────────────
    readonly_fields = [
        'client',                   # set at creation, never changed
        'item',                     # set at creation, never changed
        'weighted_avg_price',       # Celery-managed — never hand-edit
        'price_updated_at',         # Celery-managed
        'updated_at',               # auto
        'effective_price_display',
        'price_divergence_flag',
        'actuals_revenue_note',
    ]

    fieldsets = [
        (_('Item'), {
            'fields': [('client', 'item')],
        }),
        (_('Planning Price'), {
            'fields': [
                'standard_price',
                'notes',
            ],
            'description': _(
                'Set the standard_price for every item before running a forecast. '
                'This is the transfer/selling price used to convert qty forecasts '
                'to value (₹) at all aggregate levels.'
            ),
        }),
        (_('Actuals-Derived Price (read-only)'), {
            'fields': [
                'weighted_avg_price',
                'price_updated_at',
                'effective_price_display',
                'price_divergence_flag',
                'actuals_revenue_note',
            ],
            'description': _(
                'weighted_avg_price is computed automatically by the '
                'compute_series_profiles task from sum(revenue)/sum(qty) '
                'over recent actuals. Do not edit manually.'
            ),
            'classes': ['collapse'],
        }),
        (_('Audit'), {
            'fields': ['updated_at'],
            'classes': ['collapse'],
        }),
    ]

    # ── Custom columns ────────────────────────────────────────────────────────

    @admin.display(description='Item ID', ordering='item__item_id')
    def item_code(self, obj):
        return obj.item.item_id

    @admin.display(description='Effective Price')
    def effective_price_display(self, obj):
        ep = obj.effective_price
        source = (
            'actuals-derived'
            if obj.weighted_avg_price
            else 'standard (no actuals revenue)'
        )
        return format_html(
            '<strong>₹{}</strong> <span style="color:#6c757d;font-size:11px">({})</span>',
            ep, source,
        )

    @admin.display(description='Price Check')
    def price_divergence_flag(self, obj):
        """
        Warn when weighted_avg_price diverges > 20% from standard_price.
        Helps planners spot stale standard prices.
        """
        if not obj.weighted_avg_price or not obj.standard_price:
            return '—'

        wap = float(obj.weighted_avg_price)
        sp  = float(obj.standard_price)
        if sp == 0:
            return '—'

        divergence_pct = abs(wap - sp) / sp * 100

        if divergence_pct > 30:
            return format_html(
                '<span style="color:#dc3545;font-weight:bold">'
                '⚠ {:.1f}% divergence — review standard_price'
                '</span>',
                divergence_pct,
            )
        if divergence_pct > 15:
            return format_html(
                '<span style="color:#fd7e14">'
                '△ {:.1f}% divergence'
                '</span>',
                divergence_pct,
            )
        return format_html(
            '<span style="color:#198754">✓ {:.1f}%</span>',
            divergence_pct,
        )

    @admin.display(description='Actuals Note')
    def actuals_revenue_note(self, obj):
        """
        Show how many ActualSale rows with revenue exist for this item,
        so planners know whether weighted_avg_price is well-supported.
        """
        from mysite.models.demand.actuals import ActualSale
        count = ActualSale.objects.filter(
            client=obj.client,
            item=obj.item,
            revenue__isnull=False,
        ).count()
        if count == 0:
            return format_html(
                '<span style="color:#dc3545">'
                'No actuals revenue rows — standard_price is the only source.'
                '</span>'
            )
        return format_html(
            '<span style="color:#198754">'
            '{} actuals rows with revenue data.'
            '</span>',
            count,
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('client', 'item')
        )

    admin_role_only = True


# ═════════════════════════════════════════════════════════════════════════════
# 2. ForecastAggregate
# ═════════════════════════════════════════════════════════════════════════════

@admin.register(ForecastAggregate)
class ForecastAggregateAdmin(admin.ModelAdmin):
    """
    Read-only view of pre-rolled aggregate forecasts.

    These rows are populated by the write_forecast_aggregates Celery task
    and are never written by planners directly. Planners use ForecastOverride
    to adjust values — the override task then re-rolls aggregates.

    Use this admin to:
        - Verify rollup totals after a forecast run
        - Compare statistical vs final value at category/region level
        - Spot aggregate nodes with large override adjustments
    """

    list_display = [
        'version_label',
        'agg_level',
        'agg_key_display',
        'period_type',
        'period_start',
        'statistical_qty',
        'final_qty',
        'override_indicator',
        'total_statistical_value',
        'total_final_value',
        'value_change_pct',
        'weighted_avg_price',
    ]
    list_filter  = [
        'version__client',
        'agg_level',
        'period_type',
        'version__status',
    ]
    search_fields = [
        'version__version_label',
    ]
    date_hierarchy = 'period_start'
    ordering = ['version', 'agg_level', 'period_start']

    readonly_fields = [
        f.name for f in ForecastAggregate._meta.get_fields()
        if hasattr(f, 'name')
    ]

    fieldsets = [
        (_('Version'), {
            'fields': ['version'],
        }),
        (_('Aggregation Key'), {
            'fields': ['agg_level', 'agg_key'],
        }),
        (_('Period'), {
            'fields': [('period_type', 'period_start', 'period_end')],
        }),
        (_('Quantity'), {
            'fields': [
                ('statistical_qty', 'override_qty', 'final_qty'),
            ],
        }),
        (_('Value'), {
            'fields': [
                ('total_statistical_value', 'total_override_value', 'total_final_value'),
                'weighted_avg_price',
            ],
            'description': _(
                'total_final_value is the primary number planners see when '
                'reviewing forecasts at aggregate level. weighted_avg_price '
                'is used to convert value-based overrides back to qty.'
            ),
        }),
    ]

    # ── Custom columns ────────────────────────────────────────────────────────

    @admin.display(description='Version', ordering='version__version_label')
    def version_label(self, obj):
        return obj.version.version_label

    @admin.display(description='Node')
    def agg_key_display(self, obj):
        """Render the JSON agg_key compactly."""
        key = obj.agg_key or {}
        if not key:
            return '—'
        # Show values only, not keys, for compactness
        return ' / '.join(str(v) for v in key.values())

    @admin.display(description='Override')
    def override_indicator(self, obj):
        if obj.override_qty is not None:
            delta = float(obj.final_qty) - float(obj.statistical_qty)
            sign  = '+' if delta >= 0 else ''
            colour = '#198754' if delta >= 0 else '#dc3545'
            return format_html(
                '<span style="color:{};font-weight:bold">{}{:.0f}</span>',
                colour, sign, delta,
            )
        return format_html('<span style="color:#6c757d">—</span>')

    @admin.display(description='Value Δ%')
    def value_change_pct(self, obj):
        """Show % change from statistical to final value."""
        if not obj.total_statistical_value or float(obj.total_statistical_value) == 0:
            return '—'
        if not obj.total_final_value:
            return '—'
        pct = (
            (float(obj.total_final_value) - float(obj.total_statistical_value))
            / float(obj.total_statistical_value) * 100
        )
        colour = '#198754' if pct >= 0 else '#dc3545'
        sign   = '+' if pct >= 0 else ''
        return format_html(
            '<span style="color:{}">{}{:.1f}%</span>',
            colour, sign, pct,
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('version', 'version__client')
        )

    def has_add_permission(self, request):
        return False   # populated by Celery task only

    def has_change_permission(self, request, obj=None):
        return False   # fully read-only

    def has_delete_permission(self, request, obj=None):
        return False

    admin_role_only = True


# ═════════════════════════════════════════════════════════════════════════════
# 3. OverrideSplitWeight inline (used inside ForecastOverrideAdmin)
# ═════════════════════════════════════════════════════════════════════════════

class OverrideSplitWeightInline(admin.TabularInline):
    """
    Explicit weights for CUSTOM disaggregation.
    Only relevant when ForecastOverride.disagg_method = CUSTOM.
    Weights across all children should sum to 1.0.

    Example: a category override of 1000 units split CUSTOM:
        child_key={"item_id": "ITEM-001"}  weight=0.500  → 500 units
        child_key={"item_id": "ITEM-002"}  weight=0.300  → 300 units
        child_key={"item_id": "ITEM-003"}  weight=0.200  → 200 units
    """
    model   = OverrideSplitWeight
    extra   = 1
    fields  = ['child_key', 'weight', 'weight_display']
    readonly_fields = ['weight_display']
    ordering = ['-weight']

    @admin.display(description='Share %')
    def weight_display(self, obj):
        if obj.weight is None:
            return '—'
        pct = float(obj.weight) * 100
        return f'{pct:.1f}%'

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('-weight')


# ═════════════════════════════════════════════════════════════════════════════
# 4. ForecastOverride
# ═════════════════════════════════════════════════════════════════════════════

@admin.register(ForecastOverride)
class ForecastOverrideAdmin(admin.ModelAdmin):
    """
    Planner consensus overrides. Editable only for DRAFT versions.

    Three override modes (exactly one must be set):
        override_qty   — absolute quantity target at this level
        override_pct   — percentage adjustment (e.g. +10%, -5%)
        override_value — ₹ value target at aggregate levels
                         (engine converts to qty via weighted_avg_price)

    disagg_method controls how the override is split to child ForecastLines:
        PROPORTIONAL — by historical quantity share (default)
        EQUAL        — equal split across all children
        CUSTOM       — explicit weights via OverrideSplitWeightInline

    is_applied = True once the Celery apply_overrides task has pushed
    this override down to ForecastLine.override_qty. Until then the
    ForecastLine rows still show the statistical values.
    """

    list_display = [
        'version_label',
        'version_status_badge',
        'override_level',
        'override_key_display',
        'period_type',
        'period_start',
        'override_mode_display',
        'disagg_method',
        'is_applied_badge',
        'created_by_name',
        'created_at',
    ]
    list_filter  = [
        'version__client',
        'override_level',
        'disagg_method',
        'is_applied',
        'period_type',
        'version__status',
    ]
    search_fields = [
        'version__version_label',
        'override_note',
        'created_by__username',
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    readonly_fields = [
        'version',          # set at creation
        'created_by',       # set at creation
        'created_at',
        'is_applied',       # Celery-managed
        'period_end',       # auto-computed
        'version_status_badge',
        'override_key_display',
        'override_mode_display',
    ]

    fieldsets = [
        (_('Version'), {
            'fields': [('version', 'version_status_badge')],
            'description': _(
                'Overrides can only be created or edited on DRAFT versions. '
                'Once the version moves to IN_REVIEW, overrides are frozen.'
            ),
        }),
        (_('What is being overridden'), {
            'fields': [
                ('override_level', 'override_key'),
                ('period_type', 'period_start'),
            ],
        }),
        (_('Override Value (set exactly one)'), {
            'fields': [
                'override_qty',
                'override_pct',
                'override_value',
            ],
            'description': _(
                'override_qty: absolute units at this level.\n'
                'override_pct: percentage adjustment (positive = increase, '
                'negative = decrease).\n'
                'override_value (₹): target revenue value — engine converts to '
                'qty using weighted_avg_price. Only valid at aggregate levels '
                '(not SKU).'
            ),
        }),
        (_('Disaggregation'), {
            'fields': ['disagg_method', 'override_note'],
            'description': _(
                'PROPORTIONAL: split by historical qty share (default). '
                'EQUAL: equal split across all children. '
                'CUSTOM: use the split weights defined below.'
            ),
        }),
        (_('Status'), {
            'fields': [('is_applied', 'created_by', 'created_at')],
            'classes': ['collapse'],
        }),
    ]

    inlines = [OverrideSplitWeightInline]

    # ── Custom columns ────────────────────────────────────────────────────────

    @admin.display(description='Version', ordering='version__version_label')
    def version_label(self, obj):
        return obj.version.version_label

    @admin.display(description='Status')
    def version_status_badge(self, obj):
        colours = {
            'DRAFT':     '#6c757d',
            'IN_REVIEW': '#fd7e14',
            'APPROVED':  '#198754',
            'LOCKED':    '#0d6efd',
        }
        s = obj.version.status
        c = colours.get(s, '#000')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 7px;'
            'border-radius:3px;font-size:11px;font-weight:bold">{s}</span>',
            c=c, s=s,
        )

    @admin.display(description='Key')
    def override_key_display(self, obj):
        key = obj.override_key or {}
        return ' / '.join(str(v) for v in key.values()) or '—'

    @admin.display(description='Override')
    def override_mode_display(self, obj):
        if obj.override_qty is not None:
            return format_html(
                '<span style="color:#0d6efd">Qty: <strong>{}</strong></span>',
                obj.override_qty,
            )
        if obj.override_pct is not None:
            sign   = '+' if obj.override_pct >= 0 else ''
            colour = '#198754' if obj.override_pct >= 0 else '#dc3545'
            return format_html(
                '<span style="color:{}">Pct: <strong>{}{}</strong></span>',
                colour, sign, obj.override_pct,
            )
        if obj.override_value is not None:
            return format_html(
                '<span style="color:#6610f2">₹ Value: <strong>{}</strong></span>',
                obj.override_value,
            )
        return format_html('<span style="color:#dc3545">⚠ None set</span>')

    @admin.display(description='Applied', boolean=False)
    def is_applied_badge(self, obj):
        if obj.is_applied:
            return format_html(
                '<span style="color:#198754;font-weight:bold">✓ Applied</span>'
            )
        return format_html(
            '<span style="color:#fd7e14">⏳ Pending</span>'
        )

    @admin.display(description='Created by')
    def created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return '—'

    # ── Guards: enforce DRAFT-only editing ────────────────────────────────────

    def get_readonly_fields(self, request, obj=None):
        """
        When the version is not DRAFT, make ALL fields read-only.
        Planners can still view the override but cannot change anything.
        """
        base = list(self.readonly_fields)
        if obj and not obj.version.is_editable:
            # Add all editable fields to readonly
            editable = {
                'override_level', 'override_key',
                'period_type', 'period_start',
                'override_qty', 'override_pct', 'override_value',
                'disagg_method', 'override_note',
            }
            base.extend(editable)
        return base

    def has_change_permission(self, request, obj=None):
        """
        Block edits entirely if the version is not DRAFT.
        The override inline (OverrideSplitWeightInline) inherits this.
        """
        if obj and not obj.version.is_editable:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """
        Allow deletion only for unapplied overrides on DRAFT versions.
        Once applied, an override is part of the audit trail.
        """
        if obj:
            if not obj.version.is_editable:
                return False
            if obj.is_applied:
                return False
        return super().has_delete_permission(request, obj)

    def save_model(self, request, obj, form, change):
        """Stamp created_by on new overrides."""
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('version', 'version__client', 'created_by')
        )

    admin_role_only = True

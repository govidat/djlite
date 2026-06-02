"""
Admin registrations for models currently missing from the admin site.
 
Add these to:
  mysite/admin/demand_forecast.py     ← ForecastAggregate, ForecastOverride,
                                          OverrideSplitWeight
  mysite/admin/demand_items.py        ← ItemPlanningProfile
  (or whichever admin file covers the Item / planning-setup models)

─────────────────────────────────────────────────────────────────────────────
SECTION A — demand_forecast.py additions
─────────────────────────────────────────────────────────────────────────────
Add these imports at the top of demand_forecast.py alongside the existing ones:

    from mysite.models.demand.forecast import (
        ...,
        ForecastAggregate,
        ForecastOverride,
        OverrideSplitWeight,
    )
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

# ─────────────────────────────────────────────────────────────────────────────
# A-1.  ForecastAggregate
# ─────────────────────────────────────────────────────────────────────────────
# ForecastAggregate rows are written exclusively by the Celery rollup task —
# planners never create or edit them directly.  The admin is therefore
# fully read-only and oriented toward inspection / debugging.

@admin.register(ForecastAggregate)
class ForecastAggregateAdmin(admin.ModelAdmin):
    """
    Read-only view of pre-rolled forecast totals at any hierarchy level.

    Rows are populated by the write_forecast_aggregates Celery task (Sprint 3B.4).
    Planners and superadmins use this to verify rollup results and investigate
    value-based override calculations (weighted_avg_price).

    Access pattern:
      • Filter by version + agg_level to see all nodes at one level.
      • Filter by period_start to narrow to a single forecast period.
      • Use the search to find a specific JSON key (e.g. category name).
    """

    list_display = [
        'version',
        'agg_level',
        'agg_key',
        'period_type',
        'period_start',
        'statistical_qty',
        'override_qty',
        'final_qty',
        'total_final_value',
        'weighted_avg_price',
    ]
    list_filter = [
        'version__client',
        'agg_level',
        'period_type',
        'version__status',
    ]
    search_fields = [
        # agg_key is a JSONField; Django converts it to text for LIKE search
        'agg_key',
        'version__version_label',
        'version__client__client_id',
    ]
    date_hierarchy = 'period_start'
    ordering = ['version', 'agg_level', 'period_start']

    # Every field is read-only — this is a Celery-owned table.
    readonly_fields = [
        'version',
        'agg_level', 'agg_key',
        'period_type', 'period_start', 'period_end',
        'statistical_qty', 'override_qty', 'final_qty',
        'total_statistical_value', 'total_override_value', 'total_final_value',
        'weighted_avg_price',
    ]

    fieldsets = [
        (_('Version & Level'), {
            'fields': [
                'version',
                ('agg_level', 'agg_key'),
            ],
        }),
        (_('Period'), {
            'fields': [('period_type', 'period_start', 'period_end')],
        }),
        (_('Quantities'), {
            'fields': [
                ('statistical_qty', 'override_qty', 'final_qty'),
            ],
        }),
        (_('Value Rollups'), {
            'fields': [
                ('total_statistical_value', 'total_override_value', 'total_final_value'),
                'weighted_avg_price',
            ],
            'description': _(
                'Populated by the Celery rollup task. '
                'weighted_avg_price = total_final_value / final_qty. '
                'Used by the override engine to convert ₹ targets to qty deltas.'
            ),
            'classes': ['collapse'],
        }),
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('version', 'version__client')
        )

    # Prevent any accidental mutations.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    admin_role_only = True


# ─────────────────────────────────────────────────────────────────────────────
# A-2.  OverrideSplitWeight inline
# ─────────────────────────────────────────────────────────────────────────────

class OverrideSplitWeightInline(admin.TabularInline):
    """
    Custom disaggregation weights for a CUSTOM-method override.
    Shown inside ForecastOverrideAdmin when disagg_method=CUSTOM.
    """

    model           = OverrideSplitWeight
    extra           = 0
    fields          = ['child_key', 'weight']
    # Weights can be edited by planners (or superadmins) directly in the admin.
    readonly_fields = []

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('id')


# ─────────────────────────────────────────────────────────────────────────────
# A-3.  ForecastOverrideAdmin
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(ForecastOverride)
class ForecastOverrideAdmin(admin.ModelAdmin):
    """
    Audit trail and management view for planner consensus edits.

    ForecastOverride rows are normally created via the API / React UI.
    This admin is primarily an inspection and debugging tool —
    superadmins can also manually create or retrigger overrides here.

    Key workflow notes:
    • Only DRAFT versions accept new overrides (enforced by model.clean()).
    • is_applied is set by the Celery disaggregation task; reset it to False
      here to re-trigger disaggregation on the next task run.
    • CUSTOM disagg_method overrides show their OverrideSplitWeight rows inline.
    """

    list_display = [
        'version',
        'override_level',
        'override_key',
        'period_type',
        'period_start',
        'override_type_display',
        'disagg_method',
        'applied_badge',
        'created_by',
        'created_at',
    ]
    list_filter = [
        'version__client',
        'override_level',
        'disagg_method',
        'is_applied',
        'period_type',
        'version__status',
    ]
    search_fields = [
        'override_key',
        'version__version_label',
        'created_by__username',
        'override_note',
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    readonly_fields = [
        'is_applied',
        'created_by',
        'created_at',
        'period_end',
    ]

    fieldsets = [
        (_('Version'), {
            'fields': ['version'],
        }),
        (_('Override Target'), {
            'fields': [
                ('override_level', 'override_key'),
                ('period_type', 'period_start', 'period_end'),
            ],
            'description': _(
                'override_key is a JSON object identifying what is being overridden. '
                'Examples: {"item_id": "ITEM-001"} for SKU level; '
                '{"category": "Braking Systems"} for category level.'
            ),
        }),
        (_('Override Value'), {
            'fields': [
                'override_qty',
                'override_pct',
                'override_value',
            ],
            'description': _(
                'Set exactly one of these three fields. '
                'override_qty = absolute quantity; '
                'override_pct = percentage adjustment (+10 or -5); '
                'override_value = ₹ target (aggregate levels only, not SKU).'
            ),
        }),
        (_('Disaggregation'), {
            'fields': ['disagg_method'],
        }),
        (_('Notes & Audit'), {
            'fields': [
                'override_note',
                'created_by', 'created_at',
                'is_applied',
            ],
        }),
    ]

    inlines = [OverrideSplitWeightInline]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('version', 'version__client', 'created_by')
        )

    def save_model(self, request, obj, form, change):
        # Stamp created_by on first save.
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    # ── Custom display columns ────────────────────────────────────────────────

    @admin.display(description=_('Override Type'))
    def override_type_display(self, obj):
        """Show which of the three override fields is set and its value."""
        if obj.override_qty is not None:
            return format_html(
                'qty&nbsp;<b>{}</b>',
                obj.override_qty,
            )
        if obj.override_pct is not None:
            sign = '+' if obj.override_pct >= 0 else ''
            return format_html(
                'pct&nbsp;<b>{}{}&nbsp;%</b>',
                sign,
                obj.override_pct,
            )
        if obj.override_value is not None:
            return format_html(
                '₹&nbsp;<b>{}</b>',
                obj.override_value,
            )
        return '—'

    @admin.display(description=_('Applied'), boolean=False)
    def applied_badge(self, obj):
        if obj.is_applied:
            return format_html(
                '<span style="color:#198754;font-weight:bold">✓ Applied</span>'
            )
        return format_html(
            '<span style="color:#fd7e14">⏳ Pending</span>'
        )

    admin_role_only = True


# ─────────────────────────────────────────────────────────────────────────────
# A-4.  OverrideSplitWeightAdmin  (standalone, for bulk inspection)
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(OverrideSplitWeight)
class OverrideSplitWeightAdmin(admin.ModelAdmin):
    """
    Standalone view of custom disaggregation weights.

    Normally managed via the OverrideSplitWeightInline inside
    ForecastOverrideAdmin. This standalone view is useful for:
    • Bulk inspection across many overrides.
    • Verifying that weights for a CUSTOM override sum to 1.0.
    • Debugging disaggregation task failures.
    """

    list_display    = ['override', 'child_key', 'weight', 'weight_pct_display']
    list_filter     = ['override__version__client', 'override__disagg_method']
    search_fields   = [
        'child_key',
        'override__version__version_label',
    ]
    ordering        = ['override', 'id']

    readonly_fields = []   # weights are editable

    fieldsets = [
        (None, {
            'fields': ['override', 'child_key', 'weight'],
            'description': _(
                'child_key: JSON identifying the child node receiving this weight. '
                'Example: {"item_id": "SKU-001"} or {"location_code": "DEL"}. '
                'All weights for one override should sum to 1.0 — enforced by '
                'the disaggregation task, not the database.'
            ),
        }),
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('override', 'override__version', 'override__version__client')
        )

    @admin.display(description=_('Weight %'))
    def weight_pct_display(self, obj):
        """Show weight as a percentage for readability."""
        if obj.weight is not None:
            return f'{float(obj.weight) * 100:.2f}%'
        return '—'

    admin_role_only = True


# =============================================================================
# SECTION B — ItemPlanningProfile
# =============================================================================
# Add this to whichever admin file covers Item / planning-setup models,
# e.g. mysite/admin/demand_items.py  (or demand_hierarchy.py).
#
# Add this import at the top of that file:
#
#     from mysite.models.demand.items import ItemPlanningProfile
#                                         ↑ adjust to the actual module path
#
# The admin class below assumes the fields present on ItemPlanningProfile
# as inferred from its usage in ForecastLine.price_used help text and the
# broader Sprint 3B design (item-level planning config: price, lead time, etc.).
# Adjust field lists to match your actual model definition.
# =============================================================================

@admin.register(ItemPlanningProfile)
class ItemPlanningProfileAdmin(admin.ModelAdmin):
    """
    Item-level planning configuration — one row per (client, item).

    Holds the reference price and any other per-item planning parameters
    used by the forecast engine (e.g. effective_price captured in
    ForecastLine.price_used at run time).

    Planners and admins can edit these; the values are snapshotted into
    ForecastLine at forecast-run time so historical forecasts are not
    affected by later price changes.
    """

    list_display = [
        'item',
        'client',
        'effective_price',
        'is_active',
        'updated_at',
    ]
    list_filter  = ['client', 'is_active']
    search_fields = [
        'item__item_id',
        'item__name',
        'client__client_id',
    ]
    ordering = ['client', 'item__item_id']

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = [
        (_('Identity'), {
            'fields': ['client', 'item', 'is_active'],
        }),
        (_('Pricing'), {
            'fields': ['effective_price'],
            'description': _(
                'The price snapshotted into ForecastLine.price_used at forecast '
                'run time. Changing this after a forecast run does not alter '
                'historical ForecastLine rows.'
            ),
        }),
        (_('Audit'), {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse'],
        }),
    ]

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('item', 'client')
        )

    admin_role_only = True

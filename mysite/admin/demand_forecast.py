from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAggregate,
    ForecastOverride, OverrideSplitWeight, ForecastAccuracy,
)

from django.urls import reverse
from django.utils.safestring import mark_safe

from mysite.models.demand.forecast import (
    AbcClassDefinition,
    ForecastingConfig,
    SeriesLevelEvaluation,
    SeriesProfile,
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
        'price_used', 'statistical_value', 'override_value', 'final_value'
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
        'override_qty', 'override_pct', 'disagg_method', 'override_value',
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

#@admin.register(ForecastVersion)
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

#@admin.register(ForecastLine)
class ForecastLineAdmin(admin.ModelAdmin):
    list_display   = [
        'version', 'period_type', 'period_start',
        'item', 'planning_location', 'planning_customer',
        'statistical_qty', 'override_qty', 'final_qty', 'forecast_level', 'model_used',
        'price_used', 'statistical_value', 'override_value', 'final_value'
    ]
    list_filter    = ['version__client', 'period_type', 'version__status']
    search_fields  = [
        'item__item_id', 'item__name',
        'planning_location__code', 'planning_customer__code',
        'version__version_label',
    ]
    date_hierarchy = 'period_start'
    readonly_fields = ['period_end', 'final_qty', 'forecast_level', 'model_used', 'price_used', 'statistical_value', 'override_value', 'final_value']

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

#@admin.register(ForecastAccuracy)
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


#@admin.register(AbcClassDefinition)
class AbcClassDefinitionAdmin(admin.ModelAdmin):
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

    list_display  = ['client', 'rank', 'label', 'cumulative_upper_pct', 'description']
    list_filter   = ['client']
    ordering      = ['client', 'rank']

    def get_queryset(self, request):
        return super().get_queryset(request).order_by('client', 'rank')

    admin_role_only = True

#@admin.register(ForecastingConfig)
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
        'abc_tiers_link',       # ← replaces the inline
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

    #inlines = [AbcClassDefinitionInline]

    @admin.display(description='ABC Tiers')
    def abc_tier_summary(self, obj):
        from django.utils.safestring import mark_safe
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

    @admin.display(description='Edit Tiers')
    def abc_tiers_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        url = (
            reverse('admin:mysite_abcclassdefinition_changelist')
            + f'?client__id__exact={obj.client_id}'
        )
        count = AbcClassDefinition.objects.filter(client=obj.client).count()
        return format_html(
            '<a href="{}">Manage {} tier{}</a>',
            url, count, 's' if count != 1 else '',
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

    admin_role_only = True


#@admin.register(SeriesLevelEvaluation)
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


#@admin.register(SeriesProfile)
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
        'evaluation_log_link',     # ← replaces the inline
    ]

    fieldsets = [
        (_('Series Identity'), {
            'fields': [
                ('client', 'period_type'),
                ('item', 'planning_location', 'planning_customer'),
                ('analysis_from', 'analysis_to', 'computed_at'),
            ],
        }),
        (_('Metrics at Atomic Grain'), {
            'fields': [
                ('total_periods', 'nonzero_periods', 'total_qty', 'total_value'),
                ('adi', 'cv2', 'zero_rate'),
            ],
            'classes': ['collapse'],
        }),
        (_('Classification at Atomic Grain'), {
            'fields': [('demand_class_atomic', 'abc_class_atomic')],
        }),
        (_('Chosen Forecast Level'), {
            'fields': [
                'chosen_evaluation',
                ('chosen_grain', 'chosen_eval_period'),
                ('chosen_demand_class', 'chosen_strategy'),
                'effective_grain_display',
            ],
        }),
        (_('Evaluation Log'), {
            'fields': ['evaluation_log_link'],   # ← link to filtered changelist
        }),
        (_('Planner Override'), {
            'fields': [
                'override_grain',
                'override_strategy',
                'override_note',
                ('override_set_by', 'override_set_at'),
            ],
        }),
    ]

    #inlines = [SeriesLevelEvaluationReadOnlyInline]

    # ── Custom display columns ────────────────────────────────────────────────
    @admin.display(description='Evaluation Log')
    def evaluation_log_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if not obj.pk:
            return '—'
        url = (
            reverse('admin:mysite_seriesleveleval_changelist')
            + f'?client__id__exact={obj.client_id}'
            + f'&item__id__exact={obj.item_id}'
            + f'&period_type__exact={obj.period_type}'
        )
        count = SeriesLevelEvaluation.objects.filter(
            client=obj.client,
            item=obj.item,
            period_type=obj.period_type,
        ).count()
        return format_html(
            '<a href="{}" target="_blank">'
            'View {} evaluation{} for this item →'
            '</a>',
            url, count, 's' if count != 1 else '',
        )
    
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

# ═════════════════════════════════════════════════════════════════════════════
# 2. ForecastAggregate
# ═════════════════════════════════════════════════════════════════════════════

#@admin.register(ForecastAggregate)
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

#@admin.register(ForecastOverride)
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

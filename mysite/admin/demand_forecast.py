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
        'statistical_qty', 'override_qty', 'final_qty', 'forecast_level', 'model_used'
    ]
    list_filter    = ['version__client', 'period_type', 'version__status']
    search_fields  = [
        'item__item_id', 'item__name',
        'planning_location__code', 'planning_customer__code',
        'version__version_label',
    ]
    date_hierarchy = 'period_start'
    readonly_fields = ['period_end', 'final_qty', 'forecast_level', 'model_used']

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
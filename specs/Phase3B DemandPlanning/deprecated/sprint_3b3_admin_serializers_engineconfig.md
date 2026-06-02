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

# `mysite/api/demand/serializers.py`

from rest_framework import serializers
from mysite.models.demand.hierarchy import (
    PlanningLocation, SalesNode, CustomerSalesAssignment, PlanningCustomer,
)
from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine,
    ForecastAggregate, ForecastOverride
)

from mysite.models.demand.forecast import (
    AbcClassDefinition,
    ForecastingConfig,
    SeriesLevelEvaluation,
    SeriesProfile,
)
# ─────────────────────────────────────────────────────────────────────────────
# Planning Location tree
# ─────────────────────────────────────────────────────────────────────────────

class PlanningLocationTreeSerializer(serializers.ModelSerializer):
    """
    Recursive serializer for PlanningLocation.
    children are populated only for root-call nodes; leaves return [].
    The full tree is built in the view by fetching all nodes in one query
    and assembling in Python (avoids N+1).
    """
    children = serializers.SerializerMethodField()

    class Meta:
        model  = PlanningLocation
        fields = [
            'id', 'code', 'name', 'level_label',
            'is_leaf', 'is_active', 'depth', 'path',
            'children',
        ]

    def get_children(self, obj):
        # Children are pre-attached by the view (see build_tree() below)
        children = getattr(obj, '_children', [])
        return PlanningLocationTreeSerializer(children, many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# Sales Node tree
# ─────────────────────────────────────────────────────────────────────────────

class CustomerSalesAssignmentSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True
    )
    customer_name = serializers.CharField(
        source='planning_customer.name', read_only=True
    )

    class Meta:
        model  = CustomerSalesAssignment
        fields = ['id', 'customer_code', 'customer_name', 'valid_from', 'valid_to']


class SalesNodeTreeSerializer(serializers.ModelSerializer):
    children             = serializers.SerializerMethodField()
    active_assignments   = serializers.SerializerMethodField()
    location_code        = serializers.CharField(
        source='planning_location.code', read_only=True, default=None
    )
    location_name        = serializers.CharField(
        source='planning_location.name', read_only=True, default=None
    )

    class Meta:
        model  = SalesNode
        fields = [
            'id', 'code', 'name', 'level_label', 'is_active',
            'depth', 'path',
            'location_code', 'location_name',
            'active_assignments',
            'children',
        ]

    def get_children(self, obj):
        children = getattr(obj, '_children', [])
        return SalesNodeTreeSerializer(children, many=True).data

    def get_active_assignments(self, obj):
        from django.utils import timezone
        today = timezone.now().date()
        assignments = [
            a for a in getattr(obj, '_assignments', [])
            if a.valid_from <= today and (a.valid_to is None or a.valid_to >= today)
        ]
        return CustomerSalesAssignmentSerializer(assignments, many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# Actuals serializers (used by Sprint 3B.2 endpoints)
# ─────────────────────────────────────────────────────────────────────────────

class ActualSaleImportSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        from mysite.models.demand.actuals import ActualSaleImport
        model  = ActualSaleImport
        fields = [
            'id', 'file_name', 'period_type', 'row_count',
            'status', 'error_log', 'uploaded_at', 'uploaded_by_name',
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.username
        return None


class ActualSaleSerializer(serializers.ModelSerializer):
    item_id           = serializers.CharField(source='item.item_id', read_only=True)
    item_name         = serializers.CharField(source='item.name',    read_only=True)
    location_code     = serializers.CharField(
        source='planning_location.code', read_only=True
    )
    customer_code     = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )

    class Meta:
        from mysite.models.demand.actuals import ActualSale
        model  = ActualSale
        fields = [
            'id',
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_type', 'period_start', 'period_end',
            'qty', 'revenue',
        ]

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
            'statistical_qty', 'override_qty', 'final_qty', 'forecast_level', 'model_used', 
            'price_used', 'statistical_value', 'override_value', 'final_value',
        ]
        read_only_fields = ['period_end', 'final_qty', 'statistical_qty', 'forecast_level', 'model_used', 'price_used', 'statistical_value', 'override_value', 'final_value']


class ForecastAggregateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ForecastAggregate
        fields = [
            'id', 'agg_level', 'agg_key',
            'period_type', 'period_start', 'period_end',
            'statistical_qty', 'override_qty', 'final_qty',
            'total_statistical_value', 'total_override_value', 'total_final_value','weighted_avg_price'
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
            'disagg_method', 'override_note', 'override_value',
            'is_applied', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['is_applied', 'created_at', 'created_by_name']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None
    
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

    item_id           = serializers.CharField(source='item.item_id',         read_only=True)
    item_name         = serializers.CharField(source='item.name',            read_only=True)
    location_code     = serializers.CharField(
        source='planning_location.code', read_only=True
    )
    customer_code     = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )
    effective_strategy = serializers.CharField(read_only=True)

    class Meta:
        model  = SeriesProfile
        fields = [
            'id',
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_type',
            'analysis_from', 'analysis_to', 'computed_at',
            # Metrics
            'total_periods', 'nonzero_periods', 'total_qty',
            'adi', 'cv2', 'zero_rate',
            # Classification
            'demand_class', 'recommended_strategy',
            # Planner-editable
            'override_strategy', 'override_note',
            # Computed property
            'effective_strategy',
        ]
        read_only_fields = [
            'item_id', 'item_name', 'location_code', 'customer_code',
            'period_type', 'analysis_from', 'analysis_to', 'computed_at',
            'total_periods', 'nonzero_periods', 'total_qty',
            'adi', 'cv2', 'zero_rate',
            'demand_class', 'recommended_strategy', 'effective_strategy',
        ]
        # override_strategy and override_note are writable
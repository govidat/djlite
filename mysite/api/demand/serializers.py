# `mysite/api/demand/serializers.py`

from rest_framework import serializers
from mysite.models.demand.hierarchy import (
    PlanningLocation, SalesNode, CustomerSalesAssignment, PlanningCustomer,
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
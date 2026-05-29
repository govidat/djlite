# mysite/tests/demand/test_hierarchy_api.py

"""
# Run all demand tests
pytest mysite/tests/demand/ -v

# Run only import tests
pytest mysite/tests/demand/test_actuals_import.py -v

# Run with coverage
pytest mysite/tests/demand/ --cov=mysite.models.demand --cov=mysite.tasks.demand --cov-report=term-missing
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from mysite.models.demand.hierarchy import SalesNode, CustomerSalesAssignment, PlanningLocation
import datetime


@pytest.mark.django_db
class TestPlanningLocationHierarchyAPI:

    def setup_method(self):
        self.api = APIClient()

    def test_returns_nested_tree(self, client_obj, root_location, leaf_location, django_user_model):
        user = django_user_model.objects.create_user('testuser', password='pw')
        self.api.force_authenticate(user=user)
        # Attach client to request (simulate your middleware)
        self.api.credentials(HTTP_X_CLIENT_ID=client_obj.client_id)

        url = reverse('demand-location-hierarchy')
        response = self.api.get(url)

        assert response.status_code == 200
        data = response.json()
        # Root node should appear at top level
        assert len(data) == 1
        root = data[0]
        assert root['code'] == 'ROOT'
        assert root['depth'] == 0
        # Child node nested inside
        assert len(root['children']) == 1
        child = root['children'][0]
        assert child['code'] == 'LEAF-01'
        assert child['is_leaf'] is True
        assert child['depth'] == 1

    def test_leaves_only_param_returns_flat_list(
        self, client_obj, root_location, leaf_location, django_user_model
    ):
        user = django_user_model.objects.create_user('user2', password='pw')
        self.api.force_authenticate(user=user)

        url = reverse('demand-location-hierarchy')
        response = self.api.get(url, {'leaves_only': 'true'})

        assert response.status_code == 200
        data = response.json()
        # Only leaf nodes returned, flat list
        codes = [n['code'] for n in data]
        assert 'LEAF-01' in codes
        assert 'ROOT' not in codes


@pytest.mark.django_db
class TestPathMaterialization:
    """Sprint 3B.1 unit tests: path computed correctly."""

    def test_root_node_path(self, client_obj):
        node = PlanningLocation.objects.create(
            client=client_obj, code='R', name='Root', is_leaf=False
        )
        node.refresh_from_db()
        assert node.path == f'{node.pk}/'

    def test_child_node_path(self, client_obj, root_location):
        child = PlanningLocation.objects.create(
            client=client_obj, code='C', name='Child',
            parent=root_location, is_leaf=True
        )
        child.refresh_from_db()
        assert child.path == f'{root_location.pk}/{child.pk}/'

    def test_reparent_updates_path(self, client_obj, root_location):
        """Moving a node to a new parent must recompute path."""
        other_root = PlanningLocation.objects.create(
            client=client_obj, code='R2', name='Other Root', is_leaf=False
        )
        child = PlanningLocation.objects.create(
            client=client_obj, code='C2', name='Child',
            parent=root_location, is_leaf=True
        )
        child.refresh_from_db()
        original_path = child.path

        # Reparent
        child.parent = other_root
        child.save()
        child.refresh_from_db()

        assert child.path != original_path
        assert child.path == f'{other_root.pk}/{child.pk}/'

    def test_subtree_query_via_path_startswith(self, client_obj, root_location, leaf_location):
        """path__startswith must return all descendants."""
        root_location.refresh_from_db()
        descendants = PlanningLocation.objects.filter(
            path__startswith=root_location.path
        ).exclude(pk=root_location.pk)
        assert leaf_location in descendants

    def test_grandchild_path(self, client_obj, root_location, leaf_location):
        grandchild = PlanningLocation.objects.create(
            client=client_obj, code='GC', name='Grandchild',
            parent=leaf_location, is_leaf=True
        )
        grandchild.refresh_from_db()
        assert grandchild.path == (
            f'{root_location.pk}/{leaf_location.pk}/{grandchild.pk}/'
        )


@pytest.mark.django_db
class TestCustomerSalesAssignment:

    def test_date_effectivity_no_overlap_allowed(
        self, client_obj, planning_customer
    ):
        """Two open assignments for the same customer must be rejected."""
        from django.core.exceptions import ValidationError

        sales_root = SalesNode.objects.create(
            client=client_obj, code='NSM', name='National'
        )
        sales_leaf = SalesNode.objects.create(
            client=client_obj, code='REP-01', name='Rep 1',
            parent=sales_root
        )

        # First assignment — open-ended
        a1 = CustomerSalesAssignment(
            planning_customer=planning_customer,
            sales_node=sales_leaf,
            valid_from=datetime.date(2024, 1, 1),
            valid_to=None,
        )
        a1.full_clean()
        a1.save()

        # Second overlapping assignment — should be rejected
        a2 = CustomerSalesAssignment(
            planning_customer=planning_customer,
            sales_node=sales_leaf,
            valid_from=datetime.date(2024, 6, 1),
            valid_to=None,
        )
        # Your clean() method or a DB constraint should raise here.
        # If you haven't added overlap validation to clean() yet, add it:
        #
        #   def clean(self):
        #       overlapping = CustomerSalesAssignment.objects.filter(
        #           planning_customer=self.planning_customer,
        #           valid_to__isnull=True,
        #       ).exclude(pk=self.pk)
        #       if overlapping.exists():
        #           raise ValidationError(
        #               "Customer already has an open assignment. "
        #               "Close the existing one before creating a new one."
        #           )
        with pytest.raises(ValidationError):
            a2.full_clean()


# **Action required:** Add the overlap check to `CustomerSalesAssignment.clean()` as shown in the comment above — the test verifies it.
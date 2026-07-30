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
from mysite.models.demand.hierarchy import SalesNode, PlanningLocation
import datetime


@pytest.mark.django_db
class TestPlanningLocationHierarchyAPI:

    #def setup_method(self):
    #    self.api = APIClient()
    def test_returns_nested_tree(
        self,
        api_client,
        root_location,
        leaf_location,
    ):
        client, user = api_client
        url = reverse("demand-location-hierarchy")
        response = client.get(url)
    #def test_returns_nested_tree(self, client_obj, root_location, leaf_location, django_user_model):
        
        #user = django_user_model.objects.create_user('testuser', password='pw')
        #self.api.force_authenticate(user=user)
        # Attach client to request (simulate your middleware)
        #self.api.credentials(HTTP_X_CLIENT_ID=client_obj.client_id)

        #url = reverse('demand-location-hierarchy')
        #response = self.api.get(url)

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
        self,
        api_client,
        root_location,
        leaf_location,
    ):
        client, user = api_client
        url = reverse("demand-location-hierarchy")
        response = client.get(
            url,
            {"leaves_only": "true"}
        )

    #def test_leaves_only_param_returns_flat_list(
    #    self, client_obj, root_location, leaf_location, django_user_model
    #):
        #user = django_user_model.objects.create_user('user2', password='pw')
        #self.api.force_authenticate(user=user)

        #url = reverse('demand-location-hierarchy')
        #response = self.api.get(url, {'leaves_only': 'true'})

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
class TestSalesForecastLinkAPI:

    def test_create_shape_c_link(self, api_client, leaf_location, sales_leaf):
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
            'valid_from': '2024-01-01',
        })
        assert response.status_code == 201
        data = response.json()
        assert data['link_type'] == 'c'
        assert data['location_code'] == 'LEAF-01'
        assert data['channel_code'] is None
        assert data['customer_code'] is None
        assert data['is_active'] is True

    def test_create_defaults_valid_from_to_today(self, api_client, leaf_location, sales_leaf):
        """valid_from is optional in the request — the view defaults it to today."""
        import datetime
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
        })
        assert response.status_code == 201
        assert response.json()['valid_from'] == datetime.date.today().isoformat()

    def test_create_shape_a_link(
        self, api_client, leaf_location, sales_leaf,
        distribution_channel_common, planning_customer,
    ):
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
            'distribution_channel': distribution_channel_common.pk,
            'planning_customer': planning_customer.pk,
            'valid_from': '2024-01-01',
        })
        assert response.status_code == 201
        data = response.json()
        assert data['link_type'] == 'a'
        assert data['customer_code'] == 'CUST-01'
        assert data['channel_code'] == '00'

    def test_customer_without_channel_rejected(
        self, api_client, leaf_location, sales_leaf, planning_customer,
    ):
        """Shape must be a (loc+dc+cust), b (loc+dc), or c (loc) —
        loc+cust with no channel isn't a valid shape."""
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
            'planning_customer': planning_customer.pk,
            'valid_from': '2024-01-01',
        })
        assert response.status_code == 400

    def test_non_leaf_location_rejected(self, api_client, root_location, sales_leaf):
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': root_location.pk,
            'sales_node': sales_leaf.pk,
            'valid_from': '2024-01-01',
        })
        assert response.status_code == 400

    def test_non_leaf_sales_node_rejected(self, api_client, leaf_location, sales_root, sales_leaf):
        """sales_leaf is a child of sales_root, so sales_root is not a leaf."""
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_root.pk,
            'valid_from': '2024-01-01',
        })
        assert response.status_code == 400

    def test_valid_to_before_valid_from_rejected(self, api_client, leaf_location, sales_leaf):
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
            'valid_from': '2024-06-01',
            'valid_to': '2024-01-01',
        })
        assert response.status_code == 400

    def test_overlapping_open_link_rejected(self, api_client, sales_forecast_link_shape_c,
                                             leaf_location, sales_leaf):
        """Ported from the old CustomerSalesAssignment overlap test: two
        open (valid_to=NULL) rows for the same key must be rejected."""
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.post(url, {
            'planning_location': leaf_location.pk,
            'sales_node': sales_leaf.pk,
            'valid_from': '2024-06-01',   # overlaps the fixture's open row starting 2024-01-01
        })
        assert response.status_code == 400

    def test_list_filters_by_link_type(
        self, api_client, sales_forecast_link_shape_c, sales_forecast_link_shape_a,
    ):
        client, user = api_client
        url = reverse('demand-sales-forecast-links')
        response = client.get(url, {'link_type': 'a'})
        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1
        assert data['results'][0]['link_type'] == 'a'

    def test_delete_closes_active_link(self, api_client, sales_forecast_link_shape_c):
        """DELETE on an active link closes it (sets valid_to=today) rather
        than hard-deleting, to preserve history."""
        import datetime
        client, user = api_client
        url = reverse('demand-sales-forecast-link-detail', args=[sales_forecast_link_shape_c.pk])
        response = client.delete(url)
        assert response.status_code == 200
        assert response.json()['valid_to'] == datetime.date.today().isoformat()

        sales_forecast_link_shape_c.refresh_from_db()
        assert sales_forecast_link_shape_c.valid_to == datetime.date.today()

    def test_delete_hard_deletes_never_active_link(self, api_client, leaf_location, sales_leaf):
        """A link whose valid_from is in the future has no history to
        preserve — DELETE removes it outright."""
        import datetime
        from mysite.models.demand.hierarchy import SalesForecastLink

        future_link = SalesForecastLink.objects.create(
            client=leaf_location.client, planning_location=leaf_location, sales_node=sales_leaf,
            valid_from=datetime.date.today() + datetime.timedelta(days=30),
        )
        client, user = api_client
        url = reverse('demand-sales-forecast-link-detail', args=[future_link.pk])
        response = client.delete(url)
        assert response.status_code == 204
        assert not SalesForecastLink.objects.filter(pk=future_link.pk).exists()

    def test_sales_hierarchy_includes_forecast_links(
        self, api_client, sales_root, sales_leaf, sales_forecast_link_shape_c,
    ):
        client, user = api_client
        url = reverse('demand-sales-hierarchy')
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        root = data[0]
        leaf = root['children'][0]
        assert len(leaf['forecast_links']) == 1
        assert leaf['forecast_links'][0]['location_code'] == 'LEAF-01'
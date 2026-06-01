# mysite/tests/demand/conftest.py  (or in each test file's setUp)

import pytest
import datetime
from mysite.models import Client, Item
from mysite.models.demand.hierarchy import (
    PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
)
from mysite.models.demand.actuals import ActualSale, ActualSaleImport


@pytest.fixture
def client_obj(db):
    return Client.objects.create(client_id='test-client', name='Test Client')


@pytest.fixture
def root_location(db, client_obj):
    return PlanningLocation.objects.create(
        client=client_obj, code='ROOT', name='Root', is_leaf=False
    )


@pytest.fixture
def leaf_location(db, client_obj, root_location):
    return PlanningLocation.objects.create(
        client=client_obj, code='LEAF-01', name='Leaf Branch',
        parent=root_location, is_leaf=True
    )


@pytest.fixture
def active_item(db, client_obj):
    return Item.objects.create(
        client=client_obj, item_id='ITEM-001',
        name='Test Item', status='active'
    )


@pytest.fixture
def planning_customer(db, client_obj):
    return PlanningCustomer.objects.create(
        client=client_obj, code='CUST-001', name='Test Customer'
    )
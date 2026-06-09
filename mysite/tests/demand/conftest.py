# mysite/tests/demand/conftest.py  (or in each test file's setUp)

# ── Do NOT import models at the top level ────────────────────────────────────
# Models must only be imported inside fixtures (after Django is set up)
# or inside test functions.
"""
from mysite.models import Client, Item
from mysite.models.demand.hierarchy import (
    PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
)
from mysite.models.demand.actuals import ActualSale, ActualSaleImport

3 tests pass now. The single remaining error is clear: UNIQUE constraint failed: auth_user.username because the draft_version fixture creates a user with username='planner' on every test, but the api_client fixture also creates a user with username='planner'. They collide.
The fix is to use get_or_create in draft_version so it reuses the user that api_client already created, and to make the usernames distinct across fixtures:

The problem is clear now. The planner_user fixture has function scope (the default), so it runs once per test — but something else is already creating a user with username='planner' before it runs. Looking at the error, it fires in conftest.py:76 which is the planner_user fixture itself, meaning another fixture or the TestApplyOverridesTask tests (which pass and create their own user internally) are leaving state behind.
The root cause: TestApplyOverridesTask tests use django_user_model.objects.get(username='planner') internally in the test file, which means those tests create a planner user that persists into the next test class's setup — because the database isn't being rolled back between classes.
The fix is to use get_or_create in the planner_user fixture instead of create_user:
"""

# mysite/tests/demand/conftest.py
# mysite/tests/demand/conftest.py

import datetime
import pytest
from decimal import Decimal


@pytest.fixture(autouse=True)
def celery_eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def client_obj(db):
    from mysite.models import Client
    return Client.objects.create(
        client_id='TEST01',
        name='Test Client',
    )


@pytest.fixture
def active_item(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(
        client=client_obj,
        item_id='item-001',
        name='Brake Pad',
        status='active',
    )


@pytest.fixture
def root_location(db, client_obj):
    from mysite.models.demand.hierarchy import PlanningLocation
    return PlanningLocation.objects.create(
        client=client_obj,
        code='ROOT',
        name='Root',
        is_leaf=False,
    )

@pytest.fixture
def leaf_location(db, client_obj, root_location):
    from mysite.models.demand.hierarchy import PlanningLocation

    leaf = PlanningLocation.objects.create(
        client=client_obj,
        parent=root_location,
        code='LEAF-01',
        name='Mumbai Warehouse',
        is_leaf=True,
    )

    leaf.refresh_from_db()

    return leaf
"""
@pytest.fixture
def leaf_location(db, client_obj):
    from mysite.models.demand.hierarchy import PlanningLocation
    return PlanningLocation.objects.create(
        client=client_obj,
        code='LEAF-01',
        name='Mumbai Warehouse',
    )
"""

@pytest.fixture
def planning_customer(db, client_obj):
    from mysite.models.demand.hierarchy import PlanningCustomer
    return PlanningCustomer.objects.create(
        client=client_obj,
        code='CUST-01',
        name='Test Customer',
    )


@pytest.fixture
def planner_user(db, django_user_model):
    user, _ = django_user_model.objects.get_or_create(
        username='planner',
        defaults={'email': 'planner@example.com'},
    )
    return user

@pytest.fixture
def api_client(db, planner_user, client_obj, settings):
    from rest_framework.test import APIClient
    import mysite.api.demand.views as demand_views
    from django.shortcuts import get_object_or_404 as _real_404
    from mysite.models.demand.forecast import ForecastVersion as _FV

    # Swap middleware
    settings.MIDDLEWARE = [
        'mysite.tests.demand.test_utils.TestClientMiddleware'
        if 'CustomerProfileMiddleware' in m else m
        for m in settings.MIDDLEWARE
    ]

    _client_obj = client_obj

    # Patch get_object_or_404 at module level (covers direct calls in views)
    def _patched_404(klass, *args, **kwargs):
        if 'client' in kwargs and kwargs['client'] is None:
            kwargs['client'] = _client_obj
        return _real_404(klass, *args, **kwargs)

    demand_views.get_object_or_404 = _patched_404

    # Patch _get_draft_version directly (covers override views)
    _original_get_draft = demand_views._get_draft_version

    def _patched_get_draft(request, pk):
        return _real_404(_FV, pk=pk, client=_client_obj)

    demand_views._get_draft_version = _patched_get_draft

    # InjectingAPIClient injects _TEST_CLIENT_OBJ into META
    class InjectingAPIClient(APIClient):
        def request(self, **kwargs):
            kwargs['_TEST_CLIENT_OBJ'] = _client_obj
            return super().request(**kwargs)

    test_client = InjectingAPIClient()
    test_client.force_authenticate(user=planner_user)

    yield test_client, planner_user

    # Restore originals
    demand_views._get_draft_version = _original_get_draft
    demand_views.get_object_or_404 = _real_404

@pytest.fixture
def draft_version(db, client_obj, planner_user):
    from mysite.models.demand.forecast import ForecastVersion
    return ForecastVersion.objects.create(
        client=client_obj,
        version_label='Jan-2025 Monthly v1',
        period_type='month',
        base_period_end=datetime.date(2024, 12, 31),
        horizon_periods=6,
        status=ForecastVersion.Status.DRAFT,
        created_by=planner_user,
    )


@pytest.fixture
def draft_version_with_lines(db, draft_version, active_item, leaf_location):
    from mysite.models.demand.forecast import ForecastLine

    periods = [
        (datetime.date(2025, 1, 1), datetime.date(2025, 1, 31)),
        (datetime.date(2025, 2, 1), datetime.date(2025, 2, 28)),
    ]
    lines = []
    for ps, pe in periods:
        line = ForecastLine.objects.create(
            version           = draft_version,
            item              = active_item,
            planning_location = leaf_location,
            planning_customer = None,
            period_type       = 'month',
            period_start      = ps,
            period_end        = pe,
            statistical_qty   = Decimal('100.000'),
            final_qty         = Decimal('100.000'),
            price_used        = Decimal('150.00'),
            statistical_value = Decimal('15000.00'),
            final_value       = Decimal('15000.00'),
            model_used        = 'AutoETS',
            forecast_level    = 'item_cust_location',
        )
        lines.append(line)
    return draft_version, lines[0], lines[1]

@pytest.fixture
def series_profile(db, client_obj, active_item, leaf_location, planning_customer):
    from mysite.models.demand.forecast import SeriesProfile
    import datetime
    return SeriesProfile.objects.create(
        client            = client_obj,
        item              = active_item,
        planning_location = leaf_location,
        planning_customer = planning_customer,
        period_type       = 'month',
        analysis_from     = datetime.date(2023, 1, 1),
        analysis_to       = datetime.date(2024, 12, 31),
        total_periods     = 24,
        nonzero_periods   = 20,
        total_qty         = Decimal('2400.000'),
        zero_rate         = Decimal('0.1667'),
        demand_class_atomic = 'SMOOTH',
        abc_class_atomic    = 'A',
        chosen_grain      = 'item_cust_location',
        chosen_strategy   = 'AUTOETS',
        chosen_eval_period = 'month',
    )
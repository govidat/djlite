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

# mysite/tests/demand/conftest.py

# mysite/tests/demand/conftest.py

import datetime
import pytest
from decimal import Decimal

@pytest.fixture(autouse=True)
def celery_eager(settings):
    """Force all Celery tasks to run synchronously during tests."""
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
        item_id='ITEM-001',
        name='Brake Pad',
        status='active',
    )


@pytest.fixture
def leaf_location(db, client_obj):
    from mysite.models.demand.hierarchy import PlanningLocation
    return PlanningLocation.objects.create(
        client=client_obj,
        code='LEAF-01',
        name='Mumbai Warehouse',
    )


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
def api_client(db, planner_user, client_obj):
    """
    Authenticated APIClient with request.client injected via
    monkeypatching _get_draft_version — the function all override
    views use to resolve the version from request.client.
    """
    from rest_framework.test import APIClient

    test_client = APIClient()
    test_client.force_authenticate(user=planner_user)
    return test_client, planner_user


@pytest.fixture(autouse=True)
def inject_request_client(monkeypatch, client_obj):
    """
    Patches _get_draft_version in the views module so that
    request.client is always set to client_obj during tests.
    This avoids the middleware entirely.
    """
    import mysite.api.demand.views as demand_views
    from django.shortcuts import get_object_or_404
    from mysite.models.demand.forecast import ForecastVersion

    _client_obj = client_obj

    def patched_get_draft_version(request, pk):
        # Inject client onto the request object directly
        request.client = _client_obj
        return get_object_or_404(ForecastVersion, pk=pk, client=_client_obj)

    monkeypatch.setattr(
        demand_views,
        '_get_draft_version',
        patched_get_draft_version,
    )

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
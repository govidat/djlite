# mysite/tests/demand/test_accuracy_run.py

"""
# Run only these tests
pytest mysite/tests/demand/test_accuracy_run.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest

from mysite.models.demand.actuals import (
    ActualSale, ActualSaleOutlierAdjustment, ItemPlanningProfile,
)
from mysite.models.demand.forecast import (
    ForecastAccuracy, ForecastLine, ForecastVersion, ForecastingConfig,
)
from mysite.tasks.demand.run_forecast import compute_accuracy


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def approved_version(db, client_obj, planner_user, active_item,
                     leaf_location, distribution_channel_common):
    version = ForecastVersion.objects.create(
        client=client_obj,
        version_label='Feb-2025 Monthly v2',
        period_type='month',
        base_period_end=datetime.date(2025, 1, 31),
        horizon_periods=2,
        status=ForecastVersion.Status.APPROVED,
        created_by=planner_user,
    )
    line = ForecastLine.objects.create(
        version=version,
        item=active_item,
        planning_location=leaf_location,
        planning_customer=None,
        distribution_channel=distribution_channel_common,
        period_type='month',
        period_start=datetime.date(2025, 2, 1),
        period_end=datetime.date(2025, 2, 28),
        statistical_qty=Decimal('100.000'),
        final_qty=Decimal('100.000'),
        price_used=Decimal('150.00'),
        statistical_value=Decimal('15000.00'),
        final_value=Decimal('15000.00'),
        model_used='AutoETS',
        forecast_level='item_cust_location',
    )
    return version, line


def _add_line(version, period_start):
    return ForecastLine.objects.create(
        version=version,
        item=ForecastLine.objects.filter(version=version).first().item,
        planning_location=ForecastLine.objects.filter(version=version).first().planning_location,
        planning_customer=None,
        distribution_channel=ForecastLine.objects.filter(version=version).first().distribution_channel,
        period_type='month',
        period_start=period_start,
        period_end=period_start.replace(day=28) if period_start.month != 2 else period_start.replace(day=28),
        statistical_qty=Decimal('100.000'),
        final_qty=Decimal('100.000'),
        price_used=Decimal('150.00'),
        statistical_value=Decimal('15000.00'),
        final_value=Decimal('15000.00'),
        model_used='AutoETS',
        forecast_level='item_cust_location',
    )


@pytest.fixture
def matching_actual(db, client_obj, leaf_location, active_item,
                    distribution_channel_common):
    def _make(qty, revenue, period_start=datetime.date(2025, 2, 1)):
        return ActualSale.objects.create(
            client=client_obj,
            planning_location=leaf_location,
            item=active_item,
            planning_customer=None,
            distribution_channel=distribution_channel_common,
            period_type='month',
            period_start=period_start,
            qty=qty,
            revenue=revenue,
        )
    return _make


def _run(version):
    """Run the task synchronously and re-read the version."""
    compute_accuracy.run(version.client.pk, version.pk)
    version.refresh_from_db()
    return version


# ─────────────────────────────────────────────────────────────────────────────
# compute_accuracy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestComputeAccuracy:

    def test_grades_and_persists_weighted_stats(self, approved_version, matching_actual):
        version, line = approved_version
        _add_line(version, datetime.date(2025, 3, 1))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'),
                        period_start=datetime.date(2025, 3, 1))

        _run(version)

        rows = list(ForecastAccuracy.objects.filter(version=version))
        assert len(rows) == 2
        for r in rows:
            assert r.actual_qty == Decimal('80.000')
            assert r.forecast_qty == Decimal('100.000')
            assert r.actual_value == Decimal('8000.00')
            assert r.forecast_value == Decimal('15000.00')
            assert r.mape == Decimal('25.0000')
            assert r.bias == Decimal('25.0000')

        assert version.accuracy_run_status == ForecastVersion.AccuracyRunStatus.COMPLETE
        assert version.accuracy_run_error == ''
        assert version.last_accuracy_run_at is not None
        assert version.last_accuracy_rows == 2
        assert version.last_accuracy_wmape == Decimal('25.00')
        assert version.last_accuracy_wbias == Decimal('25.00')
        assert version.last_accuracy_value_mape == Decimal('87.50')

    def test_run_is_idempotent_over_rows(self, approved_version, matching_actual):
        version, _ = approved_version
        _add_line(version, datetime.date(2025, 3, 1))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'),
                        period_start=datetime.date(2025, 3, 1))

        _run(version)
        _run(version)

        assert ForecastAccuracy.objects.filter(version=version).count() == 2

    def test_failure_leaves_run_at_unset_and_marks_failed(self, approved_version):
        """No actuals → task raises → FAILED, last_accuracy_run_at untouched."""
        version, _ = approved_version
        _run(version)

        assert version.accuracy_run_status == ForecastVersion.AccuracyRunStatus.FAILED
        assert version.last_accuracy_run_at is None
        assert 'No actuals' in version.accuracy_run_error


@pytest.mark.django_db
class TestComputeAccuracyNetActuals:

    def test_net_on_subtracts_confirmed_outliers(self, approved_version, matching_actual):
        version, _ = approved_version
        _add_line(version, datetime.date(2025, 3, 1))
        adjusted = matching_actual(qty=Decimal('500.000'), revenue=Decimal('5000.00'))
        other = matching_actual(qty=Decimal('500.000'), revenue=Decimal('5000.00'),
                                period_start=datetime.date(2025, 3, 1))
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=adjusted, qty_adjustment=Decimal('100.000'),
            revenue_adjustment=Decimal('900.00'),
            detected_by='SYSTEM', status='CONFIRMED',
        )

        _run(version)

        rows = {r.period_start: r for r in ForecastAccuracy.objects.filter(version=version)}
        assert rows[datetime.date(2025, 2, 1)].actual_qty == Decimal('400.000')
        assert rows[datetime.date(2025, 2, 1)].actual_value == Decimal('4100.00')
        assert rows[datetime.date(2025, 3, 1)].actual_qty == Decimal('500.000')

    def test_net_off_uses_raw_qty_and_revenue(self, approved_version, matching_actual,
                                              client_obj):
        config, _ = ForecastingConfig.objects.get_or_create(client=client_obj)
        config.reporting_uses_net_actuals = False
        config.save(update_fields=['reporting_uses_net_actuals'])

        version, _ = approved_version
        sale = matching_actual(qty=Decimal('500.000'), revenue=Decimal('5000.00'))
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=sale, qty_adjustment=Decimal('100.000'),
            revenue_adjustment=Decimal('900.00'),
            detected_by='SYSTEM', status='CONFIRMED',
        )

        _run(version)

        row = ForecastAccuracy.objects.filter(version=version).get()
        assert row.actual_qty == Decimal('500.000')
        assert row.actual_value == Decimal('5000.00')


@pytest.mark.django_db
class TestComputeAccuracyValueFallback:

    def test_fallback_to_price_used_when_revenue_missing(self, approved_version, matching_actual):
        version, line = approved_version
        line.final_value = None
        line.save(update_fields=['final_value'])
        matching_actual(qty=Decimal('80.000'), revenue=None)

        _run(version)

        row = ForecastAccuracy.objects.filter(version=version).get()
        assert row.actual_value == Decimal('12000.00')   # 80 × 150
        assert row.forecast_value == Decimal('15000.00')  # 100 × 150

    def test_fallback_to_standard_price_when_price_used_missing(self, approved_version,
                                                                matching_actual, client_obj,
                                                                active_item):
        version, line = approved_version
        line.price_used = None
        line.final_value = None
        line.save(update_fields=['price_used', 'final_value'])
        ItemPlanningProfile.objects.create(
            client=client_obj, item=active_item, standard_price=Decimal('200.00'),
        )
        matching_actual(qty=Decimal('80.000'), revenue=None)

        _run(version)

        row = ForecastAccuracy.objects.filter(version=version).get()
        assert row.actual_value == Decimal('16000.00')   # 80 × 200
        assert row.forecast_value == Decimal('20000.00')  # 100 × 200

    def test_value_drops_when_no_price_anywhere(self, approved_version, matching_actual):
        version, line = approved_version
        line.price_used = None
        line.final_value = None
        line.save(update_fields=['price_used', 'final_value'])
        matching_actual(qty=Decimal('80.000'), revenue=None)

        _run(version)

        row = ForecastAccuracy.objects.filter(version=version).get()
        assert row.actual_value is None
        assert row.forecast_value is None
        assert row.actual_qty == Decimal('80.000')
        assert row.forecast_qty == Decimal('100.000')


# ─────────────────────────────────────────────────────────────────────────────
# accuracy_button_state
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccuracyButtonState:

    def test_viewer_role_denied(self, approved_version):
        version, _ = approved_version
        assert version.accuracy_button_state('viewer')[0] is False

    def test_draft_status_denied(self, draft_version):
        assert draft_version.accuracy_button_state('planner')[0] is False

    def test_approved_no_actuals_denied(self, approved_version):
        version, _ = approved_version
        assert version.accuracy_button_state('planner')[0] is False

    def test_approved_with_actuals_enabled(self, approved_version, matching_actual):
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        assert version.accuracy_button_state('planner')[0] is True
        assert version.accuracy_button_state('admin')[0] is True

    def test_up_to_date_denied_until_actuals_change(self, approved_version, matching_actual):
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        enabled, reason = version.accuracy_button_state('planner')
        assert enabled is False
        assert 'up to date' in reason

        sale = ActualSale.objects.filter(client=version.client).first()
        sale.qty = Decimal('90.000')
        sale.save(update_fields=['qty'])

        assert version.accuracy_button_state('planner')[0] is True

    def test_confirming_outlier_makes_run_stale(self, approved_version, matching_actual):
        version, _ = approved_version
        sale = matching_actual(qty=Decimal('500.000'), revenue=Decimal('5000.00'))
        _run(version)
        assert version.accuracy_button_state('planner')[0] is False

        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=sale, qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        assert version.accuracy_button_state('planner')[0] is True

    def test_failed_run_stays_enabled_for_retry(self, approved_version, matching_actual):
        """A FAILED attempt with actuals available is retry-able: it never
        advanced last_accuracy_run_at, and the actuals cover the periods."""
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        version.accuracy_run_status = ForecastVersion.AccuracyRunStatus.FAILED
        version.accuracy_run_error = 'boom'
        version.save(update_fields=['accuracy_run_status', 'accuracy_run_error'])
        version.refresh_from_db()

        assert version.last_accuracy_run_at is None
        assert version.accuracy_button_state('planner')[0] is True


# ─────────────────────────────────────────────────────────────────────────────
# UI smoke: version list + accuracy page render with the HTMX partials
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccuracyViews:

    def _client(self):
        from django.contrib.auth import get_user_model
        from django.test import Client
        admin = get_user_model().objects.create_superuser(
            username='acc-admin', email='acc@example.com', password='x',
        )
        c = Client()
        c.force_login(admin)
        return c, admin

    def test_accuracy_page_renders(self, approved_version, matching_actual):
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        c, _ = self._client()
        resp = c.get(f"/{version.client.client_id}/demand/versions/{version.pk}/accuracy/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Forecast Accuracy' in body
        assert 'Weighted MAPE' in body
        assert '25.0' in body              # WMAPE stat card
        assert 'Location drill-down' in body
        assert 'Taxonomy drill-down' in body

    def test_accuracy_page_disallows_anonymous(self, approved_version):
        from django.test import Client
        version, _ = approved_version
        c = Client()
        resp = c.get(f"/{version.client.client_id}/demand/versions/{version.pk}/accuracy/")
        assert resp.status_code in (302, 403)

    def test_version_list_offers_run_button_when_stale(self, approved_version, matching_actual):
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))

        c, _ = self._client()
        resp = c.get(f"/{version.client.client_id}/demand/versions/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Run Accuracy' in body       # enabled → button rendered

    def test_version_list_shows_complete_without_button(self, approved_version, matching_actual):
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        c, _ = self._client()
        resp = c.get(f"/{version.client.client_id}/demand/versions/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Run Accuracy' not in body    # up to date → no trigger
        assert 'WMAPE' in body


# ─────────────────────────────────────────────────────────────────────────────
# API: weighted accuracy view + hierarchy drill endpoints
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccuracyApi:

    def test_accuracy_api_returns_weighted_overall(self, api_client, approved_version,
                                                   matching_actual):
        client, _ = api_client
        version, _ = approved_version
        _add_line(version, datetime.date(2025, 3, 1))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'),
                        period_start=datetime.date(2025, 3, 1))
        _run(version)

        resp = client.get(
            f"/api/{version.client.client_id}/demand/forecast-versions/{version.pk}/accuracy/"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['count'] == 1          # one category group
        overall = data['overall']
        assert overall['record_count'] == 2
        assert overall['graded_count'] == 2
        assert overall['wmape'] == '25.00'
        assert overall['wbias'] == '25.00'
        assert overall['value_mape'] == '87.50'
        assert overall['graded_count'] == 2

    def test_accuracy_api_groups_by_location(self, api_client, approved_version,
                                             matching_actual):
        client, _ = api_client
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        resp = client.get(
            f"/api/{version.client.client_id}/demand/forecast-versions/{version.pk}/accuracy/",
            {'group_by': 'location'},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data['results']) == 1
        assert data['results'][0]['wmape'] == '25.00'

    def test_hierarchy_locations_endpoint(self, api_client, approved_version,
                                          matching_actual):
        client, _ = api_client
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        resp = client.get(
            f"/api/{version.client.client_id}/demand/forecast-versions/{version.pk}/accuracy/hierarchy/locations/"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['level'] == 'locations'
        assert len(data['results']) >= 1
        assert data['results'][0]['wmape'] == 25.0

    def test_hierarchy_taxonomy_endpoint_empty_without_mappings(
        self, api_client, approved_version, matching_actual,
    ):
        client, _ = api_client
        version, _ = approved_version
        matching_actual(qty=Decimal('80.000'), revenue=Decimal('8000.00'))
        _run(version)

        resp = client.get(
            f"/api/{version.client.client_id}/demand/forecast-versions/{version.pk}/accuracy/hierarchy/taxonomy/"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['level'] == 'taxonomy'
        assert data['count'] == 0
        assert data['results'] == []

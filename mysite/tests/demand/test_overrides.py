# mysite/tests/demand/test_overrides.py

"""
Sprint 3B.5 unit tests — override API, disaggregation, revert.

Fixtures re-use the pytest fixtures from test_forecast.py where possible.
"""
import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastOverride, OverrideSplitWeight,
)


# ─────────────────────────────────────────────────────────────────────────────
# Test class: POST /overrides/ — create
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCreateOverride:

    def _url(self, version_id):
        return f'/api/demand/forecast-versions/{version_id}/overrides/'
    
    def test_create_qty_override_returns_202(self, api_client, draft_version_with_lines):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   120,
            'disagg_method':  'PROPORTIONAL',
        }
        resp = client.post(self._url(version.pk), payload, format='json')

        assert resp.status_code == 202
        assert ForecastOverride.objects.filter(version=version).count() == 1
        override = ForecastOverride.objects.get(version=version)
        assert override.override_qty == Decimal('120')
        assert override.override_pct is None
        assert override.override_value is None

    def test_create_pct_override(self, api_client, draft_version_with_lines):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_pct':   10.0,
            'disagg_method':  'PROPORTIONAL',
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 202
        override = ForecastOverride.objects.get(version=version)
        assert override.override_pct == Decimal('10.000')
        assert override.override_qty is None

    def test_rejects_dual_override_type(self, api_client, draft_version_with_lines):
        """Providing both override_qty and override_pct must return 400."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   100,
            'override_pct':   10.0,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 400

    def test_rejects_override_value_at_sku_level(self, api_client, draft_version_with_lines):
        """override_value at SKU level must return 400."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_value': 50000,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 400

    def test_rejects_create_on_non_draft_version(self, api_client, draft_version_with_lines):
        """Creating an override on an IN_REVIEW or LOCKED version must return 403."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        version.status = ForecastVersion.Status.IN_REVIEW
        version.save(update_fields=['status'])

        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   100,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Test class: GET /overrides/ — list
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestListOverrides:

    def test_list_returns_all_overrides_for_version(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        ForecastOverride.objects.create(
            version        = version,
            override_level = 'sku',
            override_key   = {'item_id': line_a.item.item_id},
            period_type    = 'month',
            period_start   = line_a.period_start,
            period_end     = line_a.period_end,
            override_qty   = Decimal('120'),
            disagg_method  = 'PROPORTIONAL',
            created_by     = user,
        )
        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/overrides/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['override_qty'] == '120.000'

    def test_list_filters_by_is_applied(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('120'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=True,
        )
        ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('130'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=False,
        )
        resp = client.get(
            f'/api/demand/forecast-versions/{version.pk}/overrides/?is_applied=true'
        )
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['is_applied'] is True


# ─────────────────────────────────────────────────────────────────────────────
# Test class: DELETE — applied override reverts ForecastLine
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDeleteOverride:

    def test_delete_unapplied_override_removes_row(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('999'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=False,
        )
        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 204
        assert not ForecastOverride.objects.filter(pk=override.pk).exists()
        # ForecastLine.override_qty should still be None (was never applied)
        line_a.refresh_from_db()
        assert line_a.override_qty is None

    def test_delete_applied_override_reverts_forecast_line(
        self, api_client, draft_version_with_lines, django_user_model
    ):
        """
        After an applied override is deleted, ForecastLine.override_qty must be NULL
        and final_qty must equal statistical_qty.
        """
        client, user = api_client
        version, line_a, _ = draft_version_with_lines

        # Simulate an applied override: set override_qty on the line
        line_a.override_qty = Decimal('999.000')
        line_a.final_qty    = Decimal('999.000')
        line_a.save(update_fields=['override_qty', 'final_qty'])

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('999'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=True,   # already applied
        )

        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 204

        line_a.refresh_from_db()
        # Revert: override_qty cleared
        assert line_a.override_qty is None
        # final_qty reverts to statistical_qty
        assert line_a.final_qty == Decimal('100.000')

    def test_delete_blocked_on_non_draft_version(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('100'),
            disagg_method='PROPORTIONAL', created_by=user,
        )
        version.status = ForecastVersion.Status.LOCKED
        version.save(update_fields=['status'])

        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Test class: apply_overrides Celery task (unit, no Celery worker)
# ─────────────────────────────────────────────────────────────────────────────
# In test_overrides.py — update TestApplyOverridesTask fixtures

@pytest.mark.django_db
class TestApplyOverridesTask:

    def test_qty_override_updates_forecast_line_final_qty(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('150'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('150.000')
        assert line_a.final_qty    == Decimal('150.000')

    def test_pct_override_multiplies_statistical_qty(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_pct=Decimal('10'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('110.000')
        assert line_a.final_qty    == Decimal('110.000')

    def test_delete_override_reverts_to_statistical(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override
        from mysite.api.demand.views import _revert_override_lines

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('200'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        override.is_applied = True
        override.save(update_fields=['is_applied'])

        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('200.000')

        _revert_override_lines(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty is None
        assert line_a.final_qty    == Decimal('100.000')

"""        
@pytest.mark.django_db
class TestApplyOverridesTask:

    def test_qty_override_updates_forecast_line_final_qty(
        self, draft_version_with_lines, django_user_model
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('150'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        _apply_single_override(override, version)
        line_a.refresh_from_db()

        assert line_a.override_qty == Decimal('150.000')
        assert line_a.final_qty    == Decimal('150.000')

    def test_pct_override_multiplies_statistical_qty(
        self, draft_version_with_lines, django_user_model
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_pct=Decimal('10'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        _apply_single_override(override, version)
        line_a.refresh_from_db()

        # 100 * 1.1 = 110
        assert line_a.override_qty == Decimal('110.000')
        assert line_a.final_qty    == Decimal('110.000')

    def test_delete_override_reverts_to_statistical(
        self, draft_version_with_lines, django_user_model
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override
        from mysite.api.demand.views import _revert_override_lines

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('200'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        # Apply it
        _apply_single_override(override, version)
        override.is_applied = True
        override.save(update_fields=['is_applied'])

        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('200.000')

        # Revert it
        _revert_override_lines(override, version)
        line_a.refresh_from_db()

        assert line_a.override_qty is None
        assert line_a.final_qty    == Decimal('100.000')   # back to statistical
"""

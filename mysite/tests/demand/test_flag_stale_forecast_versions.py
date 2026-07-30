# mysite/tests/demand/test_flag_stale_forecast_versions.py

"""
pytest mysite/tests/demand/test_flag_stale_forecast_versions.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta
from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.forecast import ForecastVersion
from mysite.models import ActualSaleOutlierAdjustment
from mysite.tasks.demand.detect_outliers import flag_stale_forecast_versions, _horizon_end


@pytest.mark.parametrize("period_type,horizon_periods,expected_delta_kwargs", [
    ("day", 10, {"days": 10}),
    ("week", 4, {"weeks": 4}),
    ("fortnight", 3, {"weeks": 6}),
    ("month", 6, {"months": 6}),
    ("bimonth", 2, {"months": 4}),
    ("quarter", 2, {"months": 6}),
    ("halfyear", 2, {"months": 12}),
    ("year", 1, {"years": 1}),
])
def test_horizon_end_matches_expected_for_supported_period_types(
    period_type, horizon_periods, expected_delta_kwargs,
):
    """Pure function of base_period_end + horizon_periods — no DB needed."""
    base_end = datetime.date(2024, 12, 31)
    version = ForecastVersion(
        base_period_end=base_end, horizon_periods=horizon_periods, period_type=period_type,
    )
    assert _horizon_end(version) == base_end + relativedelta(**expected_delta_kwargs)


@pytest.mark.parametrize("period_type", ["second", "minute", "hour"])
def test_horizon_end_raises_for_unsupported_sub_day_period_types(period_type):
    """base_period_end has no time component — sub-day horizons must fail
    loudly here rather than silently upgrading to a datetime and producing
    a confusing TypeError later at the comparison site."""
    version = ForecastVersion(
        base_period_end=datetime.date(2024, 12, 31), horizon_periods=1, period_type=period_type,
    )
    with pytest.raises(ValueError):
        _horizon_end(version)


@pytest.fixture
def actual_sale_factory(db, client_obj, leaf_location, active_item, planning_customer,
                        distribution_channel_common):
    def _make(period_start):
        return ActualSale.objects.create(
            client=client_obj,
            planning_location=leaf_location,
            item=active_item,
            planning_customer=planning_customer,
            distribution_channel=distribution_channel_common,
            period_type='month',
            period_start=period_start,
            qty=Decimal('500.000'),
            revenue=Decimal('5000.00'),
        )
    return _make


@pytest.mark.django_db
class TestFlagStaleForecastVersions:
    """
    draft_version fixture: base_period_end=2024-12-31, horizon_periods=6,
    period_type='month' -> horizon_end = 2025-06-30. Only actuals with
    period_start strictly after base_period_end and on/before horizon_end
    should flag the version stale.
    """

    def test_period_inside_horizon_flags_version_stale(
        self, draft_version, actual_sale_factory,
    ):
        actual = actual_sale_factory(datetime.date(2025, 3, 1))
        adj = ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual, qty_adjustment=Decimal('50.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        flag_stale_forecast_versions(actual_sale_id=actual.pk)
        draft_version.refresh_from_db()
        assert draft_version.stale_actuals is True

    def test_period_before_base_period_end_does_not_flag(
        self, draft_version, actual_sale_factory,
    ):
        """A period already covered by the version's own history shouldn't
        re-flag it — that data was already known when the version was built."""
        actual = actual_sale_factory(datetime.date(2024, 11, 1))
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual, qty_adjustment=Decimal('50.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        flag_stale_forecast_versions(actual_sale_id=actual.pk)
        draft_version.refresh_from_db()
        assert draft_version.stale_actuals is False

    def test_period_after_horizon_end_does_not_flag(
        self, draft_version, actual_sale_factory,
    ):
        actual = actual_sale_factory(datetime.date(2025, 7, 1))
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual, qty_adjustment=Decimal('50.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        flag_stale_forecast_versions(actual_sale_id=actual.pk)
        draft_version.refresh_from_db()
        assert draft_version.stale_actuals is False

    def test_non_draft_version_never_flagged(
        self, draft_version, actual_sale_factory,
    ):
        from mysite.models.demand.forecast import ForecastVersion
        draft_version.status = ForecastVersion.Status.APPROVED
        draft_version.save(update_fields=['status'])

        actual = actual_sale_factory(datetime.date(2025, 3, 1))
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual, qty_adjustment=Decimal('50.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        flag_stale_forecast_versions(actual_sale_id=actual.pk)
        draft_version.refresh_from_db()
        assert draft_version.stale_actuals is False
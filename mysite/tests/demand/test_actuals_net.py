# mysite/tests/demand/test_actuals_net.py

"""
# Run all demand tests
pytest mysite/tests/demand/ -v

# Run only these tests
pytest mysite/tests/demand/test_actuals_net.py -v --tb=short

# Run with coverage
pytest mysite/tests/demand/ --cov=mysite.models.demand --cov=mysite.tasks.demand --cov-report=term-missing
"""

import datetime
from decimal import Decimal

import pytest
from mysite.models.demand.actuals import ActualSale
from mysite.models import ActualSaleOutlierAdjustment
from utils.demand.actuals_net import actuals_queryset_with_net


@pytest.fixture
def actual_sale(db, client_obj, leaf_location, active_item, planning_customer,
                distribution_channel_common):
    return ActualSale.objects.create(
        client=client_obj,
        planning_location=leaf_location,
        item=active_item,
        planning_customer=planning_customer,
        distribution_channel=distribution_channel_common,
        period_type='month',
        period_start=datetime.date(2024, 1, 1),
        qty=Decimal('500.000'),
        revenue=Decimal('5000.00'),
    )


@pytest.mark.django_db
class TestActualsQuerysetWithNet:

    def test_no_adjustment_passthrough(self, client_obj, actual_sale):
        """A row with no outlier_adjustment at all nets to its raw values,
        regardless of use_net — the LEFT JOIN behind the Case/When simply
        finds nothing to subtract."""
        row = actuals_queryset_with_net(client_obj, use_net=True).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty
        assert row.net_revenue == actual_sale.revenue

    def test_candidate_adjustment_not_netted(self, client_obj, actual_sale):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM', status='CANDIDATE',
        )
        row = actuals_queryset_with_net(client_obj, use_net=True).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty

    def test_rejected_adjustment_not_netted(self, client_obj, actual_sale):
        """A REJECTED adjustment must behave the same as CANDIDATE for
        netting purposes — only CONFIRMED ever subtracts."""
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM', status='REJECTED',
        )
        row = actuals_queryset_with_net(client_obj, use_net=True).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty

    def test_confirmed_adjustment_netted(self, client_obj, actual_sale):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            revenue_adjustment=Decimal('900.00'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        row = actuals_queryset_with_net(client_obj, use_net=True).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty - Decimal('100.000')
        assert row.net_revenue == actual_sale.revenue - Decimal('900.00')

    def test_confirmed_adjustment_with_no_revenue_adjustment(self, client_obj, actual_sale):
        """revenue_adjustment is optional (mirrors ActualSale.revenue being
        nullable). When it's None, net_revenue must fall back to the raw
        revenue via Coalesce, not raise or come back None itself."""
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM', status='CONFIRMED',
            # revenue_adjustment intentionally omitted
        )
        row = actuals_queryset_with_net(client_obj, use_net=True).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty - Decimal('100.000')
        assert row.net_revenue == actual_sale.revenue

    def test_use_net_false_ignores_confirmed_adjustment(self, client_obj, actual_sale):
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            revenue_adjustment=Decimal('900.00'),
            detected_by='SYSTEM', status='CONFIRMED',
        )
        row = actuals_queryset_with_net(client_obj, use_net=False).get(pk=actual_sale.pk)
        assert row.net_qty == actual_sale.qty
        assert row.net_revenue == actual_sale.revenue

    def test_only_the_adjusted_row_is_netted_not_others(
        self, client_obj, actual_sale, active_item, leaf_location,
        planning_customer, distribution_channel_common,
    ):
        """Confirming an adjustment on one ActualSale row must not net any
        other row for the same client — the Case/When join is per-row, not
        client-wide."""
        other = ActualSale.objects.create(
            client=client_obj,
            planning_location=leaf_location,
            item=active_item,
            planning_customer=planning_customer,
            distribution_channel=distribution_channel_common,
            period_type='month',
            period_start=datetime.date(2024, 2, 1),
            qty=Decimal('200.000'),
            revenue=Decimal('2000.00'),
        )
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual_sale, qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM', status='CONFIRMED',
        )

        qs = actuals_queryset_with_net(client_obj, use_net=True)
        adjusted_row = qs.get(pk=actual_sale.pk)
        other_row = qs.get(pk=other.pk)

        assert adjusted_row.net_qty == actual_sale.qty - Decimal('100.000')
        assert other_row.net_qty == other.qty
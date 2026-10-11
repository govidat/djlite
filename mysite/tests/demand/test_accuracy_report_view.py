# mysite/tests/demand/test_accuracy_report_view.py

"""
# Run only these tests
pytest mysite/tests/demand/test_accuracy_report_view.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest

from mysite.models.demand.forecast import ForecastAccuracy, ForecastVersion


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def acc_view_version(db, client_obj, planner_user):
    return ForecastVersion.objects.create(
        client=client_obj,
        version_label='Accuracy Drill v1',
        period_type='month',
        base_period_end=datetime.date(2025, 1, 31),
        horizon_periods=1,
        status=ForecastVersion.Status.APPROVED,
        created_by=planner_user,
    )


def _acc(version, item, location, period_start, qty=100, fc_qty=120,
         value=1000, fc_value=1200, mape=20.0, bias=20.0):
    return ForecastAccuracy.objects.create(
        version_id=version.pk,
        item=item,
        planning_location=location,
        distribution_channel_id='00',
        period_type='month',
        period_start=period_start,
        period_end=period_start.replace(day=28),
        actual_qty=Decimal(str(qty)),
        forecast_qty=Decimal(str(fc_qty)),
        actual_value=Decimal(str(value)),
        forecast_value=Decimal(str(fc_value)),
        mape=Decimal(str(mape)),
        bias=Decimal(str(bias)),
    )


@pytest.fixture
def accuracy_item2(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(
        client=client_obj, item_code='item-002', name='Oil Filter', status='active',
    )


def _admin_client():
    from django.contrib.auth import get_user_model
    from django.test import Client
    admin = get_user_model().objects.create_superuser(
        username='acc-admin2', email='acc2@example.com', password='x',
    )
    c = Client()
    c.force_login(admin)
    return c


def _make_months(start, count):
    dates = []
    d = start
    while len(dates) < count:
        dates.append(d)
        d = d + datetime.timedelta(days=30)
    return dates


# ─────────────────────────────────────────────────────────────────────────────
# Drill header modes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDrillHeaderModes:

    def test_location_aggregate_shows_value_columns(self, acc_view_version,
                                                    client_obj, active_item,
                                                    accuracy_item2,
                                                    root_location, leaf_location,
                                                    distribution_channel_common):
        """Aggregate drill (top level, no ?items) must show value-based columns."""
        _acc(acc_view_version, active_item, leaf_location,
             datetime.date(2025, 2, 1))
        _acc(acc_view_version, accuracy_item2, leaf_location,
             datetime.date(2025, 2, 1))

        c = _admin_client()
        resp = c.get(
            f"/{client_obj.client_code}/demand/versions/{acc_view_version.pk}"
            f"/accuracy/hierarchy-locations/"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'text-right">Value MAPE %' in body
        assert 'text-right">Value Bias %' in body
        assert 'Value Actual (₹)' in body
        assert 'text-right">MAPE %' not in body   # qty MAPE hidden at aggregate

    def test_location_items_show_qty_columns(self, acc_view_version, client_obj,
                                             active_item, accuracy_item2,
                                             leaf_location,
                                             distribution_channel_common):
        """?items=1 drill must show per-item qty MAPE/Bias columns."""
        _acc(acc_view_version, active_item, leaf_location,
             datetime.date(2025, 2, 1))
        _acc(acc_view_version, accuracy_item2, leaf_location,
             datetime.date(2025, 2, 1))

        c = _admin_client()
        resp = c.get(
            f"/{client_obj.client_code}/demand/versions/{acc_view_version.pk}"
            f"/accuracy/hierarchy-locations/?location_id={leaf_location.pk}&items=1"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'text-right">MAPE %' in body
        assert 'text-right">Bias %' in body
        assert 'Value Actual (₹)' not in body    # value columns only at aggregate

    def test_taxonomy_aggregate_shows_value_columns(self, acc_view_version,
                                                    client_obj, active_item,
                                                    accuracy_item2, leaf_location,
                                                    distribution_channel_common):
        from mysite.models.catalogue import ItemTaxonomyNode, Taxonomy, TaxonomyNode
        tax = Taxonomy.objects.create(slug='gpc', taxonomy_type='gpc', name='GPC')
        segment = TaxonomyNode.objects.create(
            taxonomy=tax, slug='segment-food', name='Food', order=1,
        )  # path '001'
        ItemTaxonomyNode.objects.create(item=active_item, node=segment, is_primary=True)
        ItemTaxonomyNode.objects.create(item=accuracy_item2, node=segment, is_primary=True)

        _acc(acc_view_version, active_item, leaf_location,
             datetime.date(2025, 2, 1))
        _acc(acc_view_version, accuracy_item2, leaf_location,
             datetime.date(2025, 2, 1))

        c = _admin_client()
        resp = c.get(
            f"/{client_obj.client_code}/demand/versions/{acc_view_version.pk}"
            f"/accuracy/hierarchy-taxonomy/"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'text-right">Value MAPE %' in body
        assert 'text-right">MAPE %' not in body

        resp = c.get(
            f"/{client_obj.client_code}/demand/versions/{acc_view_version.pk}"
            f"/accuracy/hierarchy-taxonomy/?node_path=001&items=1"
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'text-right">MAPE %' in body
        assert 'text-right">Value MAPE %' not in body


# ─────────────────────────────────────────────────────────────────────────────
# Line-item table pagination
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLineItemPagination:

    def test_line_table_paginates_like_value_summary(self, acc_view_version,
                                                     client_obj, active_item,
                                                     leaf_location,
                                                     distribution_channel_common):
        """60 line rows → page 1 shows 50 with Next; page 2 shows the rest."""
        for ps in _make_months(datetime.date(2025, 1, 1), 60):
            _acc(acc_view_version, active_item, leaf_location, ps)

        c = _admin_client()
        url = (f"/{client_obj.client_code}/demand/versions/{acc_view_version.pk}"
               f"/accuracy/")

        resp = c.get(url)
        assert resp.status_code == 200
        body = resp.content.decode()
        assert '1 / 2' in body           # aggregate paginator (50 of 60 period rows)
        assert 'Next' in body
        assert body.count('font-mono text-xs">item-001') == 50   # line-table rows only

        resp = c.get(url, {'page': 2})   # flips the aggregate table only
        assert resp.status_code == 200
        body = resp.content.decode()
        assert '1 / 2' in body           # line-table paginator stays on page 1
        assert 'Previous' in body
        assert body.count('font-mono text-xs">item-001') == 50

        resp = c.get(url, {'line_page': 2})   # flips the line table only
        assert resp.status_code == 200
        body = resp.content.decode()
        assert '2 / 2' in body
        assert body.count('font-mono text-xs">item-001') == 10

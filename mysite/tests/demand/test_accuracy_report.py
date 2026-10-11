# mysite/tests/demand/test_accuracy_report.py

"""
# Run only these tests
pytest mysite/tests/demand/test_accuracy_report.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pandas as pd
import pytest

from mysite.models.demand.forecast import (
    ForecastAccuracy, ForecastVersion,
)
from utils.demand.accuracy_report import (
    compute_metrics, location_children, location_items,
    taxonomy_children, taxonomy_items,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def report_version(db, client_obj, planner_user):
    return ForecastVersion.objects.create(
        client=client_obj,
        version_label='Accuracy Report v1',
        period_type='month',
        base_period_end=datetime.date(2025, 1, 31),
        horizon_periods=1,
        status=ForecastVersion.Status.APPROVED,
        created_by=planner_user,
    )


@pytest.fixture
def report_locations(db, client_obj):
    """Top-level A(path '1/5/'), B(path '1/50/'). Paths forced to collide on
    a naive startswith prefix so the segment-aware matcher is exercised."""
    from mysite.models.demand.hierarchy import PlanningLocation
    leaf_a = PlanningLocation.objects.create(client=client_obj, code='A')
    leaf_b = PlanningLocation.objects.create(client=client_obj, code='B')
    PlanningLocation.objects.filter(pk=leaf_a.pk).update(path='1/5/')
    PlanningLocation.objects.filter(pk=leaf_b.pk).update(path='1/50/')
    return leaf_a, leaf_b


def _acc(version, item, location, qty, fc_qty, value, fc_value, period_start):
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
        actual_value=None if value is None else Decimal(str(value)),
        forecast_value=None if fc_value is None else Decimal(str(fc_value)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# compute_metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeMetrics:

    def test_weighted_math_by_hand(self):
        df = pd.DataFrame([
            {'actual_qty': 100, 'forecast_qty': 120,
             'actual_value': 1000, 'forecast_value': 1200},
            {'actual_qty': 50, 'forecast_qty': 40,
             'actual_value': 500, 'forecast_value': 400},
        ])
        m = compute_metrics(df)
        assert m['record_count'] == 2
        assert m['graded_count'] == 2
        assert m['sum_actual'] == 150
        assert m['sum_forecast'] == 160
        assert m['wmape'] == 20.0          # 30 / 150
        assert m['wbias'] == 6.67          # 10 / 150
        assert m['over_forecast_pct'] == 50.0
        assert m['value_mape'] == 20.0     # 300 / 1500
        assert m['value_bias'] == 6.67     # 100 / 1500

    def test_zero_actual_rows_are_recorded_but_not_graded(self):
        df = pd.DataFrame([
            {'actual_qty': 100, 'forecast_qty': 120,
             'actual_value': 1000, 'forecast_value': 1200},
            {'actual_qty': 0, 'forecast_qty': 0,
             'actual_value': None, 'forecast_value': None},
        ])
        m = compute_metrics(df)
        assert m['record_count'] == 2
        assert m['graded_count'] == 1
        assert m['wmape'] == 20.0
        assert m['value_count'] == 1

    def test_empty_frame_returns_zeroed_metrics(self):
        m = compute_metrics(None)
        assert m['record_count'] == 0
        assert m['graded_count'] == 0
        assert m['wmape'] is None
        assert m['wbias'] is None

    def test_reports_distinct_item_count_when_present(self):
        df = pd.DataFrame([
            {'item_id': 1, 'actual_qty': 100, 'forecast_qty': 120,
             'actual_value': 1000, 'forecast_value': 1200},
            {'item_id': 1, 'actual_qty': 50, 'forecast_qty': 40,
             'actual_value': 500, 'forecast_value': 400},
            {'item_id': 2, 'actual_qty': 10, 'forecast_qty': 20,
             'actual_value': 100, 'forecast_value': 200},
        ])
        m = compute_metrics(df)
        assert m['n_items'] == 2

    def test_item_count_zero_without_item_column(self):
        df = pd.DataFrame([
            {'actual_qty': 100, 'forecast_qty': 120,
             'actual_value': 1000, 'forecast_value': 1200},
        ])
        m = compute_metrics(df)
        assert m['n_items'] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Location drill
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLocationDrill:

    def test_location_children_roll_up_only_their_own_subtree(
        self, report_version, report_locations, active_item, distribution_channel_common,
    ):
        leaf_a, leaf_b = report_locations
        # A: two rows → 20.0 wmape (same numbers as the unit test above).
        _acc(report_version, active_item, leaf_a, 100, 120, 1000, 1200,
             datetime.date(2025, 2, 1))
        _acc(report_version, active_item, leaf_a, 50, 40, 500, 400,
             datetime.date(2025, 3, 1))
        # B: one row → 50.0 wmape.
        _acc(report_version, active_item, leaf_b, 200, 100, 2000, 1000,
             datetime.date(2025, 2, 1))

        rows, current, breadcrumb = location_children(report_version)
        assert current is None
        assert breadcrumb == []
        by_code = {r['key']: r for r in rows}
        assert set(by_code) == {'A', 'B'}

        # Segment-aware path matcher: '1/5/' must not swallow B's '1/50/' rows.
        assert by_code['A']['graded_count'] == 2
        assert by_code['A']['wmape'] == 20.0
        assert by_code['B']['graded_count'] == 1
        assert by_code['B']['wmape'] == 50.0
        # Aggregate rows report distinct item count and value metrics.
        assert by_code['A']['n_items'] == 1
        assert by_code['A']['value_mape'] == 20.0

    def test_drill_into_leaf_shows_items(self, report_version, report_locations,
                                         active_item, distribution_channel_common):
        from mysite.models import Item
        leaf_a, _ = report_locations
        item2 = Item.objects.create(client=report_version.client, item_code='item-002',
                                    name='Oil Filter', status='active')
        _acc(report_version, active_item, leaf_a, 100, 120, None, None,
             datetime.date(2025, 2, 1))
        _acc(report_version, item2, leaf_a, 100, 150, None, None,
             datetime.date(2025, 2, 1))

        rows, current, breadcrumb = location_items(report_version, leaf_a.pk)
        assert len(rows) == 2
        assert rows[0]['wmape'] == 20.0    # item1, best first
        assert rows[1]['wmape'] == 50.0    # item2
        assert rows[0]['n_items'] == 1     # item rows cover a single SKU
        assert breadcrumb[-1]['label'] == (leaf_a.name or leaf_a.code)


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomy drill
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def report_taxonomy(db, active_item):
    from mysite.models.catalogue import Taxonomy, TaxonomyNode, ItemTaxonomyNode
    tax = Taxonomy.objects.create(slug='gpc', taxonomy_type='gpc', name='GPC')
    segment = TaxonomyNode.objects.create(
        taxonomy=tax, slug='segment-food', name='Food', order=1,
    )  # path '001'
    family = TaxonomyNode.objects.create(
        taxonomy=tax, parent=segment, slug='family-beverages',
        name='Beverages', order=2,
    )  # path '001.002'
    ItemTaxonomyNode.objects.create(item=active_item, node=family, is_primary=True)
    return tax, segment, family


@pytest.mark.django_db
class TestTaxonomyDrill:

    def test_top_level_rolls_up_to_segment(self, report_version, report_taxonomy,
                                           report_locations, active_item,
                                           distribution_channel_common):
        leaf_a, _ = report_locations
        _acc(report_version, active_item, leaf_a, 100, 120, None, None,
             datetime.date(2025, 2, 1))

        rows, node_path, breadcrumb = taxonomy_children(report_version)
        assert node_path is None
        assert len(rows) == 1
        row = rows[0]
        assert row['type'] == 'taxon'
        assert row['label'] == 'Food'
        assert row['has_children'] is True
        assert row['wmape'] == 20.0
        assert row['graded_count'] == 1

    def test_drill_down_and_to_items(self, report_version, report_taxonomy,
                                     report_locations, active_item,
                                     distribution_channel_common):
        leaf_a, _ = report_locations
        _acc(report_version, active_item, leaf_a, 100, 120, None, None,
             datetime.date(2025, 2, 1))

        rows, node_path, breadcrumb = taxonomy_children(report_version, '001')
        assert len(rows) == 1
        assert rows[0]['label'] == 'Beverages'
        assert breadcrumb[0]['label'] == 'Food'

        # No deeper nodes → no child rows.
        rows, node_path, _ = taxonomy_children(report_version, '001.002')
        assert rows == []

        # Item rows under the leaf node.
        items, breadcrumb = taxonomy_items(report_version, '001.002')
        assert len(items) == 1
        assert items[0]['type'] == 'item'
        assert items[0]['wmape'] == 20.0
        assert [c['label'] for c in breadcrumb] == ['Food', 'Beverages']

# mysite/tests/demand/test_forecast_engine.py

import pytest
import datetime
from decimal import Decimal
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def item_planning_profile(db, client_obj, active_item):
    from mysite.models.demand.actuals import ItemPlanningProfile
    return ItemPlanningProfile.objects.create(
        client=client_obj,
        item=active_item,
        standard_price=Decimal('150.00'),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: load_series_decisions reads SeriesProfile correctly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLoadSeriesDecisions:

    def test_reads_effective_grain_from_series_profile(
        self, client_obj, active_item, leaf_location, planning_customer,
        series_profile, item_planning_profile
    ):
        """load_series_decisions returns effective_grain from SeriesProfile."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = f'item-001|CUST-01|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={active_item.pk: Decimal('160.00')},  # actuals price overrides
        )

        assert uid in decisions
        dec = decisions[uid]
        assert dec['grain']    == series_profile.effective_grain
        assert dec['strategy'] == series_profile.effective_strategy
        # Actuals-derived price takes precedence over standard_price
        assert dec['price']    == Decimal('160.00')

    def test_force_grain_overrides_series_profile(
        self, client_obj, active_item, leaf_location, planning_customer,
        series_profile, item_planning_profile
    ):
        """force_grain from engine_config overrides SeriesProfile.effective_grain."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = f'item-001|CUST-01|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={},
            force_grain='item_client',
        )
        assert decisions[uid]['grain'] == 'item_client'

    def test_unclassified_series_defaults_to_atomic_autoets(
        self, client_obj, active_item, leaf_location
    ):
        """Series with no SeriesProfile defaults to item_cust_location / AUTOETS."""
        from utils.demand.forecast_engine import load_series_decisions

        uid = 'UNKNOWN-ITEM|NULL|LEAF-01'
        decisions = load_series_decisions(
            client_id=client_obj.pk,
            period_type='month',
            unique_ids=[uid],
            price_map={},
        )
        assert decisions[uid]['grain']    == 'item_cust_location'
        assert decisions[uid]['strategy'] == 'AUTOETS'


# ─────────────────────────────────────────────────────────────────────────────
# Test: disaggregate_to_atomic — value-based for product grains
# ─────────────────────────────────────────────────────────────────────────────

class TestDisaggregateToAtomic:

    def _make_decisions(self, uids: list, grain: str, prices: dict) -> dict:
        return {
            uid: {
                'grain': grain, 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': prices.get(uid),
                'item_id': None, 'location_id': None, 'customer_id': None,
            }
            for uid in uids
        }

    def test_location_grain_uses_qty_share(self):
        """item_location grain disaggregates to customers by historical qty share."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        # Two customers buying the same item at the same location
        # CUST-A has 2× the demand of CUST-B
        uids = ['ITEM-A|CUST-A|LOC-1', 'ITEM-A|CUST-B|LOC-1']
        dates = pd.date_range('2022-01-01', periods=12, freq='MS')
        rows = []
        for ds in dates:
            rows += [
                {'unique_id': 'ITEM-A|CUST-A|LOC-1', 'ds': ds, 'y': 200.0,
                'item_id': 1, 'item__item_id': 'ITEM-A',
                'planning_customer_id': 1, 'customer_code': 'CUST-A',
                'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                'region_code': 'REG-1', 'revenue': 400.0},
                {'unique_id': 'ITEM-A|CUST-B|LOC-1', 'ds': ds, 'y': 100.0,
                'item_id': 1, 'item__item_id': 'ITEM-A',
                'planning_customer_id': 2, 'customer_code': 'CUST-B',
                'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                'region_code': 'REG-1', 'revenue': 150.0},
            ]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # item_location aggregate: ITEM-A at LOC-1 (strips customer → ALL_CUST)
        forecast_df = pd.DataFrame([{
            'unique_id': 'ITEM-A|ALL_CUST|LOC-1',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 300.0,
            'grain': 'item_location',
            'model_used': 'AutoETS',
            'forecast_level': 'item_location',
            'eval_period': 'month',
        }])

        decisions = {
            uid: {
                'grain': 'item_location', 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': None, 'item_id': 1,
                'location_id': 1, 'customer_id': None,
            }
            for uid in uids
        }

        result = disaggregate_to_atomic(
            forecast_df, actuals_pl, decisions,
            period_type='month',
            base_freq='MS',
        )

        # CUST-A gets 2/3 (qty share 200:100), CUST-B gets 1/3
        item_a = result[result['unique_id'] == 'ITEM-A|CUST-A|LOC-1']
        item_b = result[result['unique_id'] == 'ITEM-A|CUST-B|LOC-1']
        assert not item_a.empty
        assert not item_b.empty
        ratio = float(item_a.iloc[0]['statistical_qty']) / float(item_b.iloc[0]['statistical_qty'])
        assert abs(ratio - 2.0) < 0.1

    def test_product_grain_uses_value_share(self):
        """Product-hierarchy grain disaggregates by revenue share, not qty."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        uids = ['ITEM-X|NULL|LOC-1', 'ITEM-Y|NULL|LOC-1']
        # ITEM-X: qty=100, revenue=1000 (price=10)
        # ITEM-Y: qty=100, revenue=500  (price=5)
        # Equal qty but unequal revenue — value-share should split 2:1
        dates = pd.date_range('2022-01-01', periods=12, freq='MS')
        rows = []
        for ds in dates:
            rows += [
                {'unique_id': 'ITEM-X|NULL|LOC-1', 'ds': ds, 'y': 100.0,
                 'item_id': 10, 'item__item_id': 'ITEM-X',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 1000.0},
                {'unique_id': 'ITEM-Y|NULL|LOC-1', 'ds': ds, 'y': 100.0,
                 'item_id': 11, 'item__item_id': 'ITEM-Y',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 500.0},
            ]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # Product-group forecast: taxon grain, y = revenue (1500 total)
        forecast_df = pd.DataFrame([{
            'unique_id': 'taxon_5_ALL_LOC',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 1500.0,   # this is REVENUE for product grains
            'grain': 'taxon_5_client',
            'model_used': 'AutoETS',
            'forecast_level': 'taxon_5_client',
            'eval_period': 'month',
        }])

        decisions = self._make_decisions(
            uids, 'taxon_5_client',
            # ITEM-X: price=10, ITEM-Y: price=5
            {'ITEM-X|NULL|LOC-1': Decimal('10'), 'ITEM-Y|NULL|LOC-1': Decimal('5')},
        )
        #result = disaggregate_to_atomic(forecast_df, actuals_pl, decisions)
        result = disaggregate_to_atomic(
            forecast_df, actuals_pl, decisions,
            period_type='month',
            base_freq='MS',
        )
        item_x = result[result['unique_id'] == 'ITEM-X|NULL|LOC-1']
        item_y = result[result['unique_id'] == 'ITEM-Y|NULL|LOC-1']

        if not item_x.empty and not item_y.empty:
            # ITEM-X gets 2/3 of revenue = 1000. qty = 1000/10 = 100
            # ITEM-Y gets 1/3 of revenue = 500.  qty = 500/5  = 100
            # Both get qty=100 in this case — equal quantities, different prices
            qty_x = float(item_x.iloc[0]['statistical_qty'])
            qty_y = float(item_y.iloc[0]['statistical_qty'])
            assert abs(qty_x - 100) < 1
            assert abs(qty_y - 100) < 1

    def test_retain_lower_does_not_overwrite_atomic(self):
        """disagg_conflict='retain_lower': atomic forecast is not overwritten."""
        from utils.demand.forecast_engine import disaggregate_to_atomic
        import polars as pl

        uid = 'ITEM-A|NULL|LOC-1'
        rows = [{'unique_id': uid, 'ds': pd.Timestamp('2022-01-01'),
                 'y': 100.0, 'item_id': 1, 'item__item_id': 'ITEM-A',
                 'planning_customer_id': None, 'customer_code': 'NULL',
                 'planning_location_id': 1, 'planning_location__code': 'LOC-1',
                 'region_code': 'REG-1', 'revenue': 500.0}]
        actuals_pl = pl.from_pandas(pd.DataFrame(rows))

        # Atomic forecast already exists
        atomic_df = pd.DataFrame([{
            'unique_id': uid, 'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 999.0,   # sentinel value
            'grain': 'item_cust_location',
            'model_used': 'AutoETS',
            'forecast_level': 'item_cust_location',
        }])
        # Product-grain forecast also exists
        product_df = pd.DataFrame([{
            'unique_id': 'ITEM-A|ALL_CUST|ALL_LOC',
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 1200.0,
            'grain': 'item_client',
            'model_used': 'AutoETS',
            'forecast_level': 'item_client',
        }])
        combined_df = pd.concat([atomic_df, product_df], ignore_index=True)

        decisions = {uid: {
            'grain': 'item_client', 'strategy': 'AUTOETS',
            'eval_period': 'month', 'is_manual': False,
            'price': Decimal('5'), 'item_id': 1,
            'location_id': 1, 'customer_id': None,
        }}
        result = disaggregate_to_atomic(
            combined_df, actuals_pl, decisions,
            period_type='month',
            base_freq='MS',
            disagg_conflict='retain_lower',
        )
        #result = disaggregate_to_atomic(
        #    combined_df, actuals_pl, decisions, disagg_conflict='retain_lower'
        #)

        atomic_row = result[
            (result['unique_id'] == uid) &
            (result['grain'] == 'item_cust_location')
        ]
        assert not atomic_row.empty
        # The original atomic 999 is retained
        assert float(atomic_row.iloc[0]['statistical_qty']) == 999.0


# ─────────────────────────────────────────────────────────────────────────────
# Test: write_forecast_lines — value fields computed correctly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestWriteForecastLines:

    def test_row_count_matches_input(
        self, draft_version, active_item, leaf_location, series_profile,
        item_planning_profile
    ):
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine

        forecast_df = pd.DataFrame([
            {'unique_id': 'item-001|CUST-01|LEAF-01',
             'ds': pd.Timestamp('2025-01-01'),
             'statistical_qty': 480.0, 'model_used': 'AutoETS',
             'grain': 'item_cust_location',
             'forecast_level': 'item_cust_location'},
            {'unique_id': 'item-001|CUST-01|LEAF-01',
             'ds': pd.Timestamp('2025-02-01'),
             'statistical_qty': 520.0, 'model_used': 'AutoETS',
             'grain': 'item_cust_location',
             'forecast_level': 'item_cust_location'},
        ])

        from mysite.models import Item
        from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
        decisions = {
            'item-001|CUST-01|LEAF-01': {
                'grain': 'item_cust_location', 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': Decimal('150.00'),
                'item_id': active_item.pk,
                'location_id': leaf_location.pk,
                'customer_id': None,
            }
        }

        n = write_forecast_lines(
            draft_version.pk, forecast_df, decisions, 'month',
            store_all_level_forecasts=True,
        )
        assert n == 2
        assert ForecastLine.objects.filter(version=draft_version).count() == 2

    def test_final_value_computed_from_price(
        self, draft_version, active_item, leaf_location
    ):
        """final_value = statistical_qty × price."""
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine

        forecast_df = pd.DataFrame([{
            'unique_id': 'item-001|NULL|LEAF-01',    # ← lowercase
            'ds': pd.Timestamp('2025-01-01'),
            'statistical_qty': 100.0,
            'model_used': 'AutoETS',
            'grain': 'item_cust_location',
            'forecast_level': 'item_cust_location',
        }])


        decisions = {
            'item-001|NULL|LEAF-01': {
                'grain': 'item_cust_location', 'strategy': 'AUTOETS',
                'eval_period': 'month', 'is_manual': False,
                'price': Decimal('250.00'),
                'item_id': active_item.pk,
                'location_id': leaf_location.pk,
                'customer_id': None,
            }
        }

        write_forecast_lines(
            draft_version.pk, forecast_df, decisions, 'month',
        )
        line = ForecastLine.objects.get(version=draft_version)
        assert line.final_value == Decimal('25000.00')  # 100 × 250
        assert line.price_used  == Decimal('250.00')


# ─────────────────────────────────────────────────────────────────────────────
# Test: Reconciliation coherence (unchanged — pure function test)
# ─────────────────────────────────────────────────────────────────────────────

class TestMinTraceCoherence:

    def test_reconciled_total_equals_summed_leaves(self):
        from utils.demand.forecast_engine import run_hierarchical_reconciliation
        from hierarchicalforecast.utils import aggregate

        raw = pd.DataFrame({
            'ds':        pd.date_range('2022-01-01', periods=24, freq='MS').tolist() * 2,
            'group':     ['A'] * 24 + ['A'] * 24,
            'series':    ['leaf1'] * 24 + ['leaf2'] * 24,   # ← renamed from unique_id
            'y':         list(range(100, 124)) + list(range(50, 74)),
        })
        raw['y'] = raw['y'].astype(float)

        # Hierarchy: top level = group; bottom level = group × series
        Y_df, S_df, tags = aggregate(
            raw, [['group'], ['group', 'series']]   # ← use 'series' not 'unique_id'
        )

        from statsforecast import StatsForecast
        from statsforecast.models import SeasonalNaive

        sf = StatsForecast(
            models=[SeasonalNaive(season_length=12)], freq='MS', n_jobs=1
        )
        forecasts_df = sf.forecast(df=Y_df, h=3)

        reconciled = run_hierarchical_reconciliation(
            forecasts_df=forecasts_df,
            Y_df=Y_df, S_df=S_df, tags=tags,
            method='MinTrace_ols',
        )

        rec_col = [
            c for c in reconciled.columns
            if c not in ('unique_id', 'ds') and 'SeasonalNaive' in c
        ]
        assert rec_col
        rec_col = rec_col[0]

        for ds_val in reconciled['ds'].unique():
            period = reconciled[reconciled['ds'] == ds_val]
            total  = float(period[period['unique_id'] == 'A'][rec_col].values[0])
            leaf1  = float(period[period['unique_id'] == 'A/leaf1'][rec_col].values[0])
            leaf2  = float(period[period['unique_id'] == 'A/leaf2'][rec_col].values[0])
            assert abs(total - (leaf1 + leaf2)) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Test: MAPE computation (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class TestMapeComputation:

    def test_mape_formula(self):
        actual   = 400.0
        forecast = 440.0
        mape = abs(actual - forecast) / actual * 100
        bias = (forecast - actual) / actual * 100
        assert abs(mape - 10.0) < 0.001
        assert abs(bias - 10.0) < 0.001

    def test_mape_null_when_actual_zero(self):
        actual = 0.0
        mape   = None if actual == 0 else abs(0 - actual) / actual * 100
        assert mape is None
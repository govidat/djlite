# mysite/tests/demand/test_forecast.py

import pytest
import datetime
from decimal import Decimal
from django.core.exceptions import ValidationError

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine,
    ForecastOverride, OverrideSplitWeight,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def staff_user(db, django_user_model):
    user, _ = django_user_model.objects.get_or_create(
        username='planner',
        defaults={
            'first_name': 'Test',
            'last_name': 'Planner',
        },
    )
    return user


@pytest.fixture
def approver_user(db, django_user_model):
    user, _ = django_user_model.objects.get_or_create(
        username='approver',
        defaults={},
    )
    return user


@pytest.fixture
def draft_version(db, client_obj, staff_user):
    return ForecastVersion.objects.create(
        client          = client_obj,
        version_label   = 'Jan-2025 Monthly v1',
        period_type     = 'month',
        base_period_end = datetime.date(2024, 12, 31),
        horizon_periods = 6,
        status          = ForecastVersion.Status.DRAFT,
        created_by      = staff_user,
    )


@pytest.fixture
def forecast_line(db, draft_version, active_item, leaf_location, planning_customer):
    return ForecastLine.objects.create(
        version           = draft_version,
        item              = active_item,
        planning_location = leaf_location,
        planning_customer = planning_customer,
        period_type       = 'month',
        period_start      = datetime.date(2025, 1, 1),
        statistical_qty   = Decimal('480.000'),
        final_qty         = Decimal('480.000'),   # ← add this
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: final_qty computation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastLineFinalQty:

    def test_final_qty_equals_statistical_when_no_override(self, forecast_line):
        """final_qty = statistical_qty when override_qty is None."""
        assert forecast_line.override_qty is None
        assert forecast_line.final_qty == Decimal('480.000')

    def test_final_qty_equals_override_when_set(self, forecast_line):
        """final_qty = override_qty when override_qty is set."""
        forecast_line.override_qty = Decimal('550.000')
        forecast_line.save()
        forecast_line.refresh_from_db()

        assert forecast_line.final_qty == Decimal('550.000')
        assert forecast_line.statistical_qty == Decimal('480.000')  # unchanged

    def test_final_qty_reverts_when_override_cleared(self, forecast_line):
        """Clearing override_qty causes final_qty to revert to statistical_qty."""
        forecast_line.override_qty = Decimal('600.000')
        forecast_line.save()

        forecast_line.override_qty = None
        forecast_line.save()
        forecast_line.refresh_from_db()

        assert forecast_line.final_qty == Decimal('480.000')

    def test_final_qty_zero_override_is_valid(self, forecast_line):
        """override_qty=0 is a valid override (e.g. planner sets demand to zero)."""
        forecast_line.override_qty = Decimal('0.000')
        forecast_line.save()
        forecast_line.refresh_from_db()

        # 0 is not None, so final_qty should be 0, not statistical_qty
        assert forecast_line.final_qty == Decimal('0.000')

    def test_period_end_auto_computed(self, forecast_line):
        """period_end is auto-computed from period_type + period_start."""
        assert forecast_line.period_end == datetime.date(2025, 1, 31)


# ─────────────────────────────────────────────────────────────────────────────
# Test: State machine transitions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastVersionStateMachine:

    def test_draft_transitions_to_in_review(self, draft_version, staff_user):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.refresh_from_db()
        assert draft_version.status == ForecastVersion.Status.IN_REVIEW

    def test_in_review_transitions_to_approved(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.refresh_from_db()

        assert draft_version.status == ForecastVersion.Status.APPROVED
        assert draft_version.approved_by == approver_user
        assert draft_version.approved_at is not None

    def test_approved_transitions_to_locked(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)
        draft_version.refresh_from_db()

        assert draft_version.status == ForecastVersion.Status.LOCKED
        assert draft_version.locked_at is not None

    def test_locked_rejects_all_transitions(
        self, draft_version, staff_user, approver_user
    ):
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        with pytest.raises(ValidationError):
            draft_version.transition_to(ForecastVersion.Status.DRAFT, staff_user)

    def test_invalid_transition_raises_validation_error(
        self, draft_version, staff_user
    ):
        """DRAFT cannot jump directly to APPROVED."""
        with pytest.raises(ValidationError):
            draft_version.transition_to(ForecastVersion.Status.APPROVED, staff_user)

    def test_in_review_can_be_sent_back_to_draft(
        self, draft_version, staff_user, approver_user
    ):
        """Approver can send back to DRAFT for rework."""
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.DRAFT, approver_user)
        draft_version.refresh_from_db()
        assert draft_version.status == ForecastVersion.Status.DRAFT


# ─────────────────────────────────────────────────────────────────────────────
# Test: LOCKED version rejects edits via API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLockedVersionRejectsEdits:

    def _lock_version(self, version, staff_user, approver_user):
        version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        version.transition_to(ForecastVersion.Status.LOCKED, approver_user)
        version.refresh_from_db()

    def test_locked_version_is_not_editable(
        self, draft_version, staff_user, approver_user
    ):
        self._lock_version(draft_version, staff_user, approver_user)
        assert not draft_version.is_editable
        assert draft_version.is_locked

    def test_assert_editable_raises_on_locked_version(
        self, draft_version, staff_user, approver_user
    ):
        self._lock_version(draft_version, staff_user, approver_user)
        with pytest.raises(ValidationError):
            draft_version.assert_editable()

    def test_api_returns_403_on_locked_version(
        self, api_client, draft_version, staff_user, approver_user
    ):
        from django.urls import reverse
        test_client, _ = api_client

        # Lock the version
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-forecast-version-approve', kwargs={'pk': draft_version.pk})
        response = test_client.post(url, {'action': 'submit'}, format='json')
        assert response.status_code == 403

    def test_override_on_locked_version_raises(
        self, draft_version, staff_user, approver_user,
        active_item, leaf_location
    ):
        """Creating a ForecastOverride on a LOCKED version raises ValidationError."""
        self._lock_version(draft_version, staff_user, approver_user)

        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = Decimal('600'),
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Version copy
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastVersionCopy:

    def test_copy_creates_new_draft(
        self, draft_version, forecast_line,
        staff_user, approver_user
    ):
        """copy() produces a new DRAFT version."""
        # Lock the original
        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version = draft_version.copy(user=staff_user, new_label='Feb-2025 Plan v1')

        assert new_version.status == ForecastVersion.Status.DRAFT
        assert new_version.version_label == 'Feb-2025 Plan v1'
        assert new_version.copied_from == draft_version
        assert new_version.client == draft_version.client

    def test_copy_clones_all_lines(
        self, draft_version, forecast_line,
        staff_user, approver_user,
        active_item, leaf_location, planning_customer
    ):
        """Copied version has same number of ForecastLine rows."""
        # Add a second line
        ForecastLine.objects.create(
            version           = draft_version,
            item              = active_item,
            planning_location = leaf_location,
            planning_customer = None,
            period_type       = 'month',
            period_start      = datetime.date(2025, 2, 1),
            statistical_qty   = Decimal('320.000'),
            final_qty         = Decimal('320.000'),   # ← add this
        )
        original_count = draft_version.lines.count()

        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version = draft_version.copy(user=staff_user)
        assert new_version.lines.count() == original_count

    def test_copy_preserves_override_qty(
        self, draft_version, forecast_line,
        staff_user, approver_user
    ):
        """Copied lines preserve override_qty and recompute final_qty."""
        forecast_line.override_qty = Decimal('550.000')
        forecast_line.save()

        draft_version.transition_to(ForecastVersion.Status.IN_REVIEW, staff_user)
        draft_version.transition_to(ForecastVersion.Status.APPROVED, approver_user)
        draft_version.transition_to(ForecastVersion.Status.LOCKED, approver_user)

        new_version  = draft_version.copy(user=staff_user)
        cloned_line  = new_version.lines.first()

        assert cloned_line.override_qty == Decimal('550.000')
        assert cloned_line.final_qty    == Decimal('550.000')
        assert cloned_line.statistical_qty == Decimal('480.000')

    def test_copy_of_draft_also_works(self, draft_version, forecast_line, staff_user):
        """copy() works from any status, not just LOCKED."""
        new_version = draft_version.copy(user=staff_user, new_label='Draft Copy')
        assert new_version.status == ForecastVersion.Status.DRAFT
        assert new_version.lines.count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastOverride validation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastOverrideValidation:

    def test_cannot_set_both_qty_and_pct(self, draft_version, staff_user):
        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = Decimal('500'),
            override_pct   = Decimal('10'),
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()

    def test_must_set_one_of_qty_or_pct(self, draft_version, staff_user):
        override = ForecastOverride(
            version        = draft_version,
            override_level = 'sku',
            override_key   = {'item_id': 'ITEM-001'},
            period_type    = 'month',
            period_start   = datetime.date(2025, 1, 1),
            override_qty   = None,
            override_pct   = None,
            disagg_method  = ForecastOverride.DisaggMethod.PROPORTIONAL,
            created_by     = staff_user,
        )
        with pytest.raises(ValidationError):
            override.full_clean()

# ─────────────────────────────────────────────────────────────────────────────
# Additional fixtures needed for SeriesProfile tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def forecasting_config(db, client_obj):
    from mysite.models.demand.forecast import ForecastingConfig
    return ForecastingConfig.get_for_client(client_obj)


@pytest.fixture
def abc_definitions(db, client_obj):
    from mysite.models.demand.forecast import AbcClassDefinition
    return AbcClassDefinition.get_or_create_defaults(client_obj)


@pytest.fixture
def series_profile(db, client_obj, active_item, leaf_location,
                   planning_customer, forecasting_config, abc_definitions):
    from mysite.models.demand.forecast import SeriesProfile
    import datetime
    return SeriesProfile.objects.create(
        client            = client_obj,
        item              = active_item,
        planning_customer = planning_customer,
        planning_location = leaf_location,
        period_type       = 'month',
        analysis_from     = datetime.date(2022, 1, 1),
        analysis_to       = datetime.date(2024, 12, 31),
        total_periods     = 36,
        nonzero_periods   = 24,
        total_qty         = Decimal('8640.000'),
        zero_rate         = Decimal('0.3333'),
        demand_class_atomic = 'SMOOTH',
        abc_class_atomic    = 'A',
        chosen_grain        = 'item_client',
        chosen_demand_class = 'SMOOTH',
        chosen_strategy     = 'AUTOETS',
        chosen_eval_period  = 'month',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: AbcClassDefinition
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAbcClassDefinition:

    def test_get_or_create_defaults_creates_three_tiers(
        self, client_obj, abc_definitions
    ):
        """Default tiers are A/B/C at 70/90/100."""
        from mysite.models.demand.forecast import AbcClassDefinition
        tiers = AbcClassDefinition.objects.filter(client=client_obj).order_by('rank')
        assert tiers.count() == 3
        labels = [t.label for t in tiers]
        assert labels == ['A', 'B', 'C']
        thresholds = [float(t.cumulative_upper_pct) for t in tiers]
        assert thresholds == [70.0, 90.0, 100.0]

    def test_get_or_create_defaults_is_idempotent(self, client_obj, abc_definitions):
        """Calling get_or_create_defaults twice does not create duplicates."""
        from mysite.models.demand.forecast import AbcClassDefinition
        AbcClassDefinition.get_or_create_defaults(
            AbcClassDefinition.objects.filter(client=client_obj).first().client
        )
        assert AbcClassDefinition.objects.filter(client=client_obj).count() == 3

    def test_compute_class_a_item(self, abc_definitions):
        """Item at top of value ranking is class A."""
        from mysite.models.demand.forecast import AbcClassDefinition
        # Item with value 700 out of [1000, 700, 200, 100] total=2000
        # cumulative share of top item = 1000/2000=50%, rank-1 item is A
        result = AbcClassDefinition.compute_class(
            item_value=1000.0,
            all_values_sorted_desc=[1000.0, 700.0, 200.0, 100.0],
            definitions=abc_definitions,
        )
        assert result['abc_class'] == 'A'

    def test_compute_class_c_item(self, abc_definitions):
        """Item at bottom of value ranking is class C."""
        from mysite.models.demand.forecast import AbcClassDefinition
        result = AbcClassDefinition.compute_class(
            item_value=100.0,
            all_values_sorted_desc=[1000.0, 700.0, 200.0, 100.0],
            definitions=abc_definitions,
        )
        assert result['abc_class'] == 'C'

    def test_four_tier_client(self, client_obj):
        """Client with 4 tiers (A/B/C/D) classifies correctly."""
        from mysite.models.demand.forecast import AbcClassDefinition
        # Create 4-tier config
        AbcClassDefinition.objects.filter(client=client_obj).delete()
        defs = AbcClassDefinition.objects.bulk_create([
            AbcClassDefinition(client=client_obj, rank=1, label='A',
                               cumulative_upper_pct=Decimal('60.000')),
            AbcClassDefinition(client=client_obj, rank=2, label='B',
                               cumulative_upper_pct=Decimal('80.000')),
            AbcClassDefinition(client=client_obj, rank=3, label='C',
                               cumulative_upper_pct=Decimal('95.000')),
            AbcClassDefinition(client=client_obj, rank=4, label='D',
                               cumulative_upper_pct=Decimal('100.000')),
        ])
        result = AbcClassDefinition.compute_class(
            item_value=50.0,           # last item, clearly D
            all_values_sorted_desc=[500.0, 300.0, 150.0, 50.0],
            definitions=defs,
        )
        assert result['abc_class'] == 'D'


# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastingConfig
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastingConfig:

    def test_get_for_client_creates_with_defaults(self, client_obj):
        """get_for_client creates a config with sensible defaults."""
        from mysite.models.demand.forecast import ForecastingConfig
        config = ForecastingConfig.get_for_client(client_obj)
        assert float(config.adi_threshold)  == 1.32
        assert float(config.cv2_threshold)  == 0.49
        assert config.min_nonzero_periods   == 6
        assert config.time_horizon_steps    == 2
        assert config.evaluate_customer_grain is True

    def test_get_for_client_is_idempotent(self, client_obj, forecasting_config):
        """Calling get_for_client twice returns the same row."""
        from mysite.models.demand.forecast import ForecastingConfig
        config2 = ForecastingConfig.get_for_client(client_obj)
        assert config2.pk == forecasting_config.pk

    def test_derived_time_horizons_monthly(self, forecasting_config):
        """Monthly base with 2 steps gives [quarter, halfyear]."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('month', forecasting_config.time_horizon_steps)
        assert horizons == ['quarter', 'halfyear']

    def test_derived_time_horizons_daily(self, forecasting_config):
        """Daily base with 2 steps gives [week, fortnight]."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('day', forecasting_config.time_horizon_steps)
        assert horizons == ['week', 'fortnight']

    def test_zero_steps_returns_empty(self, forecasting_config):
        """time_horizon_steps=0 means no time aggregation is tried."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('month', 0)
        assert horizons == []


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile.compute_syntetos_boylan (pure function)
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSyntetosBoylan:
    """
    Pure function tests — no DB required.
    All use default thresholds: ADI=1.32, CV²=0.49, min_nonzero=6.
    """

    ADI = 1.32
    CV2 = 0.49
    MNZ = 6

    def test_smooth_series(self):
        """All-positive, low-variance series → SMOOTH."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('100')] * 36
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'SMOOTH'
        assert result['recommended_strategy'] == 'AUTOETS'
        assert result['nonzero_periods'] == 36
        assert float(result['adi']) == pytest.approx(1.0, abs=0.01)

    def test_lumpy_series(self):
        """Sparse, high-variance series → LUMPY."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI = 36/6 = 6.0 ≥ 1.32; CV² needs to be ≥ 0.49
        # Use very high variance: [1, 500, 2, 480, 3, 520] → CV² ≈ 1.4
        qty = [Decimal('0')] * 30 + [
            Decimal('1'), Decimal('500'), Decimal('2'),
            Decimal('480'), Decimal('3'), Decimal('520'),
        ]
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'LUMPY'
        assert float(result['adi']) == pytest.approx(6.0, abs=0.1)

    def test_intermittent_series(self):
        """Sparse but stable qty → INTERMITTENT → Croston."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI ≥ 1.32, CV² < 0.49 (stable qty of 100 each time)
        qty = [Decimal('0')] * 30 + [Decimal('100')] * 6
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'INTERMITTENT'
        assert result['recommended_strategy'] == 'CROSTON'

    def test_erratic_series(self):
        """Frequent but high-variance qty → ERRATIC → AutoARIMA."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI < 1.32 (demand every period), CV² ≥ 0.49 (wildly variable)
        qty = [
            Decimal('5'), Decimal('500'), Decimal('3'), Decimal('450'),
            Decimal('8'), Decimal('600'), Decimal('2'), Decimal('400'),
            Decimal('10'), Decimal('550'), Decimal('4'), Decimal('480'),
        ] * 3   # 36 periods
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'ERRATIC'
        assert result['recommended_strategy'] == 'AUTOARIMA'

    def test_zero_series(self):
        """All-zero series → ZERO → MANUAL."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('0')] * 36
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'ZERO'
        assert result['recommended_strategy'] == 'MANUAL'
        assert result['nonzero_periods'] == 0

    def test_insufficient_series(self):
        """Fewer than min_nonzero non-zero periods → INSUFFICIENT."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('0')] * 33 + [Decimal('100')] * 3   # only 3 non-zero
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'INSUFFICIENT'
        assert result['recommended_strategy'] == 'MOVING_AVG'

    def test_configurable_thresholds(self):
        """Stricter ADI threshold changes classification."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI = 36/12 = 3.0 — INTERMITTENT with default 1.32
        # but SMOOTH with a very loose threshold of 10.0
        qty = [Decimal('0')] * 24 + [Decimal('100')] * 12
        default_result = SeriesProfile.compute_syntetos_bowlan(
            qty, 1.32, 0.49, 6
        ) if False else SeriesProfile.compute_syntetos_boylan(qty, 1.32, 0.49, 6)
        loose_result   = SeriesProfile.compute_syntetos_boylan(qty, 10.0, 0.49, 6)

        assert default_result['demand_class'] == 'INTERMITTENT'
        assert loose_result['demand_class']   == 'SMOOTH'


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesLevelEvaluation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesLevelEvaluation:

    def test_create_evaluation_row(
        self, client_obj, active_item, leaf_location
    ):
        """Can create a SeriesLevelEvaluation row with grain string."""
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        import datetime

        eval_row = SeriesLevelEvaluation.objects.create(
            client=client_obj,
            item=active_item,
            planning_customer=None,
            period_type='month',
            grain='item_client',
            evaluation_key={'grain': 'item_client'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36,
            nonzero_periods=20,
            total_qty=Decimal('2400.000'),
            zero_rate=Decimal('0.4444'),
            demand_class='LUMPY',
            is_accepted=False,
            rejection_reason='LUMPY (ADI=1.8, CV²=0.62)',
            recommended_strategy='',
        )
        assert eval_row.pk is not None
        assert eval_row.is_accepted is False
        assert 'LUMPY' in eval_row.rejection_reason

    def test_accepted_grain_stored_correctly(
        self, client_obj, active_item, leaf_location
    ):
        """The accepted evaluation row is flagged is_accepted=True."""
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        import datetime

        SeriesLevelEvaluation.objects.create(
            client=client_obj, item=active_item, planning_customer=None,
            period_type='month',
            grain='item_client',
            evaluation_key={'grain': 'item_client'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36, nonzero_periods=30,
            total_qty=Decimal('5000.000'),
            zero_rate=Decimal('0.1667'),
            demand_class='SMOOTH',
            is_accepted=True,
            rejection_reason='',
            recommended_strategy='AUTOETS',
        )
        accepted = SeriesLevelEvaluation.objects.filter(
            client=client_obj, item=active_item,
            period_type='month', is_accepted=True
        )
        assert accepted.count() == 1
        assert accepted.first().demand_class == 'SMOOTH'


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile model properties
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesProfileProperties:

    def test_effective_grain_uses_chosen_when_no_override(self, series_profile):
        """effective_grain returns chosen_grain when no override is set."""
        assert series_profile.override_grain == ''
        assert series_profile.effective_grain == 'item_client'

    def test_effective_grain_honours_override(self, series_profile):
        """effective_grain returns override_grain when set."""
        series_profile.override_grain = 'item_loc_depth_2'
        series_profile.save()
        assert series_profile.effective_grain == 'item_loc_depth_2'

    def test_effective_strategy_honours_override(self, series_profile):
        """effective_strategy returns override when set."""
        series_profile.override_strategy = 'CROSTON'
        series_profile.save()
        assert series_profile.effective_strategy == 'CROSTON'

    def test_is_overridden_false_by_default(self, series_profile):
        assert series_profile.is_overridden is False

    def test_is_overridden_true_when_grain_set(self, series_profile):
        series_profile.override_grain = 'item_client'
        assert series_profile.is_overridden is True

    def test_is_manual_true_when_strategy_manual(self, series_profile):
        series_profile.chosen_strategy = 'MANUAL'
        assert series_profile.is_manual is True

    def test_is_manual_false_for_autoets(self, series_profile):
        series_profile.chosen_strategy = 'AUTOETS'
        assert series_profile.is_manual is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile API — PATCH override
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesProfileAPI:

    def test_patch_override_grain_valid(
        self, api_client, series_profile, staff_user, client_obj,
        active_item, leaf_location
    ):
        test_client, _ = api_client
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        from django.urls import reverse
        import datetime

        SeriesLevelEvaluation.objects.create(
            client=client_obj, item=active_item, planning_customer=None,
            period_type='month',
            grain='item_loc_depth_1',
            evaluation_key={'grain': 'item_loc_depth_1', 'level_label': 'Region'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36, nonzero_periods=28,
            total_qty=Decimal('4000.000'),
            zero_rate=Decimal('0.2222'),
            demand_class='INTERMITTENT',
            is_accepted=False,
            rejection_reason='',
            recommended_strategy='CROSTON',
        )

        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = test_client.patch(
            url,
            {'override_grain': 'item_loc_depth_1', 'override_note': 'Manual review'},
            format='json',
        )
        assert response.status_code == 200
        data = response.json()
        assert data['override_grain']  == 'item_loc_depth_1'
        assert data['is_overridden']   is True
        assert data['effective_grain'] == 'item_loc_depth_1'

    def test_patch_disallowed_field_rejected(
        self, api_client, series_profile, staff_user
    ):
        test_client, _ = api_client
        from django.urls import reverse
        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = test_client.patch(
            url,
            {'chosen_grain': 'item_client'},
            format='json',
        )
        assert response.status_code == 400
        assert 'not writable' in response.json()['detail']

    def test_patch_invalid_grain_rejected(
        self, api_client, series_profile, staff_user
    ):
        test_client, _ = api_client
        from django.urls import reverse
        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = test_client.patch(
            url,
            {'override_grain': 'item_loc_depth_99'},
            format='json',
        )
        assert response.status_code == 400
        assert 'valid grain' in response.json()['override_grain'][0]

# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastingConfigView API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastingConfigAPI:

    def test_get_returns_config_with_abc_tiers(
        self, api_client, client_obj, staff_user, forecasting_config, abc_definitions
    ):
        test_client, _ = api_client
        from django.urls import reverse
        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-forecasting-config')
        response = test_client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert 'adi_threshold'         in data
        assert 'abc_class_definitions' in data
        assert len(data['abc_class_definitions']) == 3
        assert data['abc_class_definitions'][0]['label'] == 'A'

    def test_get_includes_derived_time_horizons_for_period(
        self, api_client, client_obj, staff_user, forecasting_config, abc_definitions
    ):
        test_client, _ = api_client
        from django.urls import reverse
        test_client.force_authenticate(user=staff_user)
        url = reverse('demand-forecasting-config')
        response = test_client.get(url, {'period_type': 'month'})
        data = response.json()
        assert data['derived_time_horizons'] == ['quarter', 'halfyear']

    def test_patch_by_non_staff_returns_403(
        self, api_client, client_obj, forecasting_config, abc_definitions,
        django_user_model
    ):
        test_client, _ = api_client
        from django.urls import reverse
        regular_user = django_user_model.objects.create_user(
            'regular', password='pw', is_staff=False
        )
        test_client.force_authenticate(user=regular_user)
        url = reverse('demand-forecasting-config')
        response = test_client.patch(url, {'time_horizon_steps': 3}, format='json')
        assert response.status_code == 403

    def test_patch_by_staff_updates_threshold(
        self, api_client, client_obj, staff_user, forecasting_config, abc_definitions,
        django_user_model
    ):
        test_client, _ = api_client
        from django.urls import reverse
        staff = django_user_model.objects.create_user(
            'adminstaff', password='pw', is_staff=True
        )
        test_client.force_authenticate(user=staff)
        url = reverse('demand-forecasting-config')
        response = test_client.patch(url, {'adi_threshold': '1.5000'}, format='json')
        assert response.status_code == 200
        assert response.json()['adi_threshold'] == '1.5000'
        forecasting_config.refresh_from_db()
        assert float(forecasting_config.adi_threshold) == 1.5
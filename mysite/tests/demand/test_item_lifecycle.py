# mysite/tests/demand/test_item_lifecycle.py
"""
Run:
  pytest mysite/tests/demand/test_item_lifecycle.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from mysite.models.demand.lifecycle import (
    ItemSubstitution, ItemDiscontinuation, ItemIntroduction,
    _assert_subject_role_free,
)


# -- Fixtures ----------------------------------------------------------------

@pytest.fixture
def item_a(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(client=client_obj, item_id='ITEM-A', name='Item A', status='active')


@pytest.fixture
def item_b(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(client=client_obj, item_id='ITEM-B', name='Item B', status='active')


@pytest.fixture
def item_c(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(client=client_obj, item_id='ITEM-C', name='Item C', status='active')


@pytest.fixture
def other_client_obj(db):
    from mysite.models import Client
    return Client.objects.create(client_id='OTHER1', name='Other Client')


@pytest.fixture
def other_item(db, other_client_obj):
    from mysite.models import Item
    return Item.objects.create(client=other_client_obj, item_id='ITEM-X', name='Other Item', status='active')


# ============================================================================
# Model Validation Tests
# ============================================================================

@pytest.mark.django_db
class TestItemSubstitutionValidation:

    def test_valid_creation(self, client_obj, item_a, item_b):
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('0.5'),
        )
        sub.full_clean()
        sub.save()
        assert sub.pk is not None

    def test_old_equals_new_rejected(self, client_obj, item_a):
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=item_a,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_conversion_factor_zero_rejected(self, client_obj, item_a, item_b):
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('0'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_conversion_factor_negative_rejected(self, client_obj, item_a, item_b):
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('-1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_cross_client_old_item_rejected(self, other_client_obj, item_a, item_b):
        sub = ItemSubstitution(
            client=other_client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_cross_client_new_item_rejected(self, client_obj, item_a, other_item):
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=other_item,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_direct_mapping_no_successor_as_old(self, client_obj, item_a, item_b, item_c):
        ItemSubstitution.objects.create(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        sub2 = ItemSubstitution(
            client=client_obj, old_item=item_b, new_item=item_c,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub2.full_clean()

    def test_direct_mapping_no_predecessor_as_new(self, client_obj, item_a, item_b, item_c):
        ItemSubstitution.objects.create(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        sub2 = ItemSubstitution(
            client=client_obj, old_item=item_c, new_item=item_a,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub2.full_clean()

    def test_unique_together_enforced(self, client_obj, item_a, item_b):
        ItemSubstitution.objects.create(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(Exception):
            ItemSubstitution.objects.create(
                client=client_obj, old_item=item_a, new_item=item_b,
                conversion_factor=Decimal('1'),
            )

    def test_default_conversion_factor(self, client_obj, item_a, item_b):
        sub = ItemSubstitution(client=client_obj, old_item=item_a, new_item=item_b)
        sub.full_clean()
        sub.save()
        assert sub.conversion_factor == Decimal('1')


@pytest.mark.django_db
class TestItemDiscontinuationValidation:

    def test_valid_creation(self, client_obj, item_a):
        disc = ItemDiscontinuation(
            client=client_obj, item=item_a,
            effective_from=datetime.date(2025, 6, 1),
        )
        disc.full_clean()
        disc.save()
        assert disc.pk is not None

    def test_null_effective_from(self, client_obj, item_a):
        disc = ItemDiscontinuation(client=client_obj, item=item_a, effective_from=None)
        disc.full_clean()
        disc.save()
        assert disc.effective_from is None

    def test_cross_client_rejected(self, other_client_obj, item_a):
        disc = ItemDiscontinuation(client=other_client_obj, item=item_a)
        with pytest.raises(ValidationError):
            disc.full_clean()

    def test_unique_together_enforced(self, client_obj, item_a):
        ItemDiscontinuation.objects.create(client=client_obj, item=item_a)
        with pytest.raises(Exception):
            ItemDiscontinuation.objects.create(client=client_obj, item=item_a)


@pytest.mark.django_db
class TestItemIntroductionValidation:

    def test_valid_creation(self, client_obj, item_a, item_b):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('0.5'),
        )
        intro.full_clean()
        intro.save()
        assert intro.pk is not None

    def test_new_equals_reference_rejected(self, client_obj, item_a):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=item_a,
            ratio=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_ratio_zero_rejected(self, client_obj, item_a, item_b):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('0'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_ratio_negative_rejected(self, client_obj, item_a, item_b):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('-1'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_copy_to_before_copy_from_rejected(self, client_obj, item_a, item_b):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
            copy_from=datetime.date(2025, 6, 1),
            copy_to=datetime.date(2025, 1, 1),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_cross_client_new_item_rejected(self, other_client_obj, item_a, item_b):
        intro = ItemIntroduction(
            client=other_client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_cross_client_reference_rejected(self, client_obj, item_a, other_item):
        intro = ItemIntroduction(
            client=client_obj, new_item=item_a, reference_item=other_item,
            ratio=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_no_reference_chain(self, client_obj, item_a, item_b, item_c):
        ItemIntroduction.objects.create(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
        )
        intro2 = ItemIntroduction(
            client=client_obj, new_item=item_b, reference_item=item_c,
            ratio=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            intro2.full_clean()

    def test_unique_together_enforced(self, client_obj, item_a, item_b):
        ItemIntroduction.objects.create(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
        )
        with pytest.raises(Exception):
            ItemIntroduction.objects.create(
                client=client_obj, new_item=item_a, reference_item=item_b,
                ratio=Decimal('1'),
            )


# ============================================================================
# Cross-Event Role Exclusivity Tests
# ============================================================================

@pytest.mark.django_db
class TestSubjectRoleExclusivity:

    def test_sub_old_cannot_be_discontinued(self, client_obj, item_a, item_b):
        ItemSubstitution.objects.create(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        disc = ItemDiscontinuation(client=client_obj, item=item_a)
        with pytest.raises(ValidationError):
            disc.full_clean()

    def test_sub_new_cannot_be_introduced(self, client_obj, item_a, item_b, item_c):
        ItemSubstitution.objects.create(
            client=client_obj, old_item=item_a, new_item=item_b,
            conversion_factor=Decimal('1'),
        )
        intro = ItemIntroduction(
            client=client_obj, new_item=item_b, reference_item=item_c,
            ratio=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            intro.full_clean()

    def test_discontinued_cannot_be_sub_new(self, client_obj, item_a, item_b):
        ItemDiscontinuation.objects.create(client=client_obj, item=item_a)
        sub = ItemSubstitution(
            client=client_obj, old_item=item_b, new_item=item_a,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_introduced_cannot_be_sub_old(self, client_obj, item_a, item_b, item_c):
        ItemIntroduction.objects.create(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
        )
        sub = ItemSubstitution(
            client=client_obj, old_item=item_a, new_item=item_c,
            conversion_factor=Decimal('1'),
        )
        with pytest.raises(ValidationError):
            sub.full_clean()

    def test_reference_item_may_overlap(self, client_obj, item_a, item_b):
        ItemIntroduction.objects.create(
            client=client_obj, new_item=item_a, reference_item=item_b,
            ratio=Decimal('1'),
        )
        disc = ItemDiscontinuation(client=client_obj, item=item_b)
        disc.full_clean()  # Should NOT raise
        assert True


# ============================================================================
# Feature Gate Tests
# ============================================================================

@pytest.mark.django_db
class TestFeatureGate:

    @pytest.fixture(autouse=True)
    def _flush_feature_cache_after(self):
        """Feature-control results are cached (900s) per client+feature and
        outlive these tests' transaction rollback — flush after each test so
        later modules aren't served a stale kill-switch for TEST01."""
        yield
        from django.core.cache import cache
        cache.clear()

    def test_item_lifecycle_ui_visible_default(self, client_obj):
        from utils.feature_control import item_lifecycle_ui_visible
        assert item_lifecycle_ui_visible(client_obj) is True

    def test_item_lifecycle_ui_visible_none_client(self):
        from utils.feature_control import item_lifecycle_ui_visible
        assert item_lifecycle_ui_visible(None) is False

    def test_item_lifecycle_ui_visible_when_disabled(self, client_obj):
        from utils.feature_control import item_lifecycle_ui_visible
        from mysite.models import ClientFeatureControl
        from django.utils import timezone
        import datetime as dt
        now = timezone.now()
        ClientFeatureControl.objects.create(
            client=client_obj, feature='item_lifecycle', is_disabled=True,
            from_date=now - dt.timedelta(days=1),
            to_date=now + dt.timedelta(days=1),
        )
        from django.core.cache import cache
        cache.clear()
        assert item_lifecycle_ui_visible(client_obj) is False

    def test_item_lifecycle_ui_visible_when_parent_disabled(self, client_obj):
        from utils.feature_control import item_lifecycle_ui_visible
        from mysite.models import ClientFeatureControl
        from django.utils import timezone
        import datetime as dt
        now = timezone.now()
        ClientFeatureControl.objects.create(
            client=client_obj, feature='demand_planning', is_disabled=True,
            from_date=now - dt.timedelta(days=1),
            to_date=now + dt.timedelta(days=1),
        )
        from django.core.cache import cache
        cache.clear()
        assert item_lifecycle_ui_visible(client_obj) is False

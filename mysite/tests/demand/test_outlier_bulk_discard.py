# mysite/tests/demand/test_outlier_bulk_discard.py

"""
Planners iterate on the outlier process: unconfirmed (CANDIDATE) proposals
sit in the queue and — because of the 1:1 constraint — block the same rows
from being re-proposed on the next detection run. This module covers the
bulk-discard flow that removes individual or all such proposals.

Run:
    pytest mysite/tests/demand/test_outlier_bulk_discard.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from mysite.models.demand.actuals import ActualSale
from mysite.models import ActualSaleOutlierAdjustment


@pytest.fixture
def django_client(db, planner_user):
    from django.test import Client
    client = Client()
    client.force_login(planner_user)
    return client


@pytest.fixture
def outlier_setup(db, client_obj, leaf_location, active_item, planning_customer,
                  distribution_channel_common):
    actuals = [
        ActualSale.objects.create(
            client=client_obj,
            planning_location=leaf_location,
            item=active_item,
            planning_customer=planning_customer,
            distribution_channel=distribution_channel_common,
            period_type='month',
            period_start=datetime.date(2024, month, 1),
            qty=Decimal('500.000'),
            revenue=Decimal('5000.00'),
        )
        for month in (1, 2, 3, 4)
    ]
    candidates = [
        ActualSaleOutlierAdjustment.objects.create(
            actual_sale=actual,
            qty_adjustment=Decimal('100.000'),
            detected_by='SYSTEM',
            status='CANDIDATE',
        )
        for actual in actuals[:3]
    ]
    confirmed = ActualSaleOutlierAdjustment.objects.create(
        actual_sale=actuals[3],
        qty_adjustment=Decimal('100.000'),
        detected_by='SYSTEM',
        status='CONFIRMED',
    )
    return {
        'actuals': actuals,
        'candidates': candidates,
        'confirmed': confirmed,
    }


@pytest.fixture
def other_client_candidate(db, client_obj, distribution_channel_common):
    from mysite.models import Client, Item
    from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
    other = Client.objects.create(client_id='TEST02', name='Other Client')
    location = PlanningLocation.objects.create(
        client=other, code='ROOT2', name='Other Root', is_leaf=True,
    )
    item = Item.objects.create(
        client=other, item_id='item-002', name='Wheel', status='active',
    )
    customer = PlanningCustomer.objects.create(
        client=other, code='CUST-02', name='Other Customer',
    )
    actual = ActualSale.objects.create(
        client=other,
        planning_location=location,
        item=item,
        planning_customer=customer,
        distribution_channel=distribution_channel_common,
        period_type='month',
        period_start=datetime.date(2024, 1, 1),
        qty=Decimal('500.000'),
    )
    return ActualSaleOutlierAdjustment.objects.create(
        actual_sale=actual,
        qty_adjustment=Decimal('100.000'),
        detected_by='SYSTEM',
        status='CANDIDATE',
    )


def _bulk_url(client_obj):
    return reverse('demand_ui:outlier_bulk_delete', kwargs={'client_id': client_obj.client_id})


def _queue_url(client_obj, status):
    return reverse('demand_ui:outlier_queue', kwargs={'client_id': client_obj.client_id}) + f'?status={status}'


@pytest.mark.django_db
class TestBulkDiscard:

    def test_discard_selected_only_deletes_chosen_candidates(
        self, django_client, client_obj, outlier_setup
    ):
        ids = [str(c.pk) for c in outlier_setup['candidates'][:2]]
        resp = django_client.post(_bulk_url(client_obj), {
            'mode': 'selected',
            'adjustment_ids': ids,
        })
        assert resp.status_code == 200
        remaining = ActualSaleOutlierAdjustment.objects.filter(status='CANDIDATE')
        assert remaining.count() == 1
        assert remaining.filter(pk=outlier_setup['candidates'][2].pk).exists()
        assert ActualSaleOutlierAdjustment.objects.filter(
            status='CONFIRMED'
        ).count() == 1
        assert '2 proposed outlier(s) discarded.' in resp.content.decode()

    def test_discard_all_candidates_only_touches_candidates(
        self, django_client, client_obj, outlier_setup
    ):
        resp = django_client.post(_bulk_url(client_obj), {'mode': 'all'})
        assert resp.status_code == 200
        assert not ActualSaleOutlierAdjustment.objects.filter(
            status='CANDIDATE'
        ).exists()
        assert ActualSaleOutlierAdjustment.objects.filter(
            status='CONFIRMED'
        ).count() == 1

    def test_discard_with_no_valid_ids_deletes_nothing(
        self, django_client, client_obj, outlier_setup
    ):
        resp = django_client.post(_bulk_url(client_obj), {
            'mode': 'selected',
            'adjustment_ids': ['abc', ''],
        })
        assert resp.status_code == 200
        assert ActualSaleOutlierAdjustment.objects.filter(
            status='CANDIDATE'
        ).count() == 3
        assert 'proposed outlier(s) discarded.' not in resp.content.decode()

    def test_scoped_to_current_client(
        self, django_client, client_obj, outlier_setup, other_client_candidate
    ):
        resp = django_client.post(_bulk_url(client_obj), {'mode': 'all'})
        assert resp.status_code == 200
        assert not ActualSaleOutlierAdjustment.objects.filter(
            actual_sale__client=client_obj, status='CANDIDATE'
        ).exists()
        assert ActualSaleOutlierAdjustment.objects.filter(
            pk=other_client_candidate.pk, status='CANDIDATE'
        ).exists()

    def test_discarded_candidate_frees_row_for_redetection(
        self, django_client, client_obj, outlier_setup
    ):
        cand = outlier_setup['candidates'][0]
        django_client.post(_bulk_url(client_obj), {
            'mode': 'selected',
            'adjustment_ids': [str(cand.pk)],
        })
        actual = ActualSale.objects.get(pk=cand.actual_sale_id)
        assert not hasattr(actual, 'outlier_adjustment')


@pytest.mark.django_db
class TestQueuePageDiscardUI:

    def test_discard_ui_visible_on_candidates_tab_only(
        self, django_client, client_obj, outlier_setup
    ):
        candidates_html = django_client.get(
            _queue_url(client_obj, 'CANDIDATE')
        ).content.decode()
        assert 'Discard selected' in candidates_html
        assert 'Discard all candidates' in candidates_html
        assert 'name="outlier_ids" value="' in candidates_html

        confirmed_html = django_client.get(
            _queue_url(client_obj, 'CONFIRMED')
        ).content.decode()
        assert 'Discard selected' not in confirmed_html
        assert 'name="outlier_ids" value="' not in confirmed_html

        rejected_html = django_client.get(
            _queue_url(client_obj, 'REJECTED')
        ).content.decode()
        assert 'Discard selected' not in rejected_html
        assert 'name="outlier_ids" value="' not in rejected_html

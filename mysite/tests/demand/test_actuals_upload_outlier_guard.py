# mysite/tests/demand/test_actuals_upload_outlier_guard.py

"""
Deleting an ActualSale row cascades to its one-to-one
ActualSaleOutlierAdjustment record. The actuals upload "delete then upload
fresh" flow and the Django admin must warn the user and force an explicit
reconfirmation before such a delete.

Run:
    pytest mysite/tests/demand/test_actuals_upload_outlier_guard.py -v --tb=short
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from mysite.models.demand.actuals import ActualSale
from mysite.models import ActualSaleOutlierAdjustment


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


@pytest.fixture
def outlier_adjustment(db, actual_sale):
    return ActualSaleOutlierAdjustment.objects.create(
        actual_sale=actual_sale,
        qty_adjustment=Decimal('100.000'),
        revenue_adjustment=Decimal('900.00'),
        detected_by='SYSTEM',
        status='CANDIDATE',
    )


@pytest.fixture
def django_client(db, planner_user):
    from django.test import Client
    client = Client()
    client.force_login(planner_user)
    return client


@pytest.fixture
def media_tmp(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _upload_url(client_obj):
    return reverse('demand_ui:actuals_upload', kwargs={'client_id': client_obj.client_id})


def _delete_payload(client_obj, confirmed=False):
    data = {
        'action': 'delete_and_upload',
        'pending_file': 'demand/actuals_imports/pending.csv',
        'pending_period_type': 'month',
        'period_type': 'month',
        'overlap_periods': ['2024-01-01'],
    }
    if confirmed:
        data['confirmed'] = '1'
    return data


@pytest.mark.django_db
class TestUploadOverlapWarning:

    def test_overlap_panel_warns_when_outlier_adjustments_exist(
        self, django_client, client_obj, actual_sale, outlier_adjustment, media_tmp
    ):
        csv_bytes = b'period_start\n2024-01-01\n'
        resp = django_client.post(_upload_url(client_obj), {
            'period_type': 'month',
            'file': SimpleUploadedFile(
                'actuals.csv', csv_bytes, content_type='text/csv',
            ),
        })
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'Period overlap detected' in content
        assert 'Outlier adjustments will be deleted' in content

    def test_overlap_panel_has_no_warning_without_outliers(
        self, django_client, client_obj, actual_sale, media_tmp
    ):
        csv_bytes = b'period_start\n2024-01-01\n'
        resp = django_client.post(_upload_url(client_obj), {
            'period_type': 'month',
            'file': SimpleUploadedFile(
                'actuals.csv', csv_bytes, content_type='text/csv',
            ),
        })
        content = resp.content.decode()
        assert 'Period overlap detected' in content
        assert 'Outlier adjustments will be deleted' not in content


@pytest.mark.django_db
class TestDeleteAndUploadReconfirmation:

    def test_delete_blocked_without_confirmation_when_outliers_exist(
        self, django_client, client_obj, actual_sale, outlier_adjustment
    ):
        resp = django_client.post(
            _upload_url(client_obj), _delete_payload(client_obj)
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'permanently delete outlier adjustments' in content
        assert ActualSale.objects.filter(pk=actual_sale.pk).exists()
        assert ActualSaleOutlierAdjustment.objects.count() == 1

    def test_delete_proceeds_with_confirmation_and_cascades_outliers(
        self, django_client, client_obj, actual_sale, outlier_adjustment, media_tmp
    ):
        resp = django_client.post(
            _upload_url(client_obj), _delete_payload(client_obj, confirmed=True)
        )
        assert resp.status_code == 200
        assert not ActualSale.objects.filter(pk=actual_sale.pk).exists()
        assert ActualSaleOutlierAdjustment.objects.count() == 0

    def test_delete_proceeds_without_confirmation_when_no_outliers(
        self, django_client, client_obj, actual_sale, media_tmp
    ):
        resp = django_client.post(
            _upload_url(client_obj), _delete_payload(client_obj)
        )
        assert resp.status_code == 200
        assert not ActualSale.objects.filter(pk=actual_sale.pk).exists()

    def test_go_back_rerenders_overlap_panel(
        self, django_client, client_obj, actual_sale, outlier_adjustment
    ):
        resp = django_client.post(_upload_url(client_obj), {
            'action': 'overlap',
            'pending_file': 'demand/actuals_imports/pending.csv',
            'pending_period_type': 'month',
            'period_type': 'month',
            'overlap_periods': ['2024-01-01'],
        })
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'Period overlap detected' in content
        assert 'Outlier adjustments will be deleted' in content
        assert ActualSale.objects.filter(pk=actual_sale.pk).exists()


@pytest.mark.django_db
class TestAdminDeleteGuard:

    def test_delete_view_warns_about_outlier_adjustment(
        self, client_obj, actual_sale, outlier_adjustment, db
    ):
        from django.contrib.auth import get_user_model
        from django.test import Client
        superuser = get_user_model().objects.create_superuser(
            username='admin-su', email='su@example.com', password='x',
        )
        c = Client()
        c.force_login(superuser)
        resp = c.get(f'/admin/mysite/actualsale/{actual_sale.pk}/delete/')
        assert resp.status_code == 200
        assert 'will also permanently delete' in resp.content.decode()

    def test_delete_queryset_warns_and_cascades(
        self, client_obj, actual_sale, outlier_adjustment, db
    ):
        from django.contrib import messages
        from django.contrib.admin.sites import AdminSite
        from django.contrib.auth import get_user_model
        from django.contrib.messages.middleware import MessageMiddleware
        from django.contrib.sessions.middleware import SessionMiddleware
        from django.test import RequestFactory

        from mysite.admin.demand import ActualSaleAdmin

        superuser = get_user_model().objects.create_superuser(
            username='admin-su2', email='su2@example.com', password='x',
        )
        factory = RequestFactory()
        request = factory.post('/admin/mysite/actualsale/')
        request.user = superuser
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)

        admin = ActualSaleAdmin(ActualSale, AdminSite())
        admin.delete_queryset(request, ActualSale.objects.filter(pk=actual_sale.pk))

        assert not ActualSale.objects.filter(pk=actual_sale.pk).exists()
        assert ActualSaleOutlierAdjustment.objects.count() == 0
        msgs = [str(m) for m in messages.get_messages(request)]
        assert any('outlier adjustment' in m.lower() for m in msgs)

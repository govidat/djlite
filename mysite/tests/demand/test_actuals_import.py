# mysite/tests/demand/test_actuals_import.py

"""
# Run all demand tests
pytest mysite/tests/demand/ -v

# Run only import tests
pytest mysite/tests/demand/test_actuals_import.py -v --tb=short
pytest mysite/tests/demand/test_export_approval.py -v --tb=short
# Run with coverage
pytest mysite/tests/demand/ --cov=mysite.models.demand --cov=mysite.tasks.demand --cov-report=term-missing
"""

import io
import pytest
import datetime
import pandas as pd
from mysite.models.demand.actuals import ActualSale, ActualSaleImport
from mysite.tasks.demand.import_actuals import _run_import


def make_csv(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def make_import_job(client_obj, period_type='month', tmp_file_content=None,
                    file_name='test_upload.csv', django_storage=None):
    """
    Create an ActualSaleImport record and write content to Django's default
    storage so _run_import() can open it.
    """
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile

    path = default_storage.save(
        f'demand/actuals_imports/{file_name}',
        ContentFile(tmp_file_content or b''),
    )
    return ActualSaleImport.objects.create(
        client=client_obj,
        file_name=path,
        period_type=period_type,
        status='pending',
    )


@pytest.mark.django_db(transaction=True)
class TestActualsImport:

    def test_valid_upload_creates_correct_row_count(
        self, client_obj, leaf_location, active_item, planning_customer
    ):
        """Valid upload → ActualSale row count == file row count."""
        rows = [
            {
                'period_start': '2024-01-01',
                'item_id': 'item-001',
                'location_code': 'LEAF-01',
                'customer_code': 'CUST-01',
                'qty': '100',
                'revenue': '15000.00',
            },
            {
                'period_start': '2024-02-01',
                'item_id': 'item-001',
                'location_code': 'LEAF-01',
                'customer_code': 'CUST-01',
                'qty': '120',
                'revenue': '18000.00',
            },
        ]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        assert job.status == 'done'
        assert job.row_count == 2
        assert ActualSale.objects.filter(client=client_obj).count() == 2

    def test_duplicate_upload_is_idempotent(
        self, client_obj, leaf_location, active_item, planning_customer
    ):
        """Uploading the same file twice: row count stays the same."""
        rows = [{
            'period_start': '2024-01-01', 'item_id': 'item-001',
            'location_code': 'LEAF-01', 'customer_code': 'CUST-01',
            'qty': '100', 'revenue': '',
        }]
        csv_content = make_csv(rows)

        job1 = make_import_job(client_obj, period_type='month',
                               tmp_file_content=csv_content, file_name='dup1.csv')
        _run_import(job1)
        assert ActualSale.objects.filter(client=client_obj).count() == 1

        job2 = make_import_job(client_obj, period_type='month',
                               tmp_file_content=csv_content, file_name='dup2.csv')
        _run_import(job2)
        # Still only 1 row — upsert, not insert
        assert ActualSale.objects.filter(client=client_obj).count() == 1

        job2.refresh_from_db()
        assert job2.status == 'done'

    def test_invalid_item_fk_collected_in_error_log(
        self, client_obj, leaf_location, active_item
    ):
        """Row with unknown item_id → error in error_log; other rows imported."""
        rows = [
            {
                'period_start': '2024-01-01', 'item_id': 'item-001',
                'location_code': 'LEAF-01', 'customer_code': '',
                'qty': '100', 'revenue': '',
            },
            {
                'period_start': '2024-01-01', 'item_id': 'NONEXISTENT',
                'location_code': 'LEAF-01', 'customer_code': '',
                'qty': '50', 'revenue': '',
            },
        ]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        # Valid row imported; bad row skipped
        assert ActualSale.objects.filter(client=client_obj).count() == 1
        assert job.status == 'done'
        assert 'NONEXISTENT' in job.error_log
        assert 'Row 3' in job.error_log   # excel_row = row_num+2, second data row = 3

    def test_missing_required_columns_fails_fast(self, client_obj):
        """File missing required columns → status=failed immediately."""
        bad_csv = b"location_code,qty\nLEAF-01,100\n"
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=bad_csv, file_name='bad.csv')
        _run_import(job)
        job.refresh_from_db()

        assert job.status == 'failed'
        assert 'period_start' in job.error_log
        assert 'item_id' in job.error_log

    def test_invalid_period_start_anchor_collected_as_error(
        self, client_obj, leaf_location, active_item
    ):
        """period_start=2024-01-15 for month bucket → row error, not crash."""
        rows = [{
            'period_start': '2024-01-15',    # wrong anchor — not 1st of month
            'item_id': 'item-001', 'location_code': 'LEAF-01',
            'customer_code': '', 'qty': '100', 'revenue': '',
        }]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        assert ActualSale.objects.filter(client=client_obj).count() == 0
        assert 'period_start' in job.error_log

    def test_unattributed_demand_null_customer(
        self, client_obj, leaf_location, active_item
    ):
        """Blank customer_code → ActualSale.planning_customer is NULL."""
        rows = [{
            'period_start': '2024-01-01', 'item_id': 'item-001',
            'location_code': 'LEAF-01', 'customer_code': '',
            'qty': '75', 'revenue': '',
        }]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)

        sale = ActualSale.objects.get(client=client_obj)
        assert sale.planning_customer is None
        assert sale.qty == pytest.approx(75)
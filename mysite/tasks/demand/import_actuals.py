# mysite/tasks/demand/import_actuals.py

"""
4. Celery Task: `process_actuals_import`

This is the core of Sprint 3B.2. The task:

1. Reads the uploaded file (CSV or Excel) with pandas
2. Resolves all FK columns (item_id → Item.pk, location_code → PlanningLocation.pk, etc.)
3. Validates each row, collecting errors without aborting
4. Bulk-upserts valid rows using `bulk_create(update_conflicts=True)`
5. Updates `ActualSaleImport` with final status and row counts

### 4.1 Expected column headers in the upload file

```
period_start    YYYY-MM-DD   required
item_id         string       required — must match Item.item_id for this client
location_code   string       required — must match PlanningLocation.code
customer_code   string       optional — blank = unattributed (planning_customer=NULL)
qty             decimal      required
revenue         decimal      optional
```

`period_type` is NOT a column in the file — it is specified at upload time
(as a `POST` parameter) and applies to all rows in the file.
"""

import logging
import datetime
import traceback
from decimal import Decimal, InvalidOperation

import pandas as pd
from celery import shared_task
from django.db import transaction

from mysite.models.demand.actuals import (
    ActualSale, ActualSaleImport,
    PERIOD_TYPE_CHOICES, PERIOD_FREQ_MAP,
    compute_period_end, validate_period_start,
)
from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
from mysite.models import Item   # adjust import path to match your project

logger = logging.getLogger(__name__)

# ── Column spec ───────────────────────────────────────────────────────────────
REQUIRED_COLUMNS = {'period_start', 'item_id', 'location_code', 'qty'}
OPTIONAL_COLUMNS = {'customer_code', 'revenue'}
ALL_COLUMNS      = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

# ── Batch size for bulk_create ────────────────────────────────────────────────
BATCH_SIZE = 500


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_actuals_import(self, import_id: int):
    """
    Parse an uploaded actuals file and upsert rows into ActualSale.

    Called by: ActualsUploadView after creating the ActualSaleImport record.
    The file path is stored in ActualSaleImport.file_name.

    Error handling strategy:
      - Row-level errors (bad date, missing FK, invalid qty) are collected
        into ActualSaleImport.error_log. Other rows continue to be processed.
      - File-level errors (file unreadable, missing columns) abort immediately
        and set status='failed'.
      - On task exception, the import is marked failed and the exception is
        re-raised so Celery can retry per max_retries.
    """
    job = None
    try:
        job = ActualSaleImport.objects.get(pk=import_id)
    except ActualSaleImport.DoesNotExist:
        logger.error(f"process_actuals_import: import_id={import_id} not found")
        return

    job.status = 'processing'
    job.save(update_fields=['status'])

    try:
        _run_import(job)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = (job.error_log or '') + f"\n\nFATAL: {traceback.format_exc()}"
        job.save(update_fields=['status', 'error_log'])
        logger.exception(f"process_actuals_import: fatal error on import_id={import_id}")
        raise self.retry(exc=exc)


def _run_import(job: ActualSaleImport):
    """
    Core import logic, separated from the Celery task boilerplate
    so it can be called directly in tests.
    """
    from django.core.files.storage import default_storage

    client      = job.client
    period_type = job.period_type
    errors      = []

    # ── 1. Read file ──────────────────────────────────────────────────────────
    file_path = job.file_name
    try:
        with default_storage.open(file_path, 'rb') as f:
            raw = f.read()
    except FileNotFoundError:
        job.status    = 'failed'
        job.error_log = f"File not found at storage path: {file_path}"
        job.save(update_fields=['status', 'error_log'])
        return

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(
                __import__('io').BytesIO(raw),
                dtype=str,           # read everything as string first
                keep_default_na=False,
            )
        else:
            df = pd.read_excel(
                __import__('io').BytesIO(raw),
                dtype=str,
                keep_default_na=False,
            )
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = f"Could not parse file: {exc}"
        job.save(update_fields=['status', 'error_log'])
        return

    # ── 2. Validate columns ───────────────────────────────────────────────────
    df.columns = [c.strip().lower() for c in df.columns]
    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        job.status    = 'failed'
        job.error_log = f"Missing required columns: {', '.join(sorted(missing_cols))}"
        job.save(update_fields=['status', 'error_log'])
        return

    df = df.fillna('')
    total_rows = len(df)

    # ── 3. Build FK lookup maps (one query each) ──────────────────────────────
    # Fetch all active items for this client indexed by item_id
    item_map = {
        item.item_id: item
        for item in Item.objects.filter(client=client, status='active')
    }
    # Fetch all active planning locations indexed by code
    location_map = {
        loc.code: loc
        for loc in PlanningLocation.objects.filter(client=client, is_active=True)
    }
    # Fetch all active planning customers indexed by code
    customer_map = {
        cust.code: cust
        for cust in PlanningCustomer.objects.filter(client=client, is_active=True)
    }

    # ── 4. Parse and validate each row ───────────────────────────────────────
    valid_records = []

    for row_num, row in df.iterrows():
        row_errors = []
        excel_row  = row_num + 2  # 1-based, +1 for header

        # period_start
        period_start_raw = str(row.get('period_start', '')).strip()
        period_start = None
        try:
            period_start = datetime.date.fromisoformat(period_start_raw)
            validate_period_start(period_start, period_type)
        except ValueError as exc:
            row_errors.append(f"period_start: {exc}")

        # item
        item_id_raw = str(row.get('item_id', '')).strip()
        item = item_map.get(item_id_raw)
        if not item:
            row_errors.append(f"item_id '{item_id_raw}': not found or inactive")

        # location
        location_code_raw = str(row.get('location_code', '')).strip()
        location = location_map.get(location_code_raw)
        if not location:
            row_errors.append(f"location_code '{location_code_raw}': not found or inactive")

        # customer (optional)
        customer_code_raw = str(row.get('customer_code', '')).strip()
        customer = None
        if customer_code_raw:
            customer = customer_map.get(customer_code_raw)
            if not customer:
                row_errors.append(
                    f"customer_code '{customer_code_raw}': not found or inactive"
                )

        # qty
        qty_raw = str(row.get('qty', '')).strip()
        qty = None
        try:
            qty = Decimal(qty_raw)
            if qty < 0:
                raise ValueError("qty cannot be negative")
        except (InvalidOperation, ValueError) as exc:
            row_errors.append(f"qty '{qty_raw}': {exc}")

        # revenue (optional)
        revenue_raw = str(row.get('revenue', '')).strip()
        revenue = None
        if revenue_raw:
            try:
                revenue = Decimal(revenue_raw)
            except InvalidOperation:
                row_errors.append(f"revenue '{revenue_raw}': not a valid decimal")

        if row_errors:
            errors.append(f"Row {excel_row}: {'; '.join(row_errors)}")
            continue

        # Compute period_end
        period_end = compute_period_end(period_start, period_type)

        valid_records.append(
            ActualSale(
                client            = client,
                item              = item,
                planning_location = location,
                planning_customer = customer,
                period_type       = period_type,
                period_start      = period_start,
                period_end        = period_end,
                qty               = qty,
                revenue           = revenue,
                import_batch      = job,
            )
        )

    # ── 5. Bulk upsert in batches ─────────────────────────────────────────────
    # update_conflicts=True makes this idempotent:
    # re-uploading the same file updates qty/revenue rather than failing
    # on the unique_together constraint.
    update_fields = ['qty', 'revenue', 'import_batch']
    unique_fields = [
        'client', 'planning_location', 'item',
        'planning_customer', 'period_type', 'period_start',
    ]

    inserted_count = 0
    with transaction.atomic():
        for i in range(0, len(valid_records), BATCH_SIZE):
            batch = valid_records[i : i + BATCH_SIZE]
            result = ActualSale.objects.bulk_create(
                batch,
                update_conflicts = True,
                unique_fields    = unique_fields,
                update_fields    = update_fields,
            )
            inserted_count += len(result)

    # ── 6. Finalise the import job ────────────────────────────────────────────
    job.row_count = inserted_count
    job.status    = 'done' if not errors else 'done'
    # Always mark done even with row-level errors — partial imports are valid.
    # Errors are inspectable in error_log. Use 'failed' only for fatal errors.
    job.error_log = '\n'.join(errors) if errors else ''
    job.save(update_fields=['row_count', 'status', 'error_log'])

    logger.info(
        f"process_actuals_import: import_id={job.pk} done. "
        f"total={total_rows} valid={inserted_count} errors={len(errors)}"
    )

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_summary_actuals_import(self, import_id: int):
    """
    Parse a location-summary actuals file and upsert into ActualSaleLocation.
    Same file-handling and error-collection pattern as process_actuals_import.
    """
    from mysite.models.demand.actuals import ActualSaleLocation

    job = None
    try:
        job = ActualSaleImport.objects.get(pk=import_id)
    except ActualSaleImport.DoesNotExist:
        logger.error(f"process_summary_actuals_import: import_id={import_id} not found")
        return

    job.status = 'processing'
    job.save(update_fields=['status'])

    try:
        _run_summary_import(job)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = (job.error_log or '') + f"\n\nFATAL: {traceback.format_exc()}"
        job.save(update_fields=['status', 'error_log'])
        raise self.retry(exc=exc)


def _run_summary_import(job: ActualSaleImport):
    from django.core.files.storage import default_storage
    from mysite.models.demand.actuals import ActualSaleLocation

    client      = job.client
    period_type = job.period_type
    errors      = []

    # Read file (identical to _run_import)
    try:
        with default_storage.open(job.file_name, 'rb') as f:
            raw = f.read()
        if job.file_name.endswith('.csv'):
            df = pd.read_csv(__import__('io').BytesIO(raw), dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(__import__('io').BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = str(exc)
        job.save(update_fields=['status', 'error_log'])
        return

    df.columns = [c.strip().lower() for c in df.columns]
    required   = {'period_start', 'location_code', 'total_qty'}
    missing    = required - set(df.columns)
    if missing:
        job.status    = 'failed'
        job.error_log = f"Missing columns: {', '.join(sorted(missing))}"
        job.save(update_fields=['status', 'error_log'])
        return

    df = df.fillna('')

    location_map = {
        loc.code: loc
        for loc in PlanningLocation.objects.filter(client=client, is_active=True)
    }

    valid_records = []

    for row_num, row in df.iterrows():
        row_errors = []
        excel_row  = row_num + 2

        period_start_raw = str(row.get('period_start', '')).strip()
        period_start = None
        try:
            period_start = datetime.date.fromisoformat(period_start_raw)
            validate_period_start(period_start, period_type)
        except ValueError as exc:
            row_errors.append(f"period_start: {exc}")

        location_code_raw = str(row.get('location_code', '')).strip()
        location = location_map.get(location_code_raw)
        if not location:
            row_errors.append(f"location_code '{location_code_raw}': not found")

        total_qty_raw = str(row.get('total_qty', '')).strip()
        total_qty = None
        try:
            total_qty = Decimal(total_qty_raw)
        except InvalidOperation:
            row_errors.append(f"total_qty '{total_qty_raw}': invalid decimal")

        total_revenue_raw = str(row.get('total_revenue', '')).strip()
        total_revenue = None
        if total_revenue_raw:
            try:
                total_revenue = Decimal(total_revenue_raw)
            except InvalidOperation:
                row_errors.append(f"total_revenue '{total_revenue_raw}': invalid decimal")

        if row_errors:
            errors.append(f"Row {excel_row}: {'; '.join(row_errors)}")
            continue

        period_end = compute_period_end(period_start, period_type)

        valid_records.append(
            ActualSaleLocation(
                client            = client,
                planning_location = location,
                period_type       = period_type,
                period_start      = period_start,
                period_end        = period_end,
                total_qty         = total_qty,
                total_revenue     = total_revenue,
                import_batch      = job,
            )
        )

    with transaction.atomic():
        for i in range(0, len(valid_records), BATCH_SIZE):
            batch = valid_records[i : i + BATCH_SIZE]
            ActualSaleLocation.objects.bulk_create(
                batch,
                update_conflicts = True,
                unique_fields    = [
                    'client', 'planning_location', 'period_type', 'period_start'
                ],
                update_fields    = ['total_qty', 'total_revenue', 'import_batch'],
            )

    job.row_count = len(valid_records)
    job.status    = 'done'
    job.error_log = '\n'.join(errors)
    job.save(update_fields=['row_count', 'status', 'error_log'])
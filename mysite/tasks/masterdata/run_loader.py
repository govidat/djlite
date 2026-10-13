# mysite/tasks/masterdata/run_loader.py
#
# Celery task for the Master Data upload UI.
#
# Unlike the demand import (which writes rows itself), this task REUSES the
# existing master data loader programs in scripts/load_*.py, which now accept
# a `data_dir` path argument:
#
#     python manage.py runscript load_03Atheme --script-args dryrun
#
#     from scripts import load_03Atheme
#     load_03Atheme.run(data_dir="/tmp/scratch")   # real run, commits
#
# The task:
#   1. reads the uploaded file(s) from MEDIA storage
#   2. normalises uploaded Excel to CSV (loaders read CSV only)
#   3. validates required columns + client-scope rules
#   4. optionally deletes existing overlapping rows ("Delete & reload")
#   5. hands a temp dir to the loader's run() and parses its summary
#   6. records status/summary/errors on MasterDataImport for the UI poller
#
# Row-scope violations or missing columns abort BEFORE anything is written.

import contextlib
import csv
import importlib
import io
import logging
import re
import tempfile
import traceback
from pathlib import Path

import pandas as pd
from celery import shared_task
from django.apps import apps
from django.db import transaction

from mysite.masterdata.datasets import coerce, get_dataset
from mysite.models import Client
from mysite.models.masterdata import MasterDataImport

logger = logging.getLogger(__name__)

SUMMARY_RE = re.compile(r"\(created=(\d+),\s*updated=(\d+),\s*skipped=(\d+)\)")
MAX_SCOPE_ERRS = 50


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def run_masterdata_import(self, import_id: int):
    """Run a Master Data loader for import_id. pending → processing → done/failed."""
    job = None
    try:
        job = MasterDataImport.objects.select_related("client").get(pk=import_id)
    except MasterDataImport.DoesNotExist:
        logger.error(f"run_masterdata_import: import_id={import_id} not found")
        return

    job.status = "processing"
    job.save(update_fields=["status"])

    try:
        _run(job)
    except Exception as exc:
        job.status = "failed"
        job.error_log = (job.error_log or "") + f"\n\nFATAL: {traceback.format_exc()}"
        job.save(update_fields=["status", "error_log"])
        logger.exception(f"run_masterdata_import: fatal error on import_id={import_id}")
        raise self.retry(exc=exc)


def _run(job: MasterDataImport):
    dataset = get_dataset(job.dataset_key)
    client = job.client
    files = _read_uploads(job)  # ordered list of (stored_name, payload_bytes)

    # ── 0. Multi-file datasets need every file ──────────────────────────
    if len(files) != len(dataset.files):
        job.status = "failed"
        job.error_log = (
            f"Expected {len(dataset.files)} file(s) for {dataset.key}, "
            f"received {len(files)}."
        )
        job.save(update_fields=["status", "error_log"])
        return

    # ── 1. Validate columns ──────────────────────────────────────────────
    errors = _validate_columns(dataset, files)
    if errors:
        job.status = "failed"
        job.error_log = "\n".join(errors)
        job.save(update_fields=["status", "error_log"])
        return

    # ── 2. Validate scope (every row must belong to the target client) ────
    if dataset.scope == "client":
        expected_code = job.target_client_code or (client.client_code if client else "")
        errors = _validate_scope(dataset, expected_code, files[0][1])
        if errors:
            job.status = "failed"
            job.error_log = "\n".join(errors)
            job.save(update_fields=["status", "error_log"])
            return

    # ── 3. Delete & reload + run loader, all in one transaction ─────────
    # The loader's own @transaction.atomic is a nested savepoint; if it
    # raises, the exception unwinds our outer atomic too, rolling back any
    # deletions we already applied. Nothing is half-applied.
    with tempfile.TemporaryDirectory(prefix="mdata-") as tmp:
        notes = []
        with transaction.atomic():
            if job.delete_existing and dataset.natural_key:
                deleted = _delete_overlaps(dataset, job, files[0][1])
                if deleted:
                    notes.append(f"Deleted {deleted} existing overlapping record(s).")

            for i, (stored_name, payload) in enumerate(files):
                expected = dataset.files[i]
                (Path(tmp) / expected).write_bytes(payload)

            output = io.StringIO()
            loader = importlib.import_module(f"scripts.{dataset.script}")
            with contextlib.redirect_stdout(output):
                loader.run(data_dir=tmp)  # commits inside (outer) atomic

    # ── 4. Record results ────────────────────────────────────────────────
    m = SUMMARY_RE.search(output.getvalue())
    if m:
        created, updated, skipped = (int(g) for g in m.groups())
        job.row_count = created + updated + skipped
    else:
        job.row_count = _count_rows(files[0][1])

    tail = [ln.strip() for ln in output.getvalue().strip().splitlines() if ln.strip()][-3:]
    job.summary = "\n".join([*notes, *tail])
    job.status = "done"
    job.save(update_fields=["row_count", "status", "summary", "error_log"])
    logger.info(
        f"run_masterdata_import: import_id={job.pk} {job.dataset_key} done; "
        f"rows={job.row_count}; {job.summary}"
    )


# ── File handling ─────────────────────────────────────────────────────────────

def _read_uploads(job: MasterDataImport):
    """Read + normalise each stored upload into bytes the loaders can read."""
    from django.core.files.storage import default_storage

    stored = [name for name in (job.file_name, job.file_name_b) if name]
    files = []
    for name in stored:
        with default_storage.open(name, "rb") as f:
            raw = f.read()
        files.append((name, _normalise(name, raw)))
    return files


def _normalise(stored_name: str, raw: bytes) -> bytes:
    """Excel → CSV (loaders read CSV only); plain CSV → passthrough (utf-8-sig)."""
    lower = stored_name.lower()
    if lower.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False)
        buf = io.StringIO()
        df.to_csv(buf, index=False, lineterminator="\n")
        return buf.getvalue().encode("utf-8-sig")
    return raw.decode("utf-8-sig", errors="replace").encode("utf-8-sig")


def _count_rows(payload: bytes) -> int:
    text = payload.decode("utf-8-sig", errors="replace")
    n = 0
    for line in text.splitlines():
        if line.strip():
            n += 1
    return max(n - 1, 0)


def _dict_rows(payload: bytes):
    text = payload.decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _header(payload: bytes):
    text = payload.decode("utf-8-sig", errors="replace")
    first = next(iter(text.splitlines()), "")
    return [c.strip().lower() for c in first.split(",")] if first else []


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_columns(dataset, files) -> list:
    errors = []
    for i, columns in enumerate(dataset.columns):
        header = set(_header(files[i][1]))
        missing = [c for c in columns if c.lower() not in header]
        if missing:
            errors.append(
                f"{dataset.files[i]}: missing required columns: {', '.join(missing)}"
            )
    return errors


def _validate_scope(dataset, expected_code: str, payload: bytes) -> list:
    """Every row's client column(s) must equal the import's target client code."""
    errors = []
    rows = _dict_rows(payload)
    for i, row in enumerate(rows, start=2):
        row_errs = []
        for col in dataset.client_columns:
            value = (row.get(col) or "").strip().lower()
            if value != expected_code:
                row_errs.append(f"'{col}' = '{value}' (expected '{expected_code}')")
        if row_errs:
            errors.append(f"Row {i}: " + "; ".join(row_errs))
            if len(errors) >= MAX_SCOPE_ERRS:
                errors.append(f"... and {len(rows) - i} further row(s)")
                break
    return errors


# ── Overlap detection / deletion ──────────────────────────────────────────────

def build_lookups(dataset, scope, client, payload: bytes):
    """Translate each uploaded row into ORM filter lookups via the natural key.

    Returns a de-duplicated list of dicts; rows that can't be fully keyed
    (a mandatory part is blank) are skipped.
    """
    seen = set()
    lookups_list = []
    for row in _dict_rows(payload):
        lookups = {}
        ok = True
        for nk in dataset.natural_key:
            if nk.kind == "client":
                value = (
                    client.client_code
                    if scope == "client"
                    else coerce(nk.kind, row.get(nk.csv))
                )
            else:
                value = coerce(nk.kind, row.get(nk.csv))
                if value is None:
                    ok = False
                    break
            lookups[nk.lookup] = value
        if not ok:
            continue
        fingerprint = tuple(sorted(lookups.items()))
        if fingerprint not in seen:
            seen.add(fingerprint)
            lookups_list.append(lookups)
    return lookups_list


def count_overlaps(dataset, scope, client, payload: bytes) -> int:
    """Number of existing rows that would be overwritten/deleted by this file."""
    model = apps.get_model(dataset.model_label)
    if model is None:
        return 0
    return sum(model.objects.filter(**lu).count() for lu in build_lookups(dataset, scope, client, payload))


def _delete_overlaps(dataset, job: MasterDataImport, payload: bytes) -> int:
    """Best effort: delete existing rows matching any uploaded row's natural key."""
    model = apps.get_model(dataset.model_label)
    if model is None:
        return 0

    deleted = 0
    for lu in build_lookups(dataset, job.scope, job.client, payload):
        qs = model.objects.filter(**lu)
        if qs.exists():
            deleted += qs.delete()[0]
    return deleted
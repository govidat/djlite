# mysite/masterdata_ui/views.py
#
# Client "Master Data" upload UI.
#
# Mirrors the actuals upload flow (demand_ui/views.py) but delegates the
# actual import to the existing loader programs via the Celery task
# mysite/tasks/masterdata/run_loader.py (which in turn uses the registry in
# mysite/masterdata/datasets.py).
#
# Access rules:
#   * Every view requires login + an admin ClientGroup role for the client in
#     the URL.
#   * Global datasets (client=null writes) are only reachable by a superuser
#     signed in under the 'bahushira' client (shows_global_master_data).

import logging
import os
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from mysite.admin.base import _user_has_admin_role
from mysite.masterdata.datasets import dependent_datasets, get_dataset, grouped_for_scope
from mysite.models import MasterDataImport
from mysite.tasks.masterdata.run_loader import _normalise, count_overlaps

logger = logging.getLogger(__name__)

STORAGE_PREFIX = "masterdata_imports"

ALLOWED_EXT = (".csv", ".xlsx", ".xls")


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _shows_global(request) -> bool:
    return bool(
        request.user.is_authenticated
        and request.user.is_superuser
        and request.client
        and request.client.client_code == "bahushira"
    )


def _require_admin(request):
    """Any admin role for the resolved client (or superuser)."""
    client = getattr(request, "client", None)
    user = getattr(request, "user", None)
    if client is None or user is None or not _user_has_admin_role(user, client):
        raise PermissionDenied(
            "You need a client admin role in this client to manage Master Data."
        )
    return client


def _get_dataset(dataset_key):
    try:
        return get_dataset(dataset_key)
    except KeyError:
        raise Http404("Unknown master data dataset.")


def _dispatch(job: MasterDataImport):
    from mysite.tasks.masterdata.run_loader import run_masterdata_import

    run_masterdata_import.delay(job.pk)


def _store(raw: bytes, client_code: str, original_name: str) -> str:
    name = f"{uuid.uuid4().hex[:8]}__{original_name}"
    return default_storage.save(f"{STORAGE_PREFIX}/{client_code}/{name}", ContentFile(raw))


def _job_for_user(request, job_id):
    job = get_object_or_404(MasterDataImport, pk=job_id)
    if job.client and job.client_id != request.client.pk:
        raise PermissionDenied("Not your client's import.")
    if job.client is None and not _shows_global(request):
        raise PermissionDenied("No access to global imports.")
    return job


# ── Pages ─────────────────────────────────────────────────────────────────────

@login_required
def masterdata_list(request, client_code=None):
    client = _require_admin(request)
    shows_global = _shows_global(request)

    q = Q(client=client)
    if shows_global:
        q |= Q(client__isnull=True, scope="global")
    history = MasterDataImport.objects.filter(q).order_by("-uploaded_at")[:20]

    ctx = {
        "client_datasets": grouped_for_scope("client"),
        "global_datasets": grouped_for_scope("global"),
        "shows_global_master_data": shows_global,
        "history": history,
        "active_nav": "masterdata",
    }
    return render(request, "masterdata/masterdata_list.html", ctx)


@login_required
def masterdata_upload(request, client_code=None):
    client = _require_admin(request)
    shows_global = _shows_global(request)

    dataset_key = request.GET.get("dataset") or request.POST.get("dataset_key") or ""
    dataset = _get_dataset(dataset_key) if dataset_key else None

    if dataset is None:
        ctx = {
            "client_datasets": grouped_for_scope("client"),
            "global_datasets": grouped_for_scope("global"),
            "shows_global_master_data": shows_global,
        }
        return render(request, "masterdata/masterdata_list.html", ctx)

    if dataset.is_global and not shows_global:
        raise PermissionDenied("Global master data upload is restricted.")

    if request.method == "POST":
        return _handle_upload(request, client, shows_global, dataset, dataset_key)

    ctx = {
        "dataset": dataset,
        "shows_global_master_data": shows_global,
    }
    if _is_htmx(request):
        return render(request, "masterdata/partials/upload_form.html", ctx)
    return render(request, "masterdata/masterdata_upload.html", ctx)


def _handle_upload(request, client, shows_global, dataset, dataset_key):
    action = request.POST.get("action", "upload")
    pending_file = request.POST.get("pending_file", "").strip()
    pending_file_b = request.POST.get("pending_file_b", "").strip()

    # ── Cancel — drop pending file(s) ────────────────────────────────────
    if action == "cancel":
        for path in (pending_file, pending_file_b):
            if path:
                try:
                    default_storage.delete(path)
                except Exception:
                    pass
        return render(
            request,
            "masterdata/partials/upload_form.html",
            {"dataset": dataset, "shows_global_master_data": shows_global},
        )

    # ── Pending-file actions (from the overlap panel) ────────────────────
    if action in ("override", "delete_and_reload") and pending_file:
        if action == "delete_and_reload" and not request.POST.get("confirmed"):
            dependents = dependent_datasets(dataset)
            if dependents:
                return render(
                    request,
                    "masterdata/partials/overlap_confirm.html",
                    {
                        "dataset": dataset,
                        "dependents": dependents,
                        "pending_file": pending_file,
                        "pending_file_b": pending_file_b,
                        "shows_global_master_data": shows_global,
                    },
                )
        job = MasterDataImport.objects.create(
            client=None if dataset.is_global else client,
            dataset_key=dataset.key,
            scope=dataset.scope,
            uploaded_by=request.user,
            file_name=pending_file,
            file_name_b=pending_file_b if dataset.multi_file else "",
            delete_existing=(action == "delete_and_reload"),
            status="pending",
        )
        _dispatch(job)
        return render(request, "masterdata/partials/upload_status.html", {"job": job})

    # ── Fresh upload — validate, peek for overlaps, then dispatch ────────
    file_a = request.FILES.get("file")
    file_b = request.FILES.get("file_b") if dataset.multi_file else None

    errors = {}
    if not file_a:
        errors["file"] = "Please choose the main file."
    elif os.path.splitext(file_a.name)[1].lower() not in ALLOWED_EXT:
        errors["file"] = f'Unsupported file type "{os.path.splitext(file_a.name)[1]}".'
    if dataset.multi_file:
        if not file_b:
            errors["file_b"] = "This dataset needs a second (text) file."
        elif os.path.splitext(file_b.name)[1].lower() not in ALLOWED_EXT:
            errors["file_b"] = "Unsupported file type for the second file."

    if errors:
        return render(
            request,
            "masterdata/partials/upload_form.html",
            {"dataset": dataset, "errors": errors, "shows_global_master_data": shows_global},
            status=400,
        )

    raw_a = file_a.read()

    if dataset.multi_file:
        raw_b = file_b.read()
        save_path_b = _store(raw_b, client.client_code, file_b.name)
        pending_file_b = save_path_b
    else:
        raw_b = None
        save_path_b = None

    norm_a = _normalise(file_a.name, raw_a)

    overlap = count_overlaps(
        dataset, dataset.scope,
        None if dataset.is_global else client,
        norm_a,
    )

    if overlap:
        save_path = _store(raw_a, client.client_code, file_a.name)
        return render(
            request,
            "masterdata/partials/overlap.html",
            {
                "dataset": dataset,
                "overlap_count": overlap,
                "dependents": dependent_datasets(dataset),
                "pending_file": save_path,
                "pending_file_b": save_path_b,
                "shows_global_master_data": shows_global,
            },
        )

    job = MasterDataImport.objects.create(
        client=None if dataset.is_global else client,
        dataset_key=dataset.key,
        scope=dataset.scope,
        uploaded_by=request.user,
        file_name=_store(raw_a, client.client_code, file_a.name),
        file_name_b=save_path_b or "",
        delete_existing=False,
        status="pending",
    )
    _dispatch(job)
    return render(request, "masterdata/partials/upload_status.html", {"job": job})


@login_required
def masterdata_upload_status(request, job_id, client_code=None):
    """Polled by HTMX while the job is pending/processing."""
    _require_admin(request)
    job = _job_for_user(request, job_id)
    return render(request, "masterdata/partials/upload_status.html", {"job": job})


@login_required
def masterdata_history(request, client_code=None):
    """Full history list (used from the list page 'view all' link)."""
    client = _require_admin(request)
    shows_global = _shows_global(request)
    q = Q(client=client)
    if shows_global:
        q |= Q(client__isnull=True, scope="global")
    history = MasterDataImport.objects.filter(q).order_by("-uploaded_at")
    return render(
        request,
        "masterdata/masterdata_history.html",
        {"history": history, "shows_global_master_data": shows_global},
    )


@login_required
def masterdata_template(request, client_code=None):
    """Stream the sample CSV for a dataset as a download."""
    _require_admin(request)
    dataset = _get_dataset(request.GET.get("dataset", ""))
    if dataset.is_global and not _shows_global(request):
        raise PermissionDenied("Global master data is restricted.")

    try:
        part = int(request.GET.get("part", "0"))
    except ValueError:
        part = 0
    part = min(max(part, 0), len(dataset.files) - 1)

    from django.conf import settings
    from pathlib import Path

    columns = list(dataset.columns[part])
    path = Path(settings.BASE_DIR) / "data" / dataset.files[part]
    if not path.exists():
        raise Http404("Template data not found.")

    import pandas as pd

    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{dataset.files[part]}"'
    df[columns].to_csv(resp, index=False)
    return resp
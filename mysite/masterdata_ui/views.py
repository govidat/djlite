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

import io
import logging
import os
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from mysite.admin.base import _user_has_admin_role
from mysite.masterdata.datasets import dependent_datasets, get_dataset, grouped_for_scope
from mysite.models import Client, MasterDataImport
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
    if _shows_global(request):
        return job
    if job.client and job.client_id != request.client.pk:
        raise PermissionDenied("Not your client's import.")
    if job.client is None:
        raise PermissionDenied("No access to global imports.")
    return job


SESSION_TARGET_KEY = "masterdata_target_client"


def _posted_target_code(request, dataset, shows_global) -> str:
    """Client code the form says to target.

    Falls back to the last client the operator targeted this session, then to
    the acting client (bahushira) on first visit.
    """
    if dataset.is_global or not shows_global:
        return request.client.client_code
    posted = (request.POST.get("target_client") or "").strip().lower()
    if posted:
        return posted
    return request.session.get(SESSION_TARGET_KEY) or request.client.client_code


def _resolve_target(request, dataset, client, shows_global):
    """Resolve the import's target client -> (client, code, error).

    A client admin (or superuser outside bahushira) always targets the acting
    client. The bahushira superuser may target any existing client, or type a
    brand-new code — allowed only for the 03client dataset that provisions it.
    The resolved code is remembered in the session so later uploads default to
    the same client.
    """
    if dataset.is_global or not shows_global:
        return client, client.client_code, ""
    code = _posted_target_code(request, dataset, shows_global)
    target = Client.objects.filter(client_code=code).first()
    if target is None:
        if dataset.key == "03client":
            request.session[SESSION_TARGET_KEY] = code
            return None, code, ""
        return None, "", (
            f'Unknown client code "{code}". '
            "Create it first via the Client (03client) dataset."
        )
    request.session[SESSION_TARGET_KEY] = target.client_code
    return target, target.client_code, ""


def _upload_form_ctx(dataset, shows_global, request, **extra):
    ctx = {
        "dataset": dataset,
        "shows_global_master_data": shows_global,
        "client_choices": list(Client.objects.all().order_by("client_code")),
        "target_client_code": _posted_target_code(request, dataset, shows_global),
    }
    ctx.update(extra)
    return ctx


# ── Pages ─────────────────────────────────────────────────────────────────────

def _grouped_last_imports(scope, user):
    """[(group, [(dataset, last_import|None), ...]), ...].

    `last_import` is this user's most recent MasterDataImport for the dataset,
    used by the list-page cards to show when the user last touched each dataset.
    """
    latest = {}
    for job in (
        MasterDataImport.objects.filter(uploaded_by=user)
        .order_by("dataset_key", "-uploaded_at")
        .only("dataset_key", "status", "uploaded_at", "target_client_code")
    ):
        latest.setdefault(job.dataset_key, job)
    return [
        (group, [(d, latest.get(d.key)) for d in datasets])
        for group, datasets in grouped_for_scope(scope)
    ]


@login_required
def masterdata_list(request, client_code=None):
    client = _require_admin(request)
    shows_global = _shows_global(request)

    if shows_global:
        history = MasterDataImport.objects.all().order_by("-uploaded_at")[:20]
    else:
        history = MasterDataImport.objects.filter(client=client).order_by("-uploaded_at")[:20]

    ctx = {
        "client_datasets": _grouped_last_imports("client", request.user),
        "global_datasets": _grouped_last_imports("global", request.user),
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
            "client_datasets": _grouped_last_imports("client", request.user),
            "global_datasets": _grouped_last_imports("global", request.user),
            "shows_global_master_data": shows_global,
        }
        return render(request, "masterdata/masterdata_list.html", ctx)

    if dataset.is_global and not shows_global:
        raise PermissionDenied("Global master data upload is restricted.")

    if request.method == "POST":
        return _handle_upload(request, client, shows_global, dataset, dataset_key)

    ctx = _upload_form_ctx(dataset, shows_global, request)
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
            _upload_form_ctx(dataset, shows_global, request),
        )

    # ── Resolve the client whose data this import targets ────────────────
    target_client, target_code, target_error = _resolve_target(
        request, dataset, client, shows_global
    )

    # ── Pending-file actions (from the overlap panel) ────────────────────
    if action in ("override", "delete_and_reload") and pending_file:
        if target_error:
            return render(
                request,
                "masterdata/partials/upload_form.html",
                _upload_form_ctx(
                    dataset, shows_global, request, errors={"target_client": target_error}
                ),
                status=400,
            )
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
                        "target_client": target_code,
                    },
                )
        job = MasterDataImport.objects.create(
            client=None if dataset.is_global else target_client,
            target_client_code="" if dataset.is_global else target_code,
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
    if target_error:
        errors["target_client"] = target_error

    if errors:
        return render(
            request,
            "masterdata/partials/upload_form.html",
            _upload_form_ctx(dataset, shows_global, request, errors=errors),
            status=400,
        )

    raw_a = file_a.read()

    if dataset.multi_file:
        raw_b = file_b.read()
        save_path_b = _store(raw_b, target_code, file_b.name)
        pending_file_b = save_path_b
    else:
        raw_b = None
        save_path_b = None

    norm_a = _normalise(file_a.name, raw_a)

    overlap = count_overlaps(
        dataset, dataset.scope,
        None if dataset.is_global else target_client,
        norm_a,
    )

    if overlap:
        save_path = _store(raw_a, target_code, file_a.name)
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
                "target_client": target_code,
            },
        )

    job = MasterDataImport.objects.create(
        client=None if dataset.is_global else target_client,
        target_client_code="" if dataset.is_global else target_code,
        dataset_key=dataset.key,
        scope=dataset.scope,
        uploaded_by=request.user,
        file_name=_store(raw_a, target_code, file_a.name),
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
    if shows_global:
        history = MasterDataImport.objects.all().order_by("-uploaded_at")
    else:
        history = MasterDataImport.objects.filter(client=client).order_by("-uploaded_at")
    return render(
        request,
        "masterdata/masterdata_history.html",
        {"history": history, "shows_global_master_data": shows_global},
    )


@login_required
def masterdata_template(request, client_code=None):
    """Stream the sample file for a dataset as CSV (default) or .xlsx."""
    _require_admin(request)
    dataset = _get_dataset(request.GET.get("dataset", ""))
    if dataset.is_global and not _shows_global(request):
        raise PermissionDenied("Global master data is restricted.")

    try:
        part = int(request.GET.get("part", "0"))
    except ValueError:
        part = 0
    part = min(max(part, 0), len(dataset.files) - 1)

    fmt = (request.GET.get("format") or "csv").strip().lower()
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"

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
    df = df[columns]

    stem = os.path.splitext(dataset.files[part])[0]

    if fmt == "xlsx":
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        resp = HttpResponse(
            buf.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument"
                ".spreadsheetml.sheet"
            ),
        )
        resp["Content-Disposition"] = f'attachment; filename="{stem}.xlsx"'
        return resp

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{dataset.files[part]}"'
    df.to_csv(resp, index=False)
    return resp
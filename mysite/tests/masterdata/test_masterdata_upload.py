# mysite/tests/masterdata/test_masterdata_upload.py

"""
Master Data upload UI + loader task tests.

Run:
    pytest mysite/tests/masterdata -v --tb=short
"""

import importlib
import inspect
from unittest import mock

import pytest
from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from mysite.masterdata.datasets import DATASETS, grouped_for_scope
from mysite.models import MasterDataImport


def _list_url(client_obj):
    return reverse("masterdata_ui:masterdata_list", kwargs={"client_code": client_obj.client_code})


def _upload_url(client_obj):
    return reverse("masterdata_ui:masterdata_upload", kwargs={"client_code": client_obj.client_code})


def _status_url(client_obj, job):
    return reverse(
        "masterdata_ui:masterdata_upload_status",
        kwargs={"client_code": client_obj.client_code, "job_id": job.pk},
    )


def _template_url(client_obj, dataset_key, part=None):
    return reverse("masterdata_ui:masterdata_template", kwargs={"client_code": client_obj.client_code})


# ── Registry / loader API contract ───────────────────────────────────────────

@pytest.mark.django_db
class TestRegistry:

    def test_scope_counts(self):
        client = [d for d in DATASETS if d.scope == "client"]
        globals_ = [d for d in DATASETS if d.scope == "global"]
        assert len(client) == 23
        assert len(globals_) == 9

    def test_every_model_label_resolves(self):
        for d in DATASETS:
            if d.model_label:
                assert apps.get_model(d.model_label) is not None, d.key

    def test_every_loader_accepts_data_dir(self):
        for d in DATASETS:
            mod = importlib.import_module(f"scripts.{d.script}")
            sig = inspect.signature(mod.run)
            assert "data_dir" in sig.parameters, f"{d.script} lacks data_dir"

    def test_files_and_columns_aligned(self):
        for d in DATASETS:
            assert len(d.files) == len(d.columns), d.key
            if d.multi_file:
                assert len(d.files) == 2, d.key

    def test_grouped_scopes_cover_all(self):
        for scope in ("client", "global"):
            all_keys = [d.key for d in DATASETS if d.scope == scope]
            grouped = [d.key for _, ds in grouped_for_scope(scope) for d in ds]
            assert sorted(all_keys) == sorted(grouped)


# ── Visibility (navbar context processor) ────────────────────────────────────

@pytest.mark.django_db
class TestNavContext:

    def _ctx(self, user, client):
        from mysite.context_processors import master_data_nav
        return master_data_nav(type("R", (), {"user": user, "client": client}))

    def test_anonymous_hidden(self, client_obj):
        ctx = self._ctx(AnonymousUser(), client_obj)
        assert ctx["master_data_ui_visible"] is False
        assert ctx["shows_global_master_data"] is False

    def test_non_admin_hidden(self, staff_user, client_obj):
        ctx = self._ctx(staff_user, client_obj)
        assert ctx["master_data_ui_visible"] is False

    def test_admin_visible(self, admin_user, client_obj):
        ctx = self._ctx(admin_user, client_obj)
        assert ctx["master_data_ui_visible"] is True
        assert ctx["shows_global_master_data"] is False

    def test_superuser_bahushira_shows_global(self, superuser, bahushira_obj):
        ctx = self._ctx(superuser, bahushira_obj)
        assert ctx["master_data_ui_visible"] is True
        assert ctx["shows_global_master_data"] is True

    def test_superuser_non_bahushira_no_global(self, superuser, client_obj):
        ctx = self._ctx(superuser, client_obj)
        assert ctx["master_data_ui_visible"] is True
        assert ctx["shows_global_master_data"] is False

    def test_feature_disabled_hides_link(self, admin_user, client_obj):
        from mysite.tests.masterdata.conftest import _feature_control
        _feature_control(client_obj, "master_data", disabled=True)
        ctx = self._ctx(admin_user, client_obj)
        assert ctx["master_data_ui_visible"] is False


# ── Access control ───────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccessControl:

    def test_anonymous_redirected(self, client_obj):
        from django.test import Client
        resp = Client().get(_list_url(client_obj))
        assert resp.status_code in (302, 403)

    def test_non_admin_forbidden(self, client_obj, staff_user, media_tmp):
        from django.test import Client
        c = Client()
        c.force_login(staff_user)
        assert c.get(_list_url(client_obj)).status_code == 403

    def test_admin_list_ok(self, web_client, client_obj):
        resp = web_client.get(_list_url(client_obj))
        assert resp.status_code == 200
        assert "Master Data" in resp.content.decode()


# ── Upload flow ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestUpload:

    def test_fresh_upload_creates_job(self, web_client, client_obj, theme_csv, media_tmp):
        with mock.patch("mysite.masterdata_ui.views._dispatch") as dispatch:
            resp = web_client.post(_upload_url(client_obj), {
                "action": "upload",
                "dataset_key": "03Atheme",
                "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
            })
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Import complete" not in content  # still pending
        job = MasterDataImport.objects.get(dataset_key="03Atheme")
        assert job.status == "pending"
        assert job.scope == "client"
        assert job.client_id == client_obj.pk
        assert job.delete_existing is False
        assert job.file_name.endswith("themes.csv")
        dispatch.assert_called_once_with(job)

    def test_overlap_panel_shown(self, web_client, client_obj, theme_csv, media_tmp):
        from mysite.models import Theme
        Theme.objects.create(client=client_obj, theme_code="solar", name="Solar")
        with mock.patch("mysite.masterdata_ui.views._dispatch") as dispatch:
            resp = web_client.post(_upload_url(client_obj), {
                "action": "upload",
                "dataset_key": "03Atheme",
                "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
            })
        content = resp.content.decode()
        assert "Overlapping records detected" in content
        assert dispatch.call_count == 0  # not dispatched yet — awaiting decision

    def test_override_action_dispatches(self, web_client, client_obj, theme_csv, media_tmp):
        stored = f"masterdata_imports/{client_obj.client_code}/abcd__themes.csv"
        with mock.patch("mysite.masterdata_ui.views._dispatch") as dispatch:
            resp = web_client.post(_upload_url(client_obj), {
                "action": "override",
                "dataset_key": "03Atheme",
                "pending_file": stored,
            })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.delete_existing is False
        assert job.file_name == stored
        dispatch.assert_called_once_with(job)

    def test_delete_and_reload_requires_confirm_when_dependents(self, web_client, client_obj, media_tmp):
        # 20item has dependents (media, variants, attribute values…)
        stored = f"masterdata_imports/{client_obj.client_code}/abcd__items.csv"
        resp = web_client.post(_upload_url(client_obj), {
            "action": "delete_and_reload",
            "dataset_key": "20item",
            "pending_file": stored,
        })
        content = resp.content.decode()
        assert "This delete will cascade" in content
        assert not MasterDataImport.objects.exists()

        resp = web_client.post(_upload_url(client_obj), {
            "action": "delete_and_reload",
            "dataset_key": "20item",
            "pending_file": stored,
            "confirmed": "1",
        })
        job = MasterDataImport.objects.latest("pk")
        assert job.delete_existing is True
        assert job.file_name == stored

    def test_delete_and_reload_no_confirm_when_no_dependents(self, web_client, client_obj, theme_csv, media_tmp):
        stored = "masterdata_imports/TEST01/abcd__themes.csv"
        resp = web_client.post(_upload_url(client_obj), {
            "action": "delete_and_reload",
            "dataset_key": "03Atheme",
            "pending_file": stored,
        })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.delete_existing is True

    def test_missing_columns_fails_job(self, client_obj, admin_user, media_tmp):
        csv_bad = b"theme_code\nsolar\n"  # missing client_code + all name fields
        stored = "masterdata_imports/TEST01/bad.csv"
        from django.core.files.storage import default_storage
        default_storage.save(stored, __import__("django.core.files.base", fromlist=["ContentFile"]).ContentFile(csv_bad))
        job = MasterDataImport.objects.create(
            client=client_obj, dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name=stored, status="pending",
        )
        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "failed"
        assert "missing required columns" in job.error_log

    def test_scope_violation_fails_job(self, client_obj, admin_user, media_tmp):
        from mysite.tests.masterdata.conftest import _theme_csv
        stored = "masterdata_imports/TEST01/other.csv"
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        default_storage.save(stored, ContentFile(_theme_csv("OTHER01")))
        job = MasterDataImport.objects.create(
            client=client_obj, dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name=stored, status="pending",
        )
        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "failed"
        assert "'client_code' = 'other01'" in job.error_log
        from mysite.models import Theme
        assert not Theme.objects.exists()

    def test_full_import_roundtrip(self, client_obj, admin_user, theme_csv, media_tmp):
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        stored = "masterdata_imports/TEST01/ok.csv"
        default_storage.save(stored, ContentFile(theme_csv))
        job = MasterDataImport.objects.create(
            client=client_obj, dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name=stored, status="pending",
        )
        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "done"
        assert job.row_count == 1
        from mysite.models import Theme
        theme = Theme.objects.get(client=client_obj, theme_code="solar")
        assert theme.name_en == "Solar"

    def test_delete_existing_removes_overlap(self, client_obj, admin_user, theme_csv, media_tmp):
        from mysite.models import Theme
        Theme.objects.create(client=client_obj, theme_code="solar", name="Old")
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        stored = "masterdata_imports/TEST01/del.csv"
        default_storage.save(stored, ContentFile(theme_csv))
        job = MasterDataImport.objects.create(
            client=client_obj, dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name=stored,
            delete_existing=True, status="pending",
        )
        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "done"
        assert "Deleted 1 existing overlapping record" in job.summary
        assert Theme.objects.filter(client=client_obj).count() == 1
        assert Theme.objects.get(client=client_obj).name_en == "Solar"


# ── Status + template ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStatusAndTemplate:

    def test_status_partial_polls(self, web_client, client_obj, admin_user, media_tmp):
        job = MasterDataImport.objects.create(
            client=client_obj, dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name="x.csv", status="processing",
        )
        resp = web_client.get(_status_url(client_obj, job))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Processing upload" in content
        assert f"upload/{job.pk}/status/" in content  # HTMX poll present

    def test_template_download(self, web_client, client_obj):
        url = _template_url(client_obj, "03Atheme")
        resp = web_client.get(url, {"dataset": "03Atheme"})
        assert resp.status_code == 200
        header = resp.content.decode().splitlines()[0]
        assert "theme_code" in header
        assert "client_code" in header

    def test_global_template_denied_for_client_admin(self, web_client, client_obj):
        resp = web_client.get(_template_url(client_obj, "01globalval"), {"dataset": "01globalval"})
        assert resp.status_code == 403
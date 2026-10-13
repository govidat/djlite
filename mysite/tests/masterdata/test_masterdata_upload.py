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


# ── Bahushira operator: upload data for other clients ───────────────────────

def _03client_csv(client_code):
    header = ("client_code,language_list,theme_list,nb_title_svg_pre,nb_title_svg_suf,"
              "name_en,name_fr,name_hi,name_ta,nb_title_en,nb_title_fr,nb_title_hi,"
              "nb_title_ta,default_language,parent_id")
    return (header + f"\n{client_code},,,,,\"New {client_code}\",,,,New,,,,en,\n").encode("utf-8")


@pytest.mark.django_db
class TestSuperuserTargetUpload:

    def _operator(self, superuser):
        from django.test import Client
        c = Client()
        c.force_login(superuser)
        return c

    def _upload(self, operator, bahushira_obj, data):
        return operator.post(
            reverse("masterdata_ui:masterdata_upload",
                    kwargs={"client_code": bahushira_obj.client_code}),
            data,
        )

    def test_operator_upload_targets_other_client(self, superuser, bahushira_obj, client_obj,
                                                 theme_csv, media_tmp):
        with mock.patch("mysite.masterdata_ui.views._dispatch") as dispatch:
            resp = self._upload(self._operator(superuser), bahushira_obj, {
                "action": "upload",
                "dataset_key": "03Atheme",
                "target_client": client_obj.client_code,
                "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
            })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.client_id == client_obj.pk
        assert job.target_client_code == "test01"
        assert job.file_name.startswith("masterdata_imports/test01/")
        dispatch.assert_called_once_with(job)

    def test_operator_scope_validated_against_target(self, superuser, bahushira_obj, client_obj,
                                                     admin_user, media_tmp):
        from mysite.tests.masterdata.conftest import _theme_csv
        csv_other = _theme_csv("OTHER01")
        with mock.patch("mysite.masterdata_ui.views._dispatch"):
            resp = self._upload(self._operator(superuser), bahushira_obj, {
                "action": "upload",
                "dataset_key": "03Atheme",
                "target_client": client_obj.client_code,
                "file": SimpleUploadedFile("themes.csv", csv_other, content_type="text/csv"),
            })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.target_client_code == "test01"

        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "failed"
        assert "'client_code' = 'other01' (expected 'test01')" in job.error_log

    def test_operator_overlap_counted_against_target(self, superuser, bahushira_obj, client_obj,
                                                    theme_csv, media_tmp):
        from mysite.models import Theme
        Theme.objects.create(client=client_obj, theme_code="solar", name="Solar")
        with mock.patch("mysite.masterdata_ui.views._dispatch") as dispatch:
            resp = self._upload(self._operator(superuser), bahushira_obj, {
                "action": "upload",
                "dataset_key": "03Atheme",
                "target_client": client_obj.client_code,
                "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
            })
        assert "Overlapping records detected" in resp.content.decode()
        assert dispatch.call_count == 0  # bahushira has no themes — overlap is TEST01's

    def test_operator_unknown_target_rejected(self, superuser, bahushira_obj, client_obj,
                                             theme_csv, media_tmp):
        resp = self._upload(self._operator(superuser), bahushira_obj, {
            "action": "upload",
            "dataset_key": "03Atheme",
            "target_client": "noclient",
            "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
        })
        assert resp.status_code == 400
        assert b"Unknown client code" in resp.content
        assert not MasterDataImport.objects.exists()

    def test_operator_new_client_allowed_only_for_03client(self, superuser, bahushira_obj,
                                                          media_tmp):
        resp = self._upload(self._operator(superuser), bahushira_obj, {
            "action": "upload",
            "dataset_key": "03client",
            "target_client": "newclient",
            "file": SimpleUploadedFile("03client.csv", _03client_csv("newclient"),
                                       content_type="text/csv"),
        })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.client is None
        assert job.target_client_code == "newclient"

    def test_operator_provisions_new_client_end_to_end(self, superuser, bahushira_obj,
                                                       media_tmp):
        from mysite.models import Client
        with mock.patch("mysite.masterdata_ui.views._dispatch"):
            self._upload(self._operator(superuser), bahushira_obj, {
                "action": "upload",
                "dataset_key": "03client",
                "target_client": "newclient",
                "file": SimpleUploadedFile("03client.csv", _03client_csv("newclient"),
                                           content_type="text/csv"),
            })
        job = MasterDataImport.objects.latest("pk")

        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        assert job.status == "done"
        assert Client.objects.filter(client_code="newclient").exists()

    def test_operator_status_poll_cross_client_ok(self, superuser, bahushira_obj,
                                                  client_obj, admin_user, media_tmp):
        job = MasterDataImport.objects.create(
            client=client_obj, target_client_code="test01",
            dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name="x.csv", status="processing",
        )
        resp = self._operator(superuser).get(_status_url(bahushira_obj, job))
        assert resp.status_code == 200

    def test_operator_target_remembered_in_session(self, superuser, bahushira_obj,
                                                   client_obj, theme_csv, media_tmp):
        operator = self._operator(superuser)
        with mock.patch("mysite.masterdata_ui.views._dispatch"):
            self._upload(operator, bahushira_obj, {
                "action": "upload",
                "dataset_key": "03Atheme",
                "target_client": client_obj.client_code,
                "file": SimpleUploadedFile("themes.csv", theme_csv, content_type="text/csv"),
            })
        resp = operator.get(reverse("masterdata_ui:masterdata_upload",
                                    kwargs={"client_code": bahushira_obj.client_code}),
                            {"dataset": "03Atheme"})
        content = resp.content.decode()
        assert 'name="target_client"' in content
        assert 'value="test01"' in content

    def test_operator_history_lists_all_clients(self, superuser, bahushira_obj,
                                               client_obj, admin_user, media_tmp):
        job = MasterDataImport.objects.create(
            client=client_obj, target_client_code="test01",
            dataset_key="03Atheme", scope="client",
            uploaded_by=admin_user, file_name="x.csv", status="done",
        )
        operator = self._operator(superuser)
        resp = operator.get(reverse("masterdata_ui:masterdata_history",
                                    kwargs={"client_code": bahushira_obj.client_code}))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "test01" in content
        assert f'<code>{job.dataset_key}</code>' in content

    def test_operator_list_renders_global_imports(self, superuser, bahushira_obj,
                                                  client_obj, admin_user, media_tmp):
        MasterDataImport.objects.create(
            client=None, target_client_code="", dataset_key="01globalval",
            scope="global", uploaded_by=admin_user, file_name="x.csv", status="done",
        )
        operator = self._operator(superuser)
        resp = operator.get(reverse("masterdata_ui:masterdata_list",
                                    kwargs={"client_code": bahushira_obj.client_code}))
        assert resp.status_code == 200
        assert "global" in resp.content.decode()

    def test_client_admin_target_forced_and_picker_hidden(self, web_client, client_obj,
                                                         theme_csv, media_tmp):
        resp = web_client.get(_upload_url(client_obj), {"dataset": "03Atheme"})
        content = resp.content.decode()
        assert "masterdata-client-list" not in content
        assert 'name="target_client"' not in content  # no target field at all

        resp = web_client.post(_upload_url(client_obj), {
            "action": "override",
            "dataset_key": "03Atheme",
            "target_client": "other01",
            "pending_file": "masterdata_imports/TEST01/forced.csv",
        })
        assert resp.status_code == 200
        job = MasterDataImport.objects.latest("pk")
        assert job.client_id == client_obj.pk
        assert job.target_client_code == job.client.client_code


# ── 03Cnavitem re-upload dedup (regression) ──────────────────────────────────

def _nav_csv(client_code):
    header = ("location,nav_type,url,name_en,name_hi,name_fr,order,hidden,open_in_new_tab,"
              "client_code,page_code,svg_pre,svg_suf,name_ta,parent_name_en")
    row = f"header,page,/home,Home,,,1,0,0,{client_code},,,,," 
    return (header + "\n" + row + "\n").encode("utf-8")


@pytest.mark.django_db
class TestNavItemDuplicates:

    def _nav_client(self):
        from mysite.models import Client
        return Client.objects.create(client_code="navco", name="Nav Co")

    def _run_import(self, client, admin_user, idx, media_tmp):
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        stored = f"masterdata_imports/{client.client_code}/nav{idx}.csv"
        default_storage.save(stored, ContentFile(_nav_csv(client.client_code)))
        job = MasterDataImport.objects.create(
            client=client, target_client_code=client.client_code,
            dataset_key="03Cnavitem", scope="client",
            uploaded_by=admin_user, file_name=stored, status="pending",
        )
        from mysite.tasks.masterdata.run_loader import run_masterdata_import
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()
        return job

    def test_reupload_updates_in_place_no_duplicates(self, admin_user, media_tmp):
        from mysite.models import NavItem
        client = self._nav_client()
        j1 = self._run_import(client, admin_user, 1, media_tmp)
        assert j1.status == "done"
        assert NavItem.objects.filter(client=client).count() == 1

        j2 = self._run_import(client, admin_user, 2, media_tmp)
        assert j2.status == "done"
        rows = NavItem.objects.filter(client=client)
        assert rows.count() == 1  # updated, not duplicated

    def test_stored_display_case_still_matches_overlap(self, admin_user, media_tmp):
        from mysite.models import NavItem
        from mysite.masterdata.datasets import get_dataset
        from mysite.tasks.masterdata.run_loader import count_overlaps
        client = self._nav_client()
        self._run_import(client, admin_user, 1, media_tmp)
        row = NavItem.objects.get(client=client)
        assert row.name_en == "Home"  # display case preserved

        ds = get_dataset("03Cnavitem")
        payload = _nav_csv(client.client_code)
        assert count_overlaps(ds, ds.scope, client, payload) == 1  # case-insensitive match


# ── List-page cards: "last updated by you" ───────────────────────────────────

@pytest.mark.django_db
class TestCardLastImport:

    def _job(self, client_obj, user, dataset_key, status="done"):
        return MasterDataImport.objects.create(
            client=client_obj, target_client_code=client_obj.client_code,
            dataset_key=dataset_key, scope="client",
            uploaded_by=user, file_name="x.csv", status=status,
        )

    def test_card_shows_last_import_by_this_user(self, web_client, client_obj, admin_user, media_tmp):
        from django.utils.timezone import localtime
        job = self._job(client_obj, admin_user, "03Atheme")
        resp = web_client.get(_list_url(client_obj))
        content = resp.content.decode()
        assert "Last by you:" in content
        assert localtime(job.uploaded_at).strftime("%Y-%m-%d %H:%M") in content

    def test_card_hidden_when_only_other_users_imported(self, web_client, client_obj,
                                                         django_user_model, media_tmp):
        other = django_user_model.objects.create(username="someone-else", is_staff=True)
        self._job(client_obj, other, "03Atheme")
        resp = web_client.get(_list_url(client_obj))
        assert "Last by you:" not in resp.content.decode()

    def test_card_shows_target_only_for_operator(self, superuser, bahushira_obj, client_obj,
                                                 media_tmp):
        from django.test import Client
        MasterDataImport.objects.create(
            client=client_obj, target_client_code="test01",
            dataset_key="03Atheme", scope="client",
            uploaded_by=superuser, file_name="x.csv", status="done",
        )
        c = Client()
        c.force_login(superuser)
        resp = c.get(reverse("masterdata_ui:masterdata_list",
                             kwargs={"client_code": bahushira_obj.client_code}))
        content = resp.content.decode()
        assert "Last by you:" in content
        assert "→ test01" in content


# ── 03Dpagecontent: utf-8-sig (BOM) handling (regression) ────────────────────

@pytest.mark.django_db
class TestPageContentBom:

    def test_pagecontent_rows_imported_not_skipped(self, admin_user, media_tmp):
        from django.core.files.storage import default_storage
        from django.core.files.base import ContentFile
        from mysite.models import Client, Page, PageContent
        from mysite.tasks.masterdata.run_loader import run_masterdata_import

        client = Client.objects.create(client_code="pageco", name="PageCo")
        Page.objects.create(client=client, page_code="home")

        header = "client_code,page_code,htmlblob_en,htmlblob_fr,htmlblob_hi,htmlblob_ta"
        row = 'pageco,home,"<div>, hello</div>",,,'
        payload = (header + "\n" + row + "\n").encode("utf-8")

        stored = "masterdata_imports/pageco/pc.csv"
        default_storage.save(stored, ContentFile(payload))
        job = MasterDataImport.objects.create(
            client=client, target_client_code=client.client_code,
            dataset_key="03Dpagecontent", scope="client",
            uploaded_by=admin_user, file_name=stored, status="pending",
        )
        run_masterdata_import.run(job.pk)
        job.refresh_from_db()

        assert job.status == "done"
        assert "skipped=0" in job.summary
        pc = PageContent.objects.get(page__client=client, page__page_code="home")
        assert pc.htmlblob_en == "<div>, hello</div>"
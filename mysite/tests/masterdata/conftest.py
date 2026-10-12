# mysite/tests/masterdata/conftest.py

import datetime

import pytest


@pytest.fixture
def client_obj(db):
    from mysite.models import Client
    return Client.objects.create(client_code="TEST01", name="Test Client")


@pytest.fixture
def bahushira_obj(db):
    from mysite.models import Client
    return Client.objects.create(client_code="bahushira", name="Bahushira")


@pytest.fixture
def admin_user(db, django_user_model, client_obj):
    from mysite.models import ClientGroup, ClientUserMembership
    user = django_user_model.objects.create(
        username="mdata-admin", email="admin@example.com",
        is_staff=True, is_superuser=False,
    )
    grp = ClientGroup.objects.create(
        client=client_obj, clientgroup_code="ADM01",
        name="Admins", role="admin", is_active=True,
    )
    ClientUserMembership.objects.create(user=user, group=grp)
    return user


@pytest.fixture
def staff_user(db, django_user_model, client_obj):
    from mysite.models import ClientGroup, ClientUserMembership
    user = django_user_model.objects.create(username="mdata-staff")
    grp = ClientGroup.objects.create(
        client=client_obj, clientgroup_code="STF01",
        name="Staff", role="staff", is_active=True,
    )
    ClientUserMembership.objects.create(user=user, group=grp)
    return user


@pytest.fixture
def superuser(db, django_user_model):
    return django_user_model.objects.create(
        username="root", is_staff=True, is_superuser=True,
    )


@pytest.fixture
def web_client(db, admin_user):
    from django.test import Client
    c = Client()
    c.force_login(admin_user)
    return c


@pytest.fixture
def media_tmp(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _theme_csv(client_code, theme_code="solar"):
    header = ("theme_code,order,hidden,overrides,is_default,client_code,"
              "themepreset_code,name_en,name_fr,name_hi,name_ta,ltext")
    row = (f"{theme_code},1,0,,1,{client_code},,Solar,Solar,,,")
    return (header + "\n" + row + "\n").encode("utf-8")


@pytest.fixture
def theme_csv(client_obj):
    return _theme_csv(client_obj.client_code)


def _feature_control(client, feature, disabled=True):
    from django.utils import timezone
    from mysite.models import ClientFeatureControl
    now = timezone.now()
    return ClientFeatureControl.objects.create(
        client=client,
        feature=feature,
        is_disabled=disabled,
        from_date=now - datetime.timedelta(days=1),
        to_date=now + datetime.timedelta(days=1),
        message="disabled for test",
    )
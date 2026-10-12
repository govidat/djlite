# mysite/masterdata_ui/urls.py
#
# Mount in project urls.py:
#   path('<str:client_code>/masterdata/', include('mysite.masterdata_ui.urls')),

from django.urls import path

from mysite.masterdata_ui import views

app_name = "masterdata_ui"

urlpatterns = [
    path("", views.masterdata_list, name="masterdata_list"),
    path("upload/", views.masterdata_upload, name="masterdata_upload"),
    path("upload/<int:job_id>/status/", views.masterdata_upload_status, name="masterdata_upload_status"),
    path("history/", views.masterdata_history, name="masterdata_history"),
    path("template/", views.masterdata_template, name="masterdata_template"),
]
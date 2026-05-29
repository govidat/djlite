# mysite/api/demand/urls.py

from django.urls import path
from mysite.api.demand import views

urlpatterns = [
    # ── Hierarchy ──────────────────────────────────────────────────────────
    path(
        'location-hierarchy/',
        views.PlanningLocationHierarchyView.as_view(),
        name='demand-location-hierarchy',
    ),
    path(
        'sales-hierarchy/',
        views.SalesHierarchyView.as_view(),
        name='demand-sales-hierarchy',
    ),

    # ── Actuals (Sprint 3B.2) ──────────────────────────────────────────────
    path(
        'actuals/upload/',
        views.ActualsUploadView.as_view(),
        name='demand-actuals-upload',
    ),
    path(
        'actuals/upload/<int:pk>/',
        views.ActualsUploadStatusView.as_view(),
        name='demand-actuals-upload-status',
    ),
    path(
        'actuals/',
        views.ActualsQueryView.as_view(),
        name='demand-actuals-query',
    ),

    path(
        'actuals/template/',
        views.ActualsTemplateDownloadView.as_view(),
        name='demand-actuals-template',
    ),

]
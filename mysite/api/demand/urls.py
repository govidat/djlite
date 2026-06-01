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
    # ── Forecast Versions ──────────────────────────────────────────────────
    path(
        'forecast-versions/',
        views.ForecastVersionListCreateView.as_view(),
        name='demand-forecast-versions',
    ),
    path(
        'forecast-versions/<int:pk>/',
        views.ForecastVersionDetailView.as_view(),
        name='demand-forecast-version-detail',
    ),
    path(
        'forecast-versions/<int:pk>/lines/',
        views.ForecastVersionLinesView.as_view(),
        name='demand-forecast-version-lines',
    ),
    path(
        'forecast-versions/<int:pk>/aggregates/',
        views.ForecastVersionAggregatesView.as_view(),
        name='demand-forecast-version-aggregates',
    ),
    path(
        'forecast-versions/<int:pk>/approve/',
        views.ForecastVersionApproveView.as_view(),
        name='demand-forecast-version-approve',
    ),

    # ── Series Profiles  (NEW — SeriesProfile additions) ───────────────────
    path(
        'series-profiles/',
        views.SeriesProfileListView.as_view(),
        name='demand-series-profiles',
    ),
    path(
        'series-profiles/<int:pk>/',
        views.SeriesProfileDetailView.as_view(),
        name='demand-series-profile-detail',
    ),
    path(
        'series-profiles/<int:pk>/evaluations/',
        views.SeriesProfileEvaluationsView.as_view(),
        name='demand-series-profile-evaluations',
    ),

    # ── Forecasting Config  (NEW — SeriesProfile additions) ────────────────
    path(
        'forecasting-config/',
        views.ForecastingConfigView.as_view(),
        name='demand-forecasting-config',
    ),     

]
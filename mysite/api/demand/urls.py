# mysite/api/demand/urls.py

from django.urls import path
from mysite.api.demand import views
#from mysite.api.demand.views import forecast_grid
#, override_key_field, override_value_inputs, encode_override_key, override_propagation

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
    path(
        'forecast-versions/<int:pk>/run/',
        views.ForecastVersionRunView.as_view(),
        name='demand-forecast-version-run',
    ),
    path(
        'forecast-versions/<int:pk>/run-status/',
        views.ForecastVersionRunStatusView.as_view(),
        name='demand-forecast-version-run-status',
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
    # Override list + create
    path(
        'forecast-versions/<int:pk>/overrides/',
        views.ForecastOverrideListCreateView.as_view(),
        name='demand-forecast-overrides',
    ),
    # Override detail + delete
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/',
        views.ForecastOverrideDetailView.as_view(),
        name='demand-forecast-override-detail',
    ),
    # Propagation view — which lines did this override touch?
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/affected-lines/',
        views.ForecastOverrideAffectedLinesView.as_view(),
        name='demand-forecast-override-affected-lines',
    ),
    # Custom split-weight management
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/split-weights/',
        views.ForecastOverrideSplitWeightView.as_view(),
        name='demand-forecast-override-split-weights',
    ),

]
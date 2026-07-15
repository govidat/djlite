# mysite/demand_ui/urls.py
#
# HTMX-facing page routes for the Demand Planning client UI.
# These are SEPARATE from mysite/api/demand/urls.py (the JSON API).
# Pages here render HTML and call the API views internally or via
# Django ORM directly — your choice. Below, views call the model layer
# directly (same pattern as your catalogue pages) for simplicity and
# to avoid an HTTP round-trip from server to itself.
#
# Mount in your project urls.py:
#   path('<str:client_id>/demand/', include('mysite.demand_ui.urls')),

from django.urls import path
from mysite.demand_ui import views, views_drilldown, views_htmx

from mysite.views import taxonomy_tree_panel, taxonomy_tree_children
app_name = 'demand_ui'
 
urlpatterns = [
    # ── Dashboard ────────────────────────────────────────────────────────────
    path('', views.dashboard, name='dashboard'),
    # ── Global item search (no version context) ───────────────────────────
    path('items/search/', views_htmx.item_search, name='item_search_global'),

    # ── Taxonomy tree filter widget ──────────────────────────────────
   path('taxonomy-tree/', taxonomy_tree_panel, name='taxonomy_tree_panel'),
    path('taxonomy-tree/<int:node_id>/children/', taxonomy_tree_children, name='taxonomy_tree_children'),

    # ── Forecast Versions ────────────────────────────────────────────────────
    path('versions/', views.version_list, name='version_list'),
    path('versions/create/', views.version_create, name='version_create'),
    path('versions/<int:pk>/', views.version_detail, name='version_detail'),
    path('versions/<int:pk>/run/', views.version_run, name='version_run'),
    path('versions/<int:pk>/run-status/', views.version_run_status, name='version_run_status'),
    path('versions/<int:pk>/approve/', views.version_approve, name='version_approve'),
    path('versions/<int:pk>/copy/', views.version_copy, name='version_copy'),

    # ── Forecast Lines (grid) ────────────────────────────────────────────────
    path('versions/<int:pk>/lines/', views.version_lines, name='version_lines'),
    path('versions/<int:pk>/lines/row/<int:line_id>/', views.version_line_row, name='version_line_row'),

    # ── Aggregates (value summary) ───────────────────────────────────────────
    path('versions/<int:pk>/aggregates/', views.version_aggregates, name='version_aggregates'),

    # ── Drilldown ─────────────────────────────────────────────────────────────
    path('versions/<int:pk>/drilldown/', views_drilldown.drilldown, name='drilldown'),
    path('versions/<int:pk>/drilldown/<int:location_id>/', views_drilldown.drilldown, name='drilldown_location'),
    path('versions/<int:pk>/drilldown/<int:location_id>/items/', views_drilldown.drilldown_items, name='drilldown_items'),
    path('versions/<int:pk>/drilldown/<int:location_id>/override/', views_drilldown.drilldown_override_form, name='drilldown_override_form'),
    path('versions/<int:pk>/drilldown/<int:location_id>/override/preview/', views_drilldown.drilldown_override_preview, name='drilldown_override_preview'),


    # ── Overrides ─────────────────────────────────────────────────────────────
    path('versions/<int:pk>/overrides/', views.override_list, name='override_list'),
    path('versions/<int:pk>/overrides/create/', views.override_create, name='override_create'),
    path('versions/<int:pk>/overrides/<int:override_id>/delete/', views.override_delete, name='override_delete'),
    path('versions/<int:pk>/overrides/<int:override_id>/affected/', views.override_affected_lines, name='override_affected'),
    path('versions/<int:pk>/overrides/<int:override_id>/split-weights/',
        views_htmx.override_split_weights,
        name='override_split_weights'),

    # ── Override HTMX partials ────────────────────────────────────────────────
    path('versions/<int:pk>/partials/override-key-field/', views_htmx.override_key_field, name='override_key_field'),
    path('versions/<int:pk>/partials/override-value-inputs/', views_htmx.override_value_inputs, name='override_value_inputs'),
    path('versions/<int:pk>/partials/encode-override-key/', views_htmx.encode_override_key, name='encode_override_key'),
    path('versions/<int:pk>/overrides/<int:override_id>/propagation/', views_htmx.override_propagation, name='override_propagation'),
    path('versions/<int:pk>/partials/item-search/', views_htmx.item_search, name='item_search'),

    # ── Approval HTMX partials ────────────────────────────────────────────────
    path('versions/<int:pk>/partials/approval-panel/', views_htmx.approval_panel, name='approval_panel'),
    path('versions/<int:pk>/partials/approval-reject/', views_htmx.approval_reject_form, name='approval_reject_form'),
    path('versions/<int:pk>/partials/approval-copy/', views_htmx.approval_copy_form, name='approval_copy_form'),

    # Note: override_propagation currently takes override_id but not pk (version pk) in the URL — you'd want to add it for consistency and to validate the override belongs to the right version.


    # ── Export ────────────────────────────────────────────────────────────────
    path('versions/<int:pk>/export/', views.version_export, name='version_export'),

    # ── Accuracy ──────────────────────────────────────────────────────────────
    path('versions/<int:pk>/accuracy/', views.version_accuracy, name='version_accuracy'),

    # ── Actuals ───────────────────────────────────────────────────────────────
    path('actuals/', views.actuals_list, name='actuals_list'),
    path('actuals/upload/', views.actuals_upload, name='actuals_upload'),
    path('actuals/upload/<int:job_id>/status/', views.actuals_upload_status, name='actuals_upload_status'),
    path('actuals/template/', views.actuals_template_download, name='actuals_template'),

    # ── Series Profiles ───────────────────────────────────────────────────────
    path('series-profiles/', views.series_profile_list, name='series_profile_list'),
    path('series-profiles/<int:pk>/', views.series_profile_detail, name='series_profile_detail'),
    path('series-profiles/<int:pk>/override/', views.series_profile_override, name='series_profile_override'),
    path('series-profiles/recompute/', views.recompute_series_profiles, name='series_profile_recompute'),
    path('series-profiles/recompute/status/', views.recompute_status, name='recompute_status'),    
]

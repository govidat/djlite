from django.urls import path, include
from . import views
from django.http import HttpResponse

def favicon(request):
    return HttpResponse(status=204)   # No Content — silently ignore

urlpatterns = [
#    path('', views.HomeView.as_view(), name='home'),
#    path('<str:pkey>/', views.HomeView.as_view(), name='home'),  # with pkey
#    path('<str:pkey>/home/', views.HomeView.as_view(), name='home'),  # with pkey    
#    path('<str:pkey>/about/', views.AboutView.as_view(), name='about'),  # with pkey
#    path('<str:pkey>/contact/', views.ContactView.as_view(), name='contact'),  # with pkey          

    # this is for persisting theme selection 
    path("set-theme/", views.set_theme, name="set_theme"),
    path("set-country/", views.set_country, name="set_country"),

    #path('', views.ClientPageView.as_view(), name="client_page"), 
    path('', views.landing_page, name='landing'),
    path('<str:client_code>/', views.ClientPageView.as_view(), name="client_page"), 

    # ── Auth ──────────────────────────────────────────────────────────
    path('<str:client_code>/login/', views.client_login, name='client_login'),
    path('<str:client_code>/signup/', views.client_signup, name='client_signup'),
    path('<str:client_code>/logout/', views.client_logout, name='client_logout'),

    # ── Profile ───────────────────────────────────────────────────────
    path('<str:client_code>/profile/', views.customer_profile, name='customer_profile'),
    path('<str:client_code>/profile/onboarding/', views.customer_onboarding, name='customer_onboarding'),

    # ── Addresses ─────────────────────────────────────────────────────
    path('<str:client_code>/profile/addresses/', views.customer_addresses, name='customer_addresses'),
    path('<str:client_code>/profile/addresses/add/', views.add_address, name='add_address'),
    path('<str:client_code>/profile/addresses/<int:address_id>/default/', views.set_default_address, name='set_default_address'),
    path('<str:client_code>/profile/addresses/<int:address_id>/delete/', views.delete_address, name='delete_address'),

    # ── Catalogue ─────────────────────────────────────────────────────
    path('<str:client_code>/catalogue/', views.catalogue_page, name='catalogue_page'),
    path('<str:client_code>/catalogue/filter/', views.catalogue_filter, name='catalogue_filter'),
    path('<str:client_code>/catalogue/<str:item_code>/', views.item_detail, name='item_detail'),

    # --Demand Planning ------------------------------------------------
    #path('api/demand/',  include('mysite.api.demand.urls')),
    path('api/<str:client_code>/demand/', include('mysite.api.demand.urls')),

    # ── Demand Planning — HTML UI (NEW: separate app, client-prefixed) ────
    path('<str:client_code>/demand/', include('mysite.demand_ui.urls')),

    # ── Master Data — HTML upload UI (client-prefixed) ─────────────────────
    path('<str:client_code>/masterdata/', include('mysite.masterdata_ui.urls')),


    # ── Demand Planning — forecast grid page ──────────────────────────────
    #path('demand/forecast-versions/<int:pk>/grid/', views.forecast_grid, name='demand-forecast-grid'),
    # ── Demand Planning — override HTMX partials ──────────────────────────    
    #path('demand/partials/override-key-field/', views.override_key_field, name='demand-override-key-field'),
    #path('demand/partials/override-value-inputs/', views.override_value_inputs, name='demand-override-value-inputs'),
    #path('demand/partials/encode-override-key/', views.encode_override_key, name='demand-encode-override-key'),
    #path('demand/partials/override-propagation/<int:override_id>/', views.override_propagation, name='demand-override-propagation'),

    # ── Demand Planning — approval HTMX partials (Sprint 3B.6) ───────────
    #path('demand/partials/approval-panel/<int:pk>/', views.approval_panel, name='demand-approval-panel'),
    #path('demand/partials/approval-reject-form/<int:pk>/', views.approval_reject_form, name='demand-approval-reject-form'),
    #path('demand/partials/approval-copy-form/<int:pk>/', views.approval_copy_form, name='demand-approval-copy-form'),
    #Add BEFORE <str:client_code>/<str:page>/ catch-all:

    # ── Catch-all (must stay LAST) ────────────────────────────────────────
    path("<str:client_code>/<str:page>/", views.ClientPageView.as_view(), name="client_page"),


    # This is done in Project urls allauth handles the actual auth
    #path('accounts/', include('allauth.urls')),



]
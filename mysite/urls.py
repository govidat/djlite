from django.urls import path

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

    #path('', views.ClientPageView.as_view(), name="client_page"), 
    path('', views.landing_page, name='landing'),
    path('<str:client_id>/', views.ClientPageView.as_view(), name="client_page"), 

    # ── Auth ──────────────────────────────────────────────────────────
    path('<str:client_id>/login/', views.client_login, name='client_login'),
    path('<str:client_id>/signup/', views.client_signup, name='client_signup'),
    path('<str:client_id>/logout/', views.client_logout, name='client_logout'),

    # ── Profile ───────────────────────────────────────────────────────
    path('<str:client_id>/profile/', views.customer_profile, name='customer_profile'),
    path('<str:client_id>/profile/onboarding/', views.customer_onboarding, name='customer_onboarding'),

    # ── Addresses ─────────────────────────────────────────────────────
    path('<str:client_id>/profile/addresses/', views.customer_addresses, name='customer_addresses'),
    path('<str:client_id>/profile/addresses/add/', views.add_address, name='add_address'),
    path('<str:client_id>/profile/addresses/<int:address_id>/default/', views.set_default_address, name='set_default_address'),
    path('<str:client_id>/profile/addresses/<int:address_id>/delete/', views.delete_address, name='delete_address'),


    path("<str:client_id>/<str:page>/", views.ClientPageView.as_view(), name="client_page"),


    # This is done in Project urls allauth handles the actual auth
    #path('accounts/', include('allauth.urls')),



]
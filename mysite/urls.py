from django.urls import path

from . import views

urlpatterns = [
#    path('', views.HomeView.as_view(), name='home'),
#    path('<str:pkey>/', views.HomeView.as_view(), name='home'),  # with pkey
#    path('<str:pkey>/home/', views.HomeView.as_view(), name='home'),  # with pkey    
#    path('<str:pkey>/about/', views.AboutView.as_view(), name='about'),  # with pkey
#    path('<str:pkey>/contact/', views.ContactView.as_view(), name='contact'),  # with pkey          

    path('', views.ClientPageView.as_view(), name="client_page"), 
    path('<str:pkey>/', views.ClientPageView.as_view(), name="client_page"), 
    path("<str:pkey>/<str:page>/", views.ClientPageView.as_view(), name="client_page")
   
]
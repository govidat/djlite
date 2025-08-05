from django.urls import path

from . import views

urlpatterns = [
    path('home_cbv/', views.HomeZappView.as_view(), name='zappcbv'),
    path('home_fbv/', views.home_zapp_fbv, name='zappfbv'),    
]
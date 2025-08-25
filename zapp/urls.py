from django.urls import path

from . import views

urlpatterns = [
    path('home_cbv/', views.HomeZappView.as_view(), name='zappcbv'),
    path('<str:pkey>/home_cbv/', views.HomeZappView.as_view(), name='zappcbv_pk'),  # with pkey  
    path('home_fbv/', views.home_zapp_fbv, name='zappfbv'),    
]
"""
URL configuration for mydj project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
#from django.conf.urls.static import static # debug-toolbar
#from debug_toolbar.toolbar import debug_toolbar_urls  # debug-toolbar

urlpatterns = [
    path('admin/', admin.site.urls),
    path("accounts/", include("allauth.urls")),  # allauth
    #path("zapp/", include("zapp.urls")),  # zapp
    path('i18n/', include('django.conf.urls.i18n')),  # i18n
    path("", include("mysite.urls")),  # mysite
    path('_nested_admin/', include('nested_admin.urls')),
    # this is for persisting theme selection 
    #path("set-theme/", ./mysite.views.set_theme, name="set_theme")

] 
handler404 = 'mysite.views.main.custom_404'
handler500 = 'mysite.views.main.custom_500'
# + debug_toolbar_urls() 

#+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns  # Placing it first can help prevent conflicts

#if settings.DEBUG:
#    # Include django_browser_reload URLs only in DEBUG mode
#    urlpatterns += [
#        path("__reload__/", include("django_browser_reload.urls")),
#    ]

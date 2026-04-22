from .base import *

from .base import _make_templates, _BASE_LOADERS  # underscore names excluded from *



# ── Debug ─────────────────────────────────────────────────────────────
DEBUG = True

SECRET_KEY = 'django-insecure-ma64fm#lcnix#nm=$!gvdq8$y=+cull4rk655v!(ckm*$t6*-$'

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# ── Database ──────────────────────────────────────────────────────────
# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ── Email ─────────────────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
ACCOUNT_EMAIL_VERIFICATION = 'optional'

# ── Debug Toolbar ─────────────────────────────────────────────────────
import sys
import os
TESTING = 'test' in sys.argv or 'PYTEST_VERSION' in os.environ

# debug-toolbar
INTERNAL_IPS = [
    # ...
    "127.0.0.1",
    # ...
] 

if not TESTING:
    INSTALLED_APPS += ['debug_toolbar']
    MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

# # debug-toolbar
DEBUG_TOOLBAR_PANELS = [
    "debug_toolbar.panels.timer.TimerPanel",         # request timings
    "debug_toolbar.panels.sql.SQLPanel",             # SQL queries (important for Postgres)
    "debug_toolbar.panels.cache.CachePanel",         # cache usage (since you use caching for translations)
    "debug_toolbar.panels.templates.TemplatesPanel", # template render info (Jinja2 / Django templates)
    "debug_toolbar.panels.request.RequestPanel",     # request/response headers + cookies
    "debug_toolbar.panels.settings.SettingsPanel",   # useful for checking Django settings
]

DEBUG_TOOLBAR_CONFIG = {
    "INTERCEPT_REDIRECTS": False,  # don’t stop redirects
    "DISABLE_PANELS": {
        "debug_toolbar.panels.history.HistoryPanel",  # avoid the 404 issue
        "debug_toolbar.panels.profiling.ProfilingPanel",  # heavy + rarely useful
    },
}

TEMPLATES = _make_templates(debug=True)   # uncached loaders — changes reflect immediately

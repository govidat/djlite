# mydj/settings/production.py

from .base import *
from .base import _make_templates, _BASE_LOADERS
import os

# ── Core ──────────────────────────────────────────────────────────────
DEBUG = False

# Raises ImproperlyConfigured if missing — no insecure fallback in production
SECRET_KEY = os.environ['DJANGO_SECRET_KEY']

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')

# ── Templates (cached loaders) ────────────────────────────────────────
TEMPLATES = _make_templates(debug=False)

# ── Email ─────────────────────────────────────────────────────────────
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'

# ── Static files (whitenoise) ─────────────────────────────────────────
INSTALLED_APPS = ['whitenoise.runserver_nostatic'] + INSTALLED_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # must be directly after SecurityMiddleware
    *MIDDLEWARE[1:],                               # rest of base MIDDLEWARE, skip SecurityMiddleware
]

STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ── Database (PostgreSQL) ─────────────────────────────────────────────
# Activate once DATABASE_URL is provisioned on Railway/Render.
# Until then, comment this block out and SQLite from base.py is used.
#
# import dj_database_url
# DATABASES = {
#     'default': dj_database_url.config(
#         env='DATABASE_URL',
#         conn_max_age=600,
#         ssl_require=True,
#     )
# }

# ── Cache (Redis) ─────────────────────────────────────────────────────
# Activate once REDIS_URL is provisioned on Railway/Render.
# Until then, LocMemCache from base.py is used.
#
# CACHES = {
#     'default': {
#         'BACKEND': 'django.core.cache.backends.redis.RedisCache',
#         'LOCATION': os.environ['REDIS_URL'],
#     }
# }

# ── Security headers (enable once HTTPS is confirmed working) ─────────
# SECURE_SSL_REDIRECT = True
# SECURE_HSTS_SECONDS = 31536000
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# SECURE_HSTS_PRELOAD = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True


"""
The whitenoise middleware insertion is the trickiest part. WhiteNoise must sit at position 2 
(immediately after SecurityMiddleware) — inserting it anywhere else breaks static file serving. 
The *MIDDLEWARE[1:] slice drops the SecurityMiddleware from base.py's list so it isn't duplicated 
when we rebuild the list from scratch starting with SecurityMiddleware at position 1.

SECRET_KEY = os.environ['DJANGO_SECRET_KEY'] — using direct dict access rather than .get() 
means Django raises KeyError at startup if the env var is missing, which is exactly what you want. 
A missing secret key should be a hard crash, not a silent fallback.

The ALLOWED_HOSTS split — Railway and Render set this as a comma-separated string in one env var. 
So set it on the PaaS dashboard as myapp.railway.app,myapp.com and the .split(',') handles it.

When you're ready to activate Postgres and Redis, it's just uncommenting those two blocks and adding 
dj-database-url to requirements.txt.
"""
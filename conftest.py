# conftest.py  (project root, next to manage.py)
import django
from django.conf import settings


def pytest_configure(config):
    """Called by pytest before collection starts."""
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'djlite.settings')
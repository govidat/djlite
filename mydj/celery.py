# mysite/celery.py  — or wherever your settings package lives

import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')

app = Celery('mysite')
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all INSTALLED_APPS
# Looks for a tasks.py or tasks/ package in each app
app.autodiscover_tasks()
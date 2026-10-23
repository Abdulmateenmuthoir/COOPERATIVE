"""
Celery configuration for the Cooperative Management Platform.

The Celery app is imported from ``config/__init__.py`` so that it is loaded
whenever Django starts. There are no Celery tasks in use yet, so no worker or
broker is required to run the API; the app is only wired up for future use.
"""
import os

from celery import Celery

from config.runtime import settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module())

app = Celery("cooperative_platform")

# Read config from Django settings, using CELERY_ namespace
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task that prints the request info."""
    print(f"Request: {self.request!r}")

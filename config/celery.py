"""Celery configuration for the Cooperative Management Platform."""
import os

from __future__ import absolute_import, unicode_literals

from celery import Celery

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings." + os.getenv("DJANGO_ENV", "dev"),
)

app = Celery("cooperative_platform")

# Read config from Django settings, using CELERY_ namespace
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task that prints the request info."""
    print(f"Request: {self.request!r}")

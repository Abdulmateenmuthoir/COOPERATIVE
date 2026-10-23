"""
WSGI config for the Cooperative Management SaaS Platform.

Gunicorn entry point: ``gunicorn config.wsgi:application``
The settings module is resolved by ``config.runtime`` (DJANGO_ENV / RENDER).
"""
import os

from django.core.wsgi import get_wsgi_application

from config.runtime import settings_module

os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module())

application = get_wsgi_application()

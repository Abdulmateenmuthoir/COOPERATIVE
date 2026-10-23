"""
Health endpoints used by hosting platforms (Render health checks, uptime
monitors) and by load balancers.

Two separate checks on purpose:

    GET /health/         liveness  — is the process up and serving?
    GET /health/ready/   readiness — can it reach the database?

A liveness check must never depend on the database: if Postgres is briefly
unavailable the platform would kill and restart an otherwise healthy container,
which makes an outage worse. Readiness is the check that reports dependency
problems.
"""
import logging

from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def liveness(request):
    """Cheap, dependency-free check."""
    return JsonResponse({"status": "ok"})


def readiness(request):
    """Verifies the database connection with a trivial query."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - report any failure, never raise
        logger.warning("Readiness check failed: %s", exc)
        return JsonResponse(
            {"status": "unavailable", "database": "down"},
            status=503,
        )
    return JsonResponse({"status": "ok", "database": "up"})

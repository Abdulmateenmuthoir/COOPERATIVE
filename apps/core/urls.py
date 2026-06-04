"""
Core app URL configuration — Platform Admin endpoints.
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PlatformStatsView, TenantViewSet

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")
router.register(r"stats", PlatformStatsView, basename="platform-stats")

urlpatterns = [
    path("", include(router.urls)),
]

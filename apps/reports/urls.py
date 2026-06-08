"""Reports app URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ExecutiveDashboardViewSet

router = DefaultRouter()
router.register(r"dashboard", ExecutiveDashboardViewSet, basename="dashboard")

urlpatterns = [
    path("", include(router.urls)),
]

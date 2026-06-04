"""Schedules app URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import ScheduleBatchViewSet

router = DefaultRouter()
router.register(r"", ScheduleBatchViewSet, basename="schedule")

urlpatterns = [
    path("", include(router.urls)),
]

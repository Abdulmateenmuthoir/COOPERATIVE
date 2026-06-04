"""Contributions app URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContributionCycleViewSet,
    ContributionEntryViewSet,
    ContributionPlanViewSet,
    FinancialLedgerViewSet,
    MyContributionsViewSet,
)

router = DefaultRouter()
router.register(r"plans", ContributionPlanViewSet, basename="contribution-plan")
router.register(r"cycles", ContributionCycleViewSet, basename="contribution-cycle")
router.register(r"entries", ContributionEntryViewSet, basename="contribution-entry")
router.register(r"my", MyContributionsViewSet, basename="my-contributions")
router.register(r"ledger", FinancialLedgerViewSet, basename="financial-ledger")

urlpatterns = [
    path("", include(router.urls)),
]

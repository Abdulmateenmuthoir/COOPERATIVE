"""Contributions app URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContributionCycleViewSet,
    ContributionEntryViewSet,
    ContributionPlanViewSet,
    FinancialLedgerViewSet,
    MyContributionsViewSet,
    ShareProductViewSet,
    ShareholdingViewSet,
    ExitRequestViewSet,
    ContributionAgreementViewSet,
    DividendDeclarationViewSet,
    DividendEntitlementViewSet,
)

router = DefaultRouter()
router.register(r"plans", ContributionPlanViewSet, basename="contribution-plan")
router.register(r"cycles", ContributionCycleViewSet, basename="contribution-cycle")
router.register(r"entries", ContributionEntryViewSet, basename="contribution-entry")
router.register(r"my", MyContributionsViewSet, basename="my-contributions")
router.register(r"ledger", FinancialLedgerViewSet, basename="financial-ledger")
router.register(r"shares/products", ShareProductViewSet, basename="share-product")
router.register(r"shares/holdings", ShareholdingViewSet, basename="shareholding")
router.register(r"exit-requests", ExitRequestViewSet, basename="exit-request")
router.register(r"agreements", ContributionAgreementViewSet, basename="contribution-agreement")
router.register(r"dividends/declarations", DividendDeclarationViewSet, basename="dividend-declaration")
router.register(r"dividends/entitlements", DividendEntitlementViewSet, basename="dividend-entitlement")

urlpatterns = [
    path("", include(router.urls)),
]

"""Loans app URL configuration."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EligibilityCheckView,
    LoanApplicationViewSet,
    LoanProductViewSet,
    LoanViewSet,
)

router = DefaultRouter()
router.register(r"products", LoanProductViewSet, basename="loan-product")
router.register(r"applications", LoanApplicationViewSet, basename="loan-application")
router.register(r"eligibility", EligibilityCheckView, basename="loan-eligibility")
router.register(r"active", LoanViewSet, basename="loan")

urlpatterns = [
    path("", include(router.urls)),
]

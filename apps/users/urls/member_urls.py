"""Member management URL patterns."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.users.views import MemberViewSet, PermissionViewSet, RoleViewSet
from apps.contributions.views import MyContributionsViewSet, ShareholdingViewSet, ExitRequestViewSet

router = DefaultRouter()
router.register(r"", MemberViewSet, basename="member")
router.register(r"roles", RoleViewSet, basename="role")
router.register(r"permissions", PermissionViewSet, basename="permission")

urlpatterns = [
    path("me/contributions/summary/", MyContributionsViewSet.as_view({"get": "summary"}), name="member-contribution-summary"),
    path("me/shareholdings/", ShareholdingViewSet.as_view({"get": "mine"}), name="member-shareholdings"),
    path("me/exit-requests/", ExitRequestViewSet.as_view({"get": "list", "post": "create"}), name="member-exit-requests"),
    path("me/exit-settlement/", ExitRequestViewSet.as_view({"get": "estimate"}), name="member-exit-estimate"),
    path("", include(router.urls)),
]

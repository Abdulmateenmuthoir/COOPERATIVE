"""Member management URL patterns."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.users.views import MemberViewSet, PermissionViewSet, RoleViewSet

router = DefaultRouter()
router.register(r"", MemberViewSet, basename="member")
router.register(r"roles", RoleViewSet, basename="role")
router.register(r"permissions", PermissionViewSet, basename="permission")

urlpatterns = [
    path("", include(router.urls)),
]

"""
RBAC permission classes for the Cooperative Management SaaS Platform.

The permission model is hybrid:
- Role-based: A user's role determines general capabilities
- Permission-based: Specific permissions can be granted/revoked per user
- Tenant-scoped: All permissions are evaluated within a tenant context

Permission evaluation order:
1. Check if user has active membership in the current tenant
2. Check for explicit user-level DENY override → block
3. Check for explicit user-level ALLOW override → grant
4. Check if user's role includes the required permission → grant/deny
"""
import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)


class IsPlatformAdmin(BasePermission):
    """
    Allows access only to platform-level administrators (SUPER_ADMIN).
    These are users with is_platform_user=True.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_platform_user
        )


class IsPlatformAdminOrSocietyAdmin(BasePermission):
    """
    Allows platform administrators, or the SOCIETY_ADMIN of the tenant that
    is being acted upon.

    Platform admins may act on any tenant. A society admin may only act on
    the society they administer — the check is made against the resolved
    object, so a society admin can never reach another society's
    configuration even though the route lives under /platform/.

    Use with a viewset that calls `get_object()` (or DRF's
    `check_object_permissions`) so the object-level check runs.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Platform admins bypass role checks.
        if request.user.is_platform_user:
            return True

        from apps.users.models import Membership

        return Membership.objects.filter(
            user=request.user,
            status=Membership.Status.ACTIVE,
            role__code="SOCIETY_ADMIN",
        ).exists()

    def has_object_permission(self, request, view, obj):
        if request.user.is_platform_user:
            return True

        from apps.users.models import Membership

        return Membership.objects.filter(
            tenant=obj,
            user=request.user,
            status=Membership.Status.ACTIVE,
            role__code="SOCIETY_ADMIN",
        ).exists()


class IsTenantMember(BasePermission):
    """
    Allows access only to authenticated users who are active members
    of the current tenant.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.tenant is not None
        )


class HasTenantRole(BasePermission):
    """
    Checks if the user has a specific role within the current tenant.

    Usage:
        class MyView(APIView):
            permission_classes = [HasTenantRole]
            required_roles = ['SOCIETY_ADMIN', 'EXECUTIVE']
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Platform admins bypass role checks
        if request.user.is_platform_user:
            return True

        if not hasattr(request, "tenant") or request.tenant is None:
            return False

        required_roles = getattr(view, "required_roles", [])
        if not required_roles:
            return True  # No specific role required

        from apps.users.models import Membership

        return Membership.objects.filter(
            tenant=request.tenant,
            user=request.user,
            status=Membership.Status.ACTIVE,
            role__code__in=required_roles,
        ).exists()


class HasTenantPermission(BasePermission):
    """
    Checks if the user has a specific permission within the current tenant.
    Evaluates the hybrid RBAC model:
    1. Explicit user deny → False
    2. Explicit user allow → True
    3. Role-based permission → True/False

    The required code(s) can be supplied in two ways:

    1. As a class attribute on the view (used when the whole viewset is gated):

        class MyView(APIView):
            permission_classes = [HasTenantPermission]
            required_permissions = ['view_financials', 'prepare_deductions']

    2. As a constructor argument (used from `get_permissions()` when only some
       actions of a viewset are gated):

        return [HasTenantPermission(permission_code="manage_members")]

    When several codes are given, the caller must hold all of them.
    """

    message = "You do not have permission to perform this action in this society."

    def __init__(self, permission_code=None, permission_codes=None):
        super().__init__()
        explicit = []
        if permission_code:
            explicit.append(permission_code)
        if permission_codes:
            explicit.extend(permission_codes)
        self.explicit_permissions = explicit

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Platform admins bypass permission checks
        if request.user.is_platform_user:
            return True

        if not hasattr(request, "tenant") or request.tenant is None:
            return False

        required_permissions = self.explicit_permissions or getattr(view, "required_permissions", [])
        if not required_permissions:
            return True

        from apps.users.models import Membership, UserPermissionOverride

        # Get user's membership and role
        membership = Membership.objects.filter(
            tenant=request.tenant,
            user=request.user,
            status=Membership.Status.ACTIVE,
        ).select_related("role").first()

        if not membership:
            return False

        for perm_code in required_permissions:
            # 1. Check for explicit DENY override
            deny_exists = UserPermissionOverride.objects.filter(
                tenant=request.tenant,
                user=request.user,
                permission__code=perm_code,
                effect=UserPermissionOverride.Effect.DENY,
            ).exists()

            if deny_exists:
                logger.info(
                    f"Permission DENIED (user override): user={request.user.id}, "
                    f"tenant={request.tenant.id}, permission={perm_code}"
                )
                return False

            # 2. Check for explicit ALLOW override
            allow_exists = UserPermissionOverride.objects.filter(
                tenant=request.tenant,
                user=request.user,
                permission__code=perm_code,
                effect=UserPermissionOverride.Effect.ALLOW,
            ).exists()

            if allow_exists:
                continue  # This permission is granted

            # 3. Check role-based permission
            role_has_perm = membership.role.permissions.filter(code=perm_code).exists()

            if not role_has_perm:
                logger.info(
                    f"Permission DENIED (role): user={request.user.id}, "
                    f"tenant={request.tenant.id}, role={membership.role.code}, "
                    f"permission={perm_code}"
                )
                return False

        return True


class IsExecutiveOrAbove(BasePermission):
    """Shortcut: requires SOCIETY_ADMIN or EXECUTIVE role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_platform_user:
            return True
        if not hasattr(request, "tenant") or request.tenant is None:
            return False

        from apps.users.models import Membership

        return Membership.objects.filter(
            tenant=request.tenant,
            user=request.user,
            status=Membership.Status.ACTIVE,
            role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"],
        ).exists()


class IsSocietyAdmin(BasePermission):
    """Shortcut: requires SOCIETY_ADMIN role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_platform_user:
            return True
        if not hasattr(request, "tenant") or request.tenant is None:
            return False

        from apps.users.models import Membership

        return Membership.objects.filter(
            tenant=request.tenant,
            user=request.user,
            status=Membership.Status.ACTIVE,
            role__code="SOCIETY_ADMIN",
        ).exists()

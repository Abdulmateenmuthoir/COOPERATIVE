"""
Tenant resolution middleware.

This middleware resolves the current tenant for every API request and attaches
it to `request.tenant`. It runs AFTER authentication middleware so that
JWT claims are available.

Tenant resolution order:
1. JWT claim `tenant_id` (primary — set during login)
2. X-Tenant-ID header (fallback — useful for API testing)
3. Subdomain extraction (future — for white-label deployments)

Platform-level endpoints (SUPER_ADMIN operations) bypass tenant resolution
and set request.tenant = None.
"""
import logging

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# URL prefixes that do NOT require tenant context
TENANT_EXEMPT_PREFIXES = (
    "/admin/",
    "/api/schema/",
    "/api/docs/",
    "/api/redoc/",
    "/api/v1/auth/login/",
    "/api/v1/auth/register/",
    "/api/v1/auth/password/reset/",
    "/api/v1/platform/",  # SUPER_ADMIN endpoints handle tenant context differently
    "/__debug__/",
)


class TenantMiddleware(MiddlewareMixin):
    """
    Resolves tenant context for each request.
    Sets request.tenant to the Tenant instance or None for exempt paths.
    """

    def process_request(self, request):
        # Always initialize tenant attribute
        request.tenant = None
        request.tenant_id = None

        # Skip tenant resolution for exempt paths
        if any(request.path.startswith(prefix) for prefix in TENANT_EXEMPT_PREFIXES):
            return None

        user = self._authenticate(request)

        # Not authenticated — let DRF return the 401 from the view.
        if user is None:
            return None

        tenant_id = self._resolve_tenant_id(request, user)

        if not tenant_id:
            # Platform administrators are cross-tenant by design and carry no
            # tenant claim of their own. Let them through without one — the
            # tenant-scoped views still refuse them, because
            # TenantScopedViewSetMixin and IsTenantMember both require a
            # resolved tenant. Without this they could not even log out.
            if user.is_platform_user:
                return None
            return JsonResponse(
                {
                    "error": "Tenant context required",
                    "detail": "A valid tenant identifier must be provided via JWT claim or X-Tenant-ID header.",
                },
                status=400,
            )

        # Import here to avoid circular imports
        from apps.core.models import Tenant

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return JsonResponse(
                {"error": "Tenant not found", "detail": "The specified tenant does not exist."},
                status=404,
            )

        if tenant.status != Tenant.Status.ACTIVE:
            return JsonResponse(
                {
                    "error": "Tenant inactive",
                    "detail": f"This cooperative society is currently {tenant.status}. Contact the platform administrator.",
                },
                status=403,
            )

        # Verify user has membership in this tenant (unless platform user)
        if not user.is_platform_user:
            from apps.users.models import Membership

            has_membership = Membership.objects.filter(
                tenant=tenant,
                user=user,
                status=Membership.Status.ACTIVE,
            ).exists()

            if not has_membership:
                return JsonResponse(
                    {"error": "Access denied", "detail": "You are not a member of this cooperative society."},
                    status=403,
                )

        request.tenant = tenant
        request.tenant_id = tenant.id
        return None

    def _authenticate(self, request):
        """
        Resolve the acting user.

        This middleware runs in the Django stack, which executes *before* DRF
        authenticates inside the view — so on a JWT API call `request.user` is
        still AnonymousUser here. Run the JWT authenticator ourselves to get the
        real user and its tenant claim. Session-authenticated requests (Django
        admin) already have a user and skip this.
        """
        existing = getattr(request, "user", None)
        if existing is not None and existing.is_authenticated:
            return existing

        from rest_framework.exceptions import AuthenticationFailed

        from common.authentication import TenantAwareJWTAuthentication

        try:
            result = TenantAwareJWTAuthentication().authenticate(request)
        except AuthenticationFailed:
            return None

        return result[0] if result else None

    def _resolve_tenant_id(self, request, user):
        """
        Attempt to resolve tenant_id from multiple sources.
        Priority: JWT claim > Header > Subdomain
        """
        # 1. From JWT token claims (most reliable — signed, not client-editable)
        if getattr(user, "current_tenant_id", None):
            return user.current_tenant_id

        # 2. From custom header
        tenant_header = request.META.get("HTTP_X_TENANT_ID")
        if tenant_header:
            return tenant_header

        # 3. From subdomain (future use)
        # host = request.get_host().split(':')[0]
        # parts = host.split('.')
        # if len(parts) > 2:
        #     from apps.core.models import Tenant
        #     tenant = Tenant.objects.filter(code=parts[0]).first()
        #     if tenant:
        #         return str(tenant.id)

        return None

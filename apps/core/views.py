"""
Core app views — Platform Admin (SUPER_ADMIN) tenant management.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsPlatformAdmin, IsPlatformAdminOrSocietyAdmin

from .models import Tenant, TenantBranding, TenantRuleSet, TenantSettings
from .serializers import (
    TenantBrandingSerializer,
    TenantCreateSerializer,
    TenantDetailSerializer,
    TenantListSerializer,
    TenantRuleSetSerializer,
    TenantSettingsSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    """
    Platform-level tenant management.

    Platform admins (SUPER_ADMIN) have full control: they may list, create,
    configure, suspend, activate and deactivate any society.

    Society admins (SOCIETY_ADMIN) may also read and configure *their own*
    society — branding, settings and versioned rules — but never another
    society, and never the platform-level lifecycle actions.

    list:    GET /api/v1/platform/tenants/
    create:  POST /api/v1/platform/tenants/
    retrieve: GET /api/v1/platform/tenants/{id}/
    update:  PUT/PATCH /api/v1/platform/tenants/{id}/
    """

    queryset = Tenant.objects.all()
    permission_classes = [IsPlatformAdmin]
    search_fields = ["name", "code", "institution_name"]
    ordering_fields = ["name", "code", "created_at"]

    # Actions a SOCIETY_ADMIN may perform on their own tenant.
    # These are *action names* (the method names), not URL paths.
    SOCIETY_ADMIN_ACTIONS = ["retrieve", "branding", "tenant_settings", "rules"]

    def get_permissions(self):
        if self.action in self.SOCIETY_ADMIN_ACTIONS:
            return [IsPlatformAdminOrSocietyAdmin()]
        return [IsPlatformAdmin()]

    def get_serializer_class(self):
        if self.action == "list":
            return TenantListSerializer
        if self.action == "create":
            return TenantCreateSerializer
        return TenantDetailSerializer

    def get_queryset(self):
        """
        Platform admins see every tenant. A society admin only ever sees the
        society they administer — the route lives under /platform/ but the
        data is still tenant-isolated.
        """
        qs = super().get_queryset()

        if not self.request.user.is_platform_user:
            from apps.users.models import Membership

            qs = qs.filter(
                users_membership_set__user=self.request.user,
                users_membership_set__status=Membership.Status.ACTIVE,
                users_membership_set__role__code="SOCIETY_ADMIN",
            ).distinct()

        return qs

    # NOTE: GET is allowed so the action resolves to `self.action ==
    # "branding"` for read requests too. A PUT/PATCH-only action leaves
    # `self.action` as None on a GET, which would drop society admins back
    # to the platform-admin permission check.
    @action(detail=True, methods=["get", "put", "patch"])
    def branding(self, request, pk=None):
        """
        Manage tenant branding.
        GET/PUT/PATCH /api/v1/platform/tenants/{id}/branding/
        """
        tenant = self.get_object()
        branding, _ = TenantBranding.objects.get_or_create(tenant=tenant)

        if request.method == "GET":
            return Response(TenantBrandingSerializer(branding).data)

        serializer = TenantBrandingSerializer(branding, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self._audit(request, tenant, "tenant_branding_updated", "Tenant branding updated")
        return Response(serializer.data)

    # NOTE: the method is named `tenant_settings`, not `settings`, because
    # `APIView.settings` is the DRF settings object. A method called
    # `settings` shadows it and every request to this viewset fails with
    # "AttributeError: 'function' object has no attribute
    # 'FORMAT_SUFFIX_KWARG'". The URL path is pinned with `url_path`.
    @action(detail=True, methods=["get", "put", "patch"], url_path="settings")
    def tenant_settings(self, request, pk=None):
        """
        Manage tenant settings.
        GET/PUT/PATCH /api/v1/platform/tenants/{id}/settings/
        """
        tenant = self.get_object()
        settings_obj, _ = TenantSettings.objects.get_or_create(tenant=tenant)

        if request.method == "GET":
            serializer = TenantSettingsSerializer(settings_obj)
            return Response(serializer.data)

        serializer = TenantSettingsSerializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        self._audit(request, tenant, "tenant_settings_updated", "Tenant settings updated")
        return Response(serializer.data)

    @action(detail=True, methods=["get", "post"])
    def rules(self, request, pk=None):
        """
        Manage tenant rule sets.
        GET /api/v1/platform/tenants/{id}/rules/ — List all rule sets
        POST /api/v1/platform/tenants/{id}/rules/ — Create new rule version
        """
        tenant = self.get_object()

        if request.method == "GET":
            rule_sets = TenantRuleSet.objects.filter(tenant=tenant)
            serializer = TenantRuleSetSerializer(rule_sets, many=True)
            return Response(serializer.data)

        # Create new version — auto-increment version number
        latest = TenantRuleSet.objects.filter(tenant=tenant).order_by("-version").first()
        new_version = (latest.version + 1) if latest else 1

        # Deactivate current active rule set
        if latest and latest.active_to is None:
            from django.utils import timezone
            latest.active_to = timezone.now().date()
            latest.save(update_fields=["active_to", "updated_at"])

        serializer = TenantRuleSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant=tenant, version=new_version, created_by=request.user)
        self._audit(
            request,
            tenant,
            "tenant_rules_published",
            f"Rule version {new_version} published",
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _audit(self, request, tenant, action_code, description):
        """Record a configuration change. Platform paths have no request.tenant."""
        from apps.auditing.services import create_audit_log

        create_audit_log(
            tenant=tenant,
            actor=request.user if request.user.is_authenticated else None,
            action_code=action_code,
            action_category="update",
            description=description,
            entity_type="Tenant",
            entity_id=str(tenant.id),
            request=request,
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        """Suspend a tenant. POST /api/v1/platform/tenants/{id}/suspend/"""
        tenant = self.get_object()
        tenant.status = Tenant.Status.SUSPENDED
        tenant.save(update_fields=["status", "updated_at"])
        return Response({"detail": f"Tenant '{tenant.name}' has been suspended."})

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """Activate a tenant. POST /api/v1/platform/tenants/{id}/activate/"""
        tenant = self.get_object()
        tenant.status = Tenant.Status.ACTIVE
        tenant.save(update_fields=["status", "updated_at"])
        return Response({"detail": f"Tenant '{tenant.name}' has been activated."})

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """Deactivate a tenant. POST /api/v1/platform/tenants/{id}/deactivate/"""
        tenant = self.get_object()
        tenant.status = Tenant.Status.DEACTIVATED
        tenant.save(update_fields=["status", "updated_at"])
        return Response({"detail": f"Tenant '{tenant.name}' has been deactivated."})


class PlatformStatsView(viewsets.ViewSet):
    """
    Platform-wide statistics for SUPER_ADMIN dashboard.
    GET /api/v1/platform/stats/
    """

    permission_classes = [IsPlatformAdmin]

    def list(self, request):
        from apps.users.models import Membership, UserAccount

        stats = {
            "total_tenants": Tenant.objects.count(),
            "active_tenants": Tenant.objects.filter(status=Tenant.Status.ACTIVE).count(),
            "suspended_tenants": Tenant.objects.filter(status=Tenant.Status.SUSPENDED).count(),
            "total_users": UserAccount.objects.count(),
            "total_memberships": Membership.objects.filter(status="active").count(),
        }
        return Response(stats)

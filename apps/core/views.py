"""
Core app views — Platform Admin (SUPER_ADMIN) tenant management.
"""
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.permissions import IsPlatformAdmin

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
    Platform-level tenant management. Only accessible by SUPER_ADMIN.

    list:    GET /api/v1/platform/tenants/
    create:  POST /api/v1/platform/tenants/
    retrieve: GET /api/v1/platform/tenants/{id}/
    update:  PUT/PATCH /api/v1/platform/tenants/{id}/
    """

    queryset = Tenant.objects.all()
    permission_classes = [IsPlatformAdmin]

    def get_serializer_class(self):
        if self.action == "list":
            return TenantListSerializer
        if self.action == "create":
            return TenantCreateSerializer
        return TenantDetailSerializer

    @action(detail=True, methods=["put", "patch"])
    def branding(self, request, pk=None):
        """
        Manage tenant branding.
        PUT/PATCH /api/v1/platform/tenants/{id}/branding/
        """
        tenant = self.get_object()
        branding, _ = TenantBranding.objects.get_or_create(tenant=tenant)
        serializer = TenantBrandingSerializer(branding, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["get", "put", "patch"])
    def settings(self, request, pk=None):
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
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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

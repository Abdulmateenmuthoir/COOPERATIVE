"""
Core app serializers for tenant management.
"""
from rest_framework import serializers

from .models import Tenant, TenantBranding, TenantMemberImport, TenantRuleSet, TenantSettings


class TenantBrandingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantBranding
        fields = ["logo_url", "primary_color", "secondary_color", "app_name_override"]


class TenantSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSettings
        fields = [
            "currency",
            "timezone",
            "locale",
            "financial_year_start_month",
            "notification_policy",
        ]


class TenantRuleSetSerializer(serializers.ModelSerializer):
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = TenantRuleSet
        fields = [
            "id",
            "version",
            "active_from",
            "active_to",
            "rules",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "version", "created_at"]


class TenantListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for tenant listing."""

    class Meta:
        model = Tenant
        fields = [
            "id",
            "code",
            "name",
            "status",
            "onboarding_state",
            "institution_name",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class TenantDetailSerializer(serializers.ModelSerializer):
    """Full detail serializer for tenant management."""

    branding = TenantBrandingSerializer(read_only=True)
    settings = TenantSettingsSerializer(read_only=True)
    active_rule_set = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            "id",
            "code",
            "name",
            "description",
            "status",
            "onboarding_state",
            "primary_contact_email",
            "primary_contact_phone",
            "institution_name",
            "address",
            "branding",
            "settings",
            "active_rule_set",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_active_rule_set(self, obj):
        active = obj.rule_sets.filter(active_to__isnull=True).first()
        if active:
            return TenantRuleSetSerializer(active).data
        return None


class TenantCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new tenant (onboarding)."""

    class Meta:
        model = Tenant
        fields = [
            "code",
            "name",
            "description",
            "primary_contact_email",
            "primary_contact_phone",
            "institution_name",
            "address",
        ]

    def create(self, validated_data):
        tenant = super().create(validated_data)
        # Auto-create branding and settings with defaults
        TenantBranding.objects.create(tenant=tenant)
        TenantSettings.objects.create(tenant=tenant)
        return tenant


class TenantMemberImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantMemberImport
        fields = [
            "id",
            "source_file_url",
            "status",
            "total_rows",
            "successful_rows",
            "failed_rows",
            "error_log",
            "created_at",
        ]
        read_only_fields = ["id", "status", "total_rows", "successful_rows", "failed_rows", "error_log", "created_at"]

from django.contrib import admin

from .models import Tenant, TenantBranding, TenantMemberImport, TenantRuleSet, TenantSettings


class TenantBrandingInline(admin.StackedInline):
    model = TenantBranding
    extra = 0


class TenantSettingsInline(admin.StackedInline):
    model = TenantSettings
    extra = 0


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "status", "onboarding_state", "primary_contact_email", "created_at"]
    list_filter = ["status", "onboarding_state"]
    search_fields = ["name", "code", "primary_contact_email"]
    readonly_fields = ["id", "created_at", "updated_at"]
    inlines = [TenantBrandingInline, TenantSettingsInline]


@admin.register(TenantRuleSet)
class TenantRuleSetAdmin(admin.ModelAdmin):
    list_display = ["tenant", "version", "active_from", "active_to", "is_active"]
    list_filter = ["tenant"]
    readonly_fields = ["id", "created_at", "updated_at"]


@admin.register(TenantMemberImport)
class TenantMemberImportAdmin(admin.ModelAdmin):
    list_display = ["tenant", "status", "total_rows", "successful_rows", "failed_rows", "created_at"]
    list_filter = ["status", "tenant"]
    readonly_fields = ["id", "created_at", "updated_at"]

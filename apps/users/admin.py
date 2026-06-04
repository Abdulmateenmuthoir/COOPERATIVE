from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    MemberProfile,
    Membership,
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserPermissionOverride,
)


@admin.register(UserAccount)
class UserAccountAdmin(BaseUserAdmin):
    list_display = ["email", "first_name", "last_name", "status", "is_platform_user", "is_staff", "date_joined"]
    list_filter = ["status", "is_platform_user", "is_staff"]
    search_fields = ["email", "first_name", "last_name"]
    ordering = ["email"]
    readonly_fields = ["id", "date_joined", "last_login"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name", "phone")}),
        ("Status", {"fields": ("status", "is_active")}),
        ("Platform", {"fields": ("is_platform_user", "is_staff", "is_superuser")}),
        ("Dates", {"fields": ("date_joined", "last_login")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "first_name", "last_name", "password1", "password2")}),
    )


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 1


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "scope", "tenant"]
    list_filter = ["scope"]
    inlines = [RolePermissionInline]


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ["code", "module", "description"]
    list_filter = ["module"]
    search_fields = ["code", "description"]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant", "role", "status", "created_at"]
    list_filter = ["status", "role", "tenant"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant", "employee_no", "payroll_no", "employment_status"]
    list_filter = ["employment_status", "tenant"]
    search_fields = ["user__email", "employee_no", "payroll_no"]


@admin.register(UserPermissionOverride)
class UserPermissionOverrideAdmin(admin.ModelAdmin):
    list_display = ["user", "tenant", "permission", "effect", "granted_by"]
    list_filter = ["effect", "tenant"]

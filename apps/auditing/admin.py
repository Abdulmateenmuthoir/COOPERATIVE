from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "actor_user", "tenant", "action_code", "action_category", "entity_type", "entity_id"]
    list_filter = ["action_category", "entity_type", "tenant"]
    search_fields = ["action_code", "description", "actor_user__email"]
    readonly_fields = [
        "id", "tenant", "actor_user", "action_code", "action_category", "description",
        "entity_type", "entity_id", "before_state", "after_state", "ip_address",
        "user_agent", "created_at",
    ]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

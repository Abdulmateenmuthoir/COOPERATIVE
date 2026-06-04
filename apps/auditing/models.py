"""
Auditing app — Immutable audit log for all critical platform actions.

Every action — loan approval, role change, contribution update, data export —
is logged with timestamps, the actor's identity, and before/after state.
Audit records are append-only: no update or delete operations.
"""
import uuid

from django.db import models


class AuditLog(models.Model):
    """
    Immutable audit trail entry.
    Captures who did what, when, and the before/after state of the affected entity.
    """

    class ActionCategory(models.TextChoices):
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        EXPORT = "export", "Export"
        LOGIN = "login", "Login"
        ROLE_CHANGE = "role_change", "Role Change"
        PERMISSION_CHANGE = "permission_change", "Permission Change"
        STATUS_CHANGE = "status_change", "Status Change"
        SYSTEM = "system", "System Action"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="audit_logs",
        db_index=True,
    )
    actor_user = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action_code = models.CharField(max_length=50, db_index=True)
    action_category = models.CharField(
        max_length=30, choices=ActionCategory.choices, default=ActionCategory.UPDATE, db_index=True
    )
    description = models.TextField(blank=True, default="")

    # Entity being acted upon
    entity_type = models.CharField(max_length=100, db_index=True, help_text="Model name, e.g., 'Loan', 'Membership'")
    entity_id = models.CharField(max_length=255, blank=True, default="")

    # State snapshots
    before_state = models.JSONField(null=True, blank=True, help_text="Entity state before the action.")
    after_state = models.JSONField(null=True, blank=True, help_text="Entity state after the action.")

    # Request metadata
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "created_at"]),
            models.Index(fields=["tenant", "entity_type", "entity_id"]),
            models.Index(fields=["actor_user", "created_at"]),
        ]
        # Prevent modification of audit records
        managed = True

    def __str__(self):
        actor = self.actor_user.email if self.actor_user else "system"
        return f"[{self.created_at}] {actor}: {self.action_code} on {self.entity_type}"

    def save(self, *args, **kwargs):
        # Prevent updates to existing audit records
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError("Audit log entries are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit log entries cannot be deleted.")

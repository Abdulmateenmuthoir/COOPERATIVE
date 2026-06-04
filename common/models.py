"""
Base model classes for the Cooperative Management SaaS Platform.

All tenant-owned data models inherit from TenantScopedModel, which ensures:
1. Every record carries a tenant foreign key
2. created_at and updated_at timestamps are automatic
3. UUID primary keys prevent enumeration attacks
"""
import uuid

from django.db import models


class TimestampedModel(models.Model):
    """
    Abstract base providing automatic created_at / updated_at timestamps.
    All models in the platform should inherit from this (or TenantScopedModel).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.__class__.__name__}({self.id})"


class TenantScopedModel(TimestampedModel):
    """
    Abstract base for all tenant-owned data.

    Every model that stores cooperative-specific data MUST inherit from this.
    The tenant field creates the data isolation boundary — combined with
    TenantScopedQuerySetMixin on views, this ensures cross-tenant data
    leakage is structurally impossible.
    """

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteModel(models.Model):
    """
    Mixin for soft-delete support.
    Records are marked as deleted instead of being physically removed.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def soft_delete(self):
        from django.utils import timezone
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at", "updated_at"])

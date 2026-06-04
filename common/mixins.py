"""
Tenant-scoped queryset mixins for DRF ViewSets.

These mixins ensure that all database queries are automatically scoped to the
current tenant. Every tenant-owned ViewSet MUST inherit from
TenantScopedViewSetMixin to prevent cross-tenant data leakage.
"""
from rest_framework.exceptions import ValidationError


class TenantScopedViewSetMixin:
    """
    Automatically filters all querysets by the current request's tenant
    and injects tenant on creation.

    Usage:
        class MyViewSet(TenantScopedViewSetMixin, ModelViewSet):
            queryset = MyModel.objects.all()
            serializer_class = MySerializer
    """

    def get_queryset(self):
        """Filter queryset to only include records from the current tenant."""
        qs = super().get_queryset()

        if not hasattr(self.request, "tenant") or self.request.tenant is None:
            # If no tenant context, return empty queryset as safety measure
            return qs.none()

        return qs.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        """Automatically inject tenant on record creation."""
        if not hasattr(self.request, "tenant") or self.request.tenant is None:
            raise ValidationError({"tenant": "Tenant context is required to create records."})

        serializer.save(tenant=self.request.tenant)

    def perform_update(self, serializer):
        """Save updates without changing tenant."""
        serializer.save()


class TenantScopedCreateMixin:
    """
    Mixin for views that only need tenant injection on create,
    without queryset filtering (e.g., nested resources).
    """

    def perform_create(self, serializer):
        if not hasattr(self.request, "tenant") or self.request.tenant is None:
            raise ValidationError({"tenant": "Tenant context is required."})
        serializer.save(tenant=self.request.tenant)


class CreatedByMixin:
    """
    Mixin that automatically sets the `created_by` field to the current user
    when creating records.
    """

    def perform_create(self, serializer):
        super().perform_create(serializer)
        # If the model has a created_by field, set it
        if hasattr(serializer.Meta.model, "created_by"):
            serializer.save(created_by=self.request.user)

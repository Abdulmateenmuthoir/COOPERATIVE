"""
Notifications views.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from common.mixins import TenantScopedViewSetMixin
from common.permissions import IsTenantMember
from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Users view their own notifications.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        return Notification.objects.filter(
            tenant=self.request.tenant, user=self.request.user
        )

    @action(detail=True, methods=["post"], url_path="read")
    def mark_as_read(self, request, pk=None):
        """Mark a notification as read."""
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=["is_read", "updated_at"])
        return Response({"detail": "Marked as read."})

    @action(detail=False, methods=["post"], url_path="read-all")
    def mark_all_as_read(self, request):
        """Mark all notifications as read."""
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({"detail": "All notifications marked as read."})

"""
Notifications models.
Records in-app notifications and tracks delivery status for Email/SMS.
"""
from django.db import models
from common.models import TenantScopedModel


class Notification(TenantScopedModel):
    """
    An individual notification sent to a user.
    """
    class NotificationType(models.TextChoices):
        INFO = "info", "Information"
        WARNING = "warning", "Warning"
        SUCCESS = "success", "Success"
        ERROR = "error", "Error"

    class Channel(models.TextChoices):
        IN_APP = "in_app", "In-App"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        ALL = "all", "All Channels"

    user = models.ForeignKey(
        "users.UserAccount", on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(
        max_length=20, choices=NotificationType.choices, default=NotificationType.INFO
    )
    is_read = models.BooleanField(default=False)
    
    # Context data (e.g. {"loan_id": "123"})
    context_data = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} - {self.title}"

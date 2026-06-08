"""
Notifications serializers.
"""
from rest_framework import serializers
from .models import Notification

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id", "title", "message", "notification_type", 
            "is_read", "context_data", "created_at"
        ]
        read_only_fields = ["id", "title", "message", "notification_type", "context_data", "created_at"]

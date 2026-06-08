"""
Notification service.
Used to dispatch in-app, email, and SMS notifications.
"""
from .models import Notification

def send_notification(user, title, message, notification_type=Notification.NotificationType.INFO, context_data=None, channels=[Notification.Channel.IN_APP]):
    """
    Core function to dispatch notifications.
    """
    # 1. Create In-App Notification (Always created if IN_APP or ALL is selected)
    if Notification.Channel.IN_APP in channels or Notification.Channel.ALL in channels:
        Notification.objects.create(
            tenant=user.memberships.first().tenant if user.memberships.exists() else None,
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            context_data=context_data
        )

    # 2. Dispatch Email (Using Celery - Placeholder)
    if Notification.Channel.EMAIL in channels or Notification.Channel.ALL in channels:
        # from .tasks import send_email_task
        # send_email_task.delay(user.email, title, message)
        pass

    # 3. Dispatch SMS (Using Celery - Placeholder)
    if Notification.Channel.SMS in channels or Notification.Channel.ALL in channels:
        # from .tasks import send_sms_task
        # send_sms_task.delay(user.phone, message)
        pass


def notify_membership_pending(membership):
    """Called when a new member registers and needs approval."""
    send_notification(
        user=membership.user,
        title="Membership Pending Approval",
        message=f"Your membership request for {membership.tenant.name} is pending approval.",
        notification_type=Notification.NotificationType.INFO
    )


def notify_membership_approved(membership):
    """Called when a member is approved."""
    send_notification(
        user=membership.user,
        title="Membership Approved",
        message=f"Welcome! Your membership for {membership.tenant.name} has been approved.",
        notification_type=Notification.NotificationType.SUCCESS,
        channels=[Notification.Channel.IN_APP, Notification.Channel.EMAIL]
    )

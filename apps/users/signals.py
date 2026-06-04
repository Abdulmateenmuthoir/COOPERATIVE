"""
Users app signals — triggered on key user/membership events.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Membership

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Membership)
def on_membership_created(sender, instance, created, **kwargs):
    """Log membership creation and trigger notifications."""
    if created:
        logger.info(
            f"Membership created: user={instance.user.email}, "
            f"tenant={instance.tenant.code}, role={instance.role.code}, "
            f"status={instance.status}"
        )

        # Trigger notification for pending membership (approval request)
        if instance.status == Membership.Status.PENDING:
            try:
                from apps.notifications.services import notify_membership_pending
                notify_membership_pending(instance)
            except ImportError:
                pass  # Notification app may not be ready yet


@receiver(post_save, sender=Membership)
def on_membership_approved(sender, instance, created, update_fields, **kwargs):
    """Notify member when their membership is approved."""
    if not created and instance.status == Membership.Status.ACTIVE:
        try:
            from apps.notifications.services import notify_membership_approved
            notify_membership_approved(instance)
        except ImportError:
            pass

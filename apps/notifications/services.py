"""
Notification service.
Used to dispatch in-app, email, and SMS notifications.
"""
from .models import Notification

def send_notification(user, title, message, notification_type=Notification.NotificationType.INFO, context_data=None, channels=[Notification.Channel.IN_APP], tenant=None):
    """
    Core function to dispatch notifications.

    `tenant` should be supplied whenever the notification belongs to a
    specific society — without it the notification is attached to the
    user's first membership, which is wrong for users who belong to more
    than one society.
    """
    # 1. Create In-App Notification (Always created if IN_APP or ALL is selected)
    if Notification.Channel.IN_APP in channels or Notification.Channel.ALL in channels:
        if tenant is None and user.memberships.exists():
            tenant = user.memberships.first().tenant

        Notification.objects.create(
            tenant=tenant,
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


# ─── Loan notifications ─────────────────────────────────────────────────
#
# `context_data["kind"]` tells the frontend which kind of card to render.
# `context_data["application_id"]` lets the client deep-link into the
# application (or the guarantee request) that the notification refers to.


def notify_guarantor_request(application, guarantor):
    """Called when a member is named as a guarantor on a loan application."""
    applicant = application.member_profile.user.full_name

    send_notification(
        user=guarantor.guarantor_member.user,
        title="Guarantee request",
        message=(
            f"{applicant} has asked you to guarantee a "
            f"₦{application.amount_requested} loan application."
        ),
        notification_type=Notification.NotificationType.INFO,
        context_data={
            "kind": "guarantor_request",
            "application_id": str(application.id),
        },
        tenant=application.tenant,
    )


def notify_guarantor_response(application, guarantor):
    """Called when a guarantor confirms or declines a guarantee request."""
    guarantor_name = guarantor.guarantor_member.user.full_name
    confirmed = guarantor.status == "confirmed"

    send_notification(
        user=application.member_profile.user,
        title="Guarantor response received",
        message=(
            f"{guarantor_name} has "
            f"{'confirmed' if confirmed else 'declined'} your loan application."
        ),
        notification_type=(
            Notification.NotificationType.SUCCESS if confirmed
            else Notification.NotificationType.WARNING
        ),
        context_data={
            "kind": "guarantor_response",
            "application_id": str(application.id),
        },
        tenant=application.tenant,
    )


def notify_loan_decision(application, decision, reason=""):
    """Called when an executive approves or rejects a loan application."""
    approved = decision == "approved"

    message = (
        f"Your loan application for ₦{application.amount_requested} was {decision}."
    )
    if not approved and reason:
        message = f"{message} Reason: {reason}"

    send_notification(
        user=application.member_profile.user,
        title=f"Loan application {decision}",
        message=message,
        notification_type=(
            Notification.NotificationType.SUCCESS if approved
            else Notification.NotificationType.ERROR
        ),
        context_data={
            "kind": "loan_decision",
            "application_id": str(application.id),
        },
        tenant=application.tenant,
    )

"""
Notification service.
Used to dispatch in-app, email, and SMS notifications.
"""
import logging
from functools import partial

from django.db import transaction

from .models import Notification

logger = logging.getLogger(__name__)


def queue_email(recipient, subject, text_content, html_content=""):
    """Queue email after the surrounding database transaction commits."""
    from .tasks import send_email_task

    try:
        transaction.on_commit(partial(
            send_email_task.delay, recipient, subject, text_content, html_content
        ))
    except Exception:
        logger.exception("Could not queue email to %s subject=%r", recipient, subject)


def send_notification(
    user,
    title,
    message,
    notification_type=Notification.NotificationType.INFO,
    context_data=None,
    channels=None,
    tenant=None,
):
    """
    Core function to dispatch notifications.

    `tenant` should be supplied whenever the notification belongs to a
    specific society — without it the notification is attached to the
    user's first membership, which is wrong for users who belong to more
    than one society.
    """
    if channels is None:
        channels = [Notification.Channel.IN_APP, Notification.Channel.EMAIL]

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

    # 2. Send email asynchronously through Brevo (or the configured local backend).
    if Notification.Channel.EMAIL in channels or Notification.Channel.ALL in channels:
        queue_email(user.email, title, message)

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
        notification_type=Notification.NotificationType.INFO,
        tenant=membership.tenant,
    )


def notify_membership_approved(membership):
    """Called when a member is approved."""
    send_notification(
        user=membership.user,
        title="Membership Approved",
        message=f"Welcome! Your membership for {membership.tenant.name} has been approved.",
        notification_type=Notification.NotificationType.SUCCESS,
        channels=[Notification.Channel.IN_APP, Notification.Channel.EMAIL],
        tenant=membership.tenant,
    )


def notify_member_invitation(user, tenant, temporary_password, continuation_url):
    """Email a new account's temporary password and one-time password setup link."""
    from html import escape

    name = escape(user.full_name)
    society = escape(tenant.name)
    safe_password = escape(temporary_password)
    safe_url = escape(continuation_url, quote=True)
    subject = f"Your {tenant.name} cooperative account is ready"
    text = (
        f"Hello {user.full_name},\n\n"
        f"Your account for {tenant.name} has been created. Your temporary password is: "
        f"{temporary_password}\n\n"
        "Continue using this one-time link to choose a permanent password:\n"
        f"{continuation_url}\n\n"
        "The link expires after 24 hours and becomes invalid after it is used."
    )
    html = (
        "<html><body>"
        f"<p>Hello {name},</p><p>Your account for <strong>{society}</strong> is ready.</p>"
        f"<p>Your temporary password: <strong>{safe_password}</strong></p>"
        f'<p><a href="{safe_url}">Continue and choose a permanent password</a></p>'
        "<p>This one-time link expires after 24 hours and becomes invalid after use.</p>"
        "</body></html>"
    )
    queue_email(user.email, subject, text, html)


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

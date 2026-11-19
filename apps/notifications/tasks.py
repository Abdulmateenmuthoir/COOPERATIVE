"""Background email delivery through Brevo's transactional email API."""
import json
import logging
import urllib.error
import urllib.request

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


@shared_task(bind=True, ignore_result=True, max_retries=5)
def send_email_task(self, recipient, subject, text_content, html_content=""):
    """Send one email via Brevo, retrying transient provider/network errors."""
    api_key = getattr(settings, "BREVO_API_KEY", "")
    if not api_key:
        # The local console backend remains useful for development. Production
        # should set BREVO_API_KEY and a verified BREVO_SENDER_EMAIL.
        send_mail(subject, text_content, None, [recipient], fail_silently=False,
                  html_message=html_content or None)
        logger.info("Email sent using Django backend to %s", recipient)
        return

    sender_email = getattr(settings, "BREVO_SENDER_EMAIL", "")
    if not sender_email:
        logger.error("BREVO_SENDER_EMAIL is required when BREVO_API_KEY is set")
        return

    body = {
        "sender": {
            "email": sender_email,
            "name": getattr(settings, "BREVO_SENDER_NAME", "Cooperative Management Platform"),
        },
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text_content,
    }
    if html_content:
        body["htmlContent"] = html_content

    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8") or "{}")
        logger.info("Brevo accepted email to %s message_id=%s", recipient, result.get("messageId"))
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429 or exc.code >= 500:
            raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 1800))
        logger.error("Brevo rejected email to %s (HTTP %s): %s", recipient, exc.code, response_body)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise self.retry(exc=exc, countdown=min(60 * (2 ** self.request.retries), 1800))

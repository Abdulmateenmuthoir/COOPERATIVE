"""
Audit logging service — utility functions and decorator for recording audit entries.
"""
import functools
import logging

from django.forms.models import model_to_dict

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Extract client IP from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def create_audit_log(
    tenant=None,
    actor=None,
    action_code="",
    action_category="update",
    description="",
    entity_type="",
    entity_id="",
    before_state=None,
    after_state=None,
    request=None,
):
    """
    Create an audit log entry.

    This is the primary interface for recording auditable events.
    Can be called directly or via the @audit_action decorator.
    """
    from apps.auditing.models import AuditLog

    ip_address = None
    user_agent = ""

    if request:
        ip_address = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if not actor and hasattr(request, "user") and request.user.is_authenticated:
            actor = request.user
        if not tenant and hasattr(request, "tenant"):
            tenant = request.tenant

    try:
        AuditLog.objects.create(
            tenant=tenant,
            actor_user=actor,
            action_code=action_code,
            action_category=action_category,
            description=description,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else "",
            before_state=before_state,
            after_state=after_state,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as e:
        # Never let audit logging break business logic
        logger.error(f"Failed to create audit log: {e}", exc_info=True)


def model_snapshot(instance, fields=None):
    """
    Take a JSON-serializable snapshot of a model instance.
    Used for before/after state in audit logs.
    """
    if instance is None:
        return None

    try:
        data = model_to_dict(instance, fields=fields)
        # Convert non-serializable types
        for key, value in data.items():
            if hasattr(value, "isoformat"):
                data[key] = value.isoformat()
            elif hasattr(value, "__str__") and not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                data[key] = str(value)
        return data
    except Exception:
        return {"id": str(instance.pk)}


def audit_action(action_code, action_category="update", description=""):
    """
    Decorator for view methods that should be audited.

    Usage:
        @audit_action("loan_approved", "approve", "Loan application approved")
        def approve_loan(self, request, pk=None):
            ...
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, request, *args, **kwargs):
            response = func(self, request, *args, **kwargs)

            # Log the action if the response was successful
            if hasattr(response, "status_code") and response.status_code < 400:
                entity_type = ""
                entity_id = ""

                if hasattr(self, "get_object"):
                    try:
                        obj = self.get_object()
                        entity_type = obj.__class__.__name__
                        entity_id = str(obj.pk)
                    except Exception:
                        pass

                create_audit_log(
                    request=request,
                    action_code=action_code,
                    action_category=action_category,
                    description=description,
                    entity_type=entity_type,
                    entity_id=entity_id,
                )

            return response

        return wrapper

    return decorator

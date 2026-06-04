"""
Custom exception handling for the Cooperative Management SaaS Platform.

Provides consistent error response format across all API endpoints.
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError as DRFValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that provides a consistent error response format:

    {
        "error": "Error Type",
        "detail": "Human-readable description",
        "errors": {...}  // Optional: field-level validation errors
    }
    """
    # Convert Django ValidationError to DRF ValidationError
    if isinstance(exc, DjangoValidationError):
        if hasattr(exc, "message_dict"):
            exc = DRFValidationError(detail=exc.message_dict)
        else:
            exc = DRFValidationError(detail=exc.messages)

    # Get the default response
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception
        logger.exception(f"Unhandled exception: {exc}", exc_info=exc)
        return Response(
            {
                "error": "Internal Server Error",
                "detail": "An unexpected error occurred. Please try again later.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Normalize the response format
    error_data = {
        "error": _get_error_type(exc),
    }

    if isinstance(response.data, dict):
        # Field-level validation errors
        if "detail" in response.data:
            error_data["detail"] = str(response.data["detail"])
        else:
            error_data["detail"] = "Validation failed"
            error_data["errors"] = response.data
    elif isinstance(response.data, list):
        error_data["detail"] = "; ".join(str(item) for item in response.data)
    else:
        error_data["detail"] = str(response.data)

    response.data = error_data
    return response


def _get_error_type(exc):
    """Map exception class to human-readable error type."""
    error_map = {
        DRFValidationError: "Validation Error",
        Http404: "Not Found",
    }

    for exc_class, error_type in error_map.items():
        if isinstance(exc, exc_class):
            return error_type

    if isinstance(exc, APIException):
        return exc.default_detail if hasattr(exc, "default_detail") else "API Error"

    return "Error"


class TenantRequired(APIException):
    """Raised when an operation requires tenant context but none is available."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This operation requires a tenant context."
    default_code = "tenant_required"


class InsufficientPermission(APIException):
    """Raised when a user lacks specific permissions for an operation."""

    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "You do not have the required permissions for this operation."
    default_code = "insufficient_permission"


class BusinessRuleViolation(APIException):
    """Raised when a business rule is violated (e.g., loan eligibility fails)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "This operation violates a business rule."
    default_code = "business_rule_violation"


class ConflictError(APIException):
    """Raised when an operation conflicts with the current state."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "This operation conflicts with the current state."
    default_code = "conflict"

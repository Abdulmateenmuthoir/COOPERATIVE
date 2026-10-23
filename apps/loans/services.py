"""
Loans app services — the society's loan policy.

A cooperative configures loans in two layers:

1. **The rule set** (``TenantRuleSet.rules["loan"]``) — society-wide policy,
   versioned by the platform console and editable by the society admin for
   their own society. It is the outer layer: where it speaks, it wins.
2. **The loan product** (``LoanProduct``) — the per-product rule package
   (rate, term, guarantors, ceiling).

The rule set's ``loan`` section understands these keys:

``escalation_threshold``
    Overrides the product's ``auto_approval_threshold``. Loans above this
    amount are always escalated to the executives for manual approval,
    however generous the product is.

``default_interest_rate``
    Pre-fills the interest rate when a new loan product is created, so a
    society can set its house rate once.

``default_interest_method``
    Pre-fills the interest basis (``flat`` or ``reducing``) for new products.

``max_term_months``
    A society-wide ceiling on the repayment term. A product may offer less
    than this, never more.

Every key is optional and every value is validated before use — a typo in
the JSON falls back to the product's own setting rather than breaking a
loan application.
"""
from decimal import Decimal, InvalidOperation

from .interest import FLAT, INTEREST_METHODS, REDUCING


def get_active_rule_set(tenant):
    """The tenant's currently active rule set, if it has one."""
    from apps.core.models import TenantRuleSet

    return (
        TenantRuleSet.objects.filter(tenant=tenant, active_to__isnull=True)
        .order_by("-version")
        .first()
    )


def get_loan_policy(tenant) -> dict:
    """The ``loan`` section of the active rule set, as a plain dict."""
    rule_set = get_active_rule_set(tenant)
    if not rule_set:
        return {}

    rules = rule_set.rules or {}
    policy = rules.get("loan") or {}

    return policy if isinstance(policy, dict) else {}


def _as_decimal(value):
    """Parse a rule-set value as a Decimal, or return None if it is not one."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def effective_auto_approval_threshold(tenant, product) -> Decimal:
    """
    The amount above which a loan must be escalated to the executives.

    The society's rule set overrides the product's own threshold.
    """
    policy = get_loan_policy(tenant)
    threshold = _as_decimal(policy.get("escalation_threshold"))
    if threshold is not None and threshold >= 0:
        return threshold
    return product.auto_approval_threshold


def society_max_term_months(tenant):
    """The society-wide ceiling on the repayment term, or None."""
    policy = get_loan_policy(tenant)
    value = policy.get("max_term_months")
    if value in (None, ""):
        return None
    try:
        term = int(value)
    except (TypeError, ValueError):
        return None
    return term if term > 0 else None


def default_interest_rate(tenant):
    """The society's house interest rate, or None."""
    policy = get_loan_policy(tenant)
    return _as_decimal(policy.get("default_interest_rate"))


def default_interest_method(tenant):
    """The society's default interest basis, or None."""
    policy = get_loan_policy(tenant)
    method = policy.get("default_interest_method")
    if method in INTEREST_METHODS:
        return method
    return None


def effective_max_term_months(tenant, product) -> int:
    """The term ceiling that actually applies to a product."""
    ceiling = society_max_term_months(tenant)
    if ceiling is None:
        return product.max_term_months
    return min(ceiling, product.max_term_months)


__all__ = [
    "FLAT",
    "REDUCING",
    "default_interest_method",
    "default_interest_rate",
    "effective_auto_approval_threshold",
    "effective_max_term_months",
    "get_active_rule_set",
    "get_loan_policy",
    "society_max_term_months",
]

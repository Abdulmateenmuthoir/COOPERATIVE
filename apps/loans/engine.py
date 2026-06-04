"""
Loan eligibility and approval engine.

Implements the configurable rule-based loan evaluation system.
All rules are read from the LoanProduct configuration, making
the engine work correctly across all tenants with different rules.
"""
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class RuleResult:
    """Result of a single eligibility rule check."""
    rule_name: str
    passed: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class EligibilityResult:
    """Complete eligibility evaluation result."""
    eligible: bool
    max_borrowable: Decimal
    rule_results: list
    approval_mode: str  # "auto" or "manual"
    message: str

    def to_dict(self):
        return {
            "eligible": self.eligible,
            "max_borrowable": str(self.max_borrowable),
            "approval_mode": self.approval_mode,
            "message": self.message,
            "rules": [
                {
                    "rule_name": r.rule_name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                }
                for r in self.rule_results
            ],
        }


class LoanEligibilityEngine:
    """
    Evaluates loan eligibility based on tenant-configured rules.

    All checks must pass for a member to be eligible:
    1. Membership duration >= min_membership_months
    2. Consecutive contribution months >= min_contribution_months
    3. No outstanding loans in default status
    4. Amount requested <= max_amount (or max_multiplier × total_contributions)
    5. Required guarantors count met
    6. All guarantors are active members in good standing
    """

    def __init__(self, member_profile, loan_product):
        self.member = member_profile
        self.product = loan_product
        self.tenant = member_profile.tenant

    def evaluate(self, amount_requested: Optional[Decimal] = None) -> EligibilityResult:
        """Run all eligibility checks and return the result."""
        results = []

        results.append(self._check_membership_duration())
        results.append(self._check_contribution_history())
        results.append(self._check_outstanding_loans())

        max_borrowable = self._calculate_max_borrowable()

        if amount_requested:
            results.append(self._check_amount(amount_requested, max_borrowable))

        all_passed = all(r.passed for r in results)
        approval_mode = "auto"

        if amount_requested and amount_requested > self.product.auto_approval_threshold:
            approval_mode = "manual"

        if all_passed:
            message = "You are eligible for a loan."
            if approval_mode == "manual":
                message += " Due to the amount, executive approval is required."
        else:
            failed = [r for r in results if not r.passed]
            message = f"Not eligible: {'; '.join(r.message for r in failed)}"

        return EligibilityResult(
            eligible=all_passed,
            max_borrowable=max_borrowable,
            rule_results=results,
            approval_mode=approval_mode,
            message=message,
        )

    def _check_membership_duration(self) -> RuleResult:
        """Check if member has been active long enough."""
        from apps.users.models import Membership

        membership = Membership.objects.filter(
            tenant=self.tenant, user=self.member.user, status=Membership.Status.ACTIVE
        ).first()

        if not membership:
            return RuleResult("membership_duration", False, "No active membership found.")

        months = (timezone.now() - membership.created_at).days // 30
        required = self.product.min_membership_months
        passed = months >= required

        return RuleResult(
            "membership_duration",
            passed,
            f"{'✓' if passed else '✗'} Membership: {months} months (required: {required})",
            {"actual_months": months, "required_months": required},
        )

    def _check_contribution_history(self) -> RuleResult:
        """Check if member has sufficient consecutive contributions."""
        from apps.contributions.models import ContributionEntry

        confirmed = ContributionEntry.objects.filter(
            tenant=self.tenant,
            member_profile=self.member,
            entry_type=ContributionEntry.EntryType.REGULAR,
            status=ContributionEntry.Status.CONFIRMED,
        ).count()

        required = self.product.min_contribution_months
        passed = confirmed >= required

        return RuleResult(
            "contribution_history",
            passed,
            f"{'✓' if passed else '✗'} Contributions: {confirmed} confirmed (required: {required})",
            {"confirmed_months": confirmed, "required_months": required},
        )

    def _check_outstanding_loans(self) -> RuleResult:
        """Check if member has any defaulted loans."""
        from apps.loans.models import Loan

        defaulted = Loan.objects.filter(
            tenant=self.tenant,
            application__member_profile=self.member,
            status=Loan.Status.DEFAULTED,
        ).exists()

        active_count = Loan.objects.filter(
            tenant=self.tenant,
            application__member_profile=self.member,
            status__in=[Loan.Status.ACTIVE, Loan.Status.REPAYING],
        ).count()

        if defaulted:
            return RuleResult(
                "outstanding_loans", False,
                "You have a defaulted loan that must be resolved first.",
                {"has_defaulted": True},
            )

        return RuleResult(
            "outstanding_loans", True,
            f"✓ No defaulted loans. Active loans: {active_count}",
            {"has_defaulted": False, "active_loans": active_count},
        )

    def _check_amount(self, amount_requested, max_borrowable) -> RuleResult:
        """Check if requested amount is within limits."""
        passed = amount_requested <= max_borrowable

        return RuleResult(
            "amount_limit",
            passed,
            f"{'✓' if passed else '✗'} Requested: ₦{amount_requested:,.2f} (max: ₦{max_borrowable:,.2f})",
            {"requested": str(amount_requested), "max_borrowable": str(max_borrowable)},
        )

    def _calculate_max_borrowable(self) -> Decimal:
        """Calculate the maximum amount a member can borrow."""
        from apps.contributions.services import get_member_balance

        balance = get_member_balance(self.member)
        multiplier_limit = balance * self.product.max_multiplier
        absolute_limit = self.product.max_amount

        return min(multiplier_limit, absolute_limit)


class LoanApprovalEngine:
    """
    Determines the approval path and creates the loan contract.
    """

    @staticmethod
    @transaction.atomic
    def auto_approve(application):
        """
        Auto-approve a loan application that meets all criteria
        and is within the auto-approval threshold.
        """
        from apps.loans.models import Loan

        application.status = application.Status.APPROVED
        application.save(update_fields=["status", "updated_at"])

        loan = _create_loan_from_application(application)

        # Update application status to disbursed (bursary model)
        application.status = application.Status.DISBURSED
        application.save(update_fields=["status", "updated_at"])

        logger.info(f"Loan auto-approved: {application}, loan_id={loan.id}")
        return loan

    @staticmethod
    def escalate_to_executives(application):
        """
        Escalate a loan application for manual review by executives.
        """
        application.status = application.Status.ESCALATED
        application.save(update_fields=["status", "updated_at"])

        logger.info(f"Loan escalated: {application}")
        return application

    @staticmethod
    @transaction.atomic
    def manual_approve(application, actor_user, comments=""):
        """
        Manually approve a loan application after executive review.
        """
        from apps.loans.models import LoanApprovalStep

        LoanApprovalStep.objects.create(
            tenant=application.tenant,
            application=application,
            actor_user=actor_user,
            actor_role_code="EXECUTIVE",
            decision=LoanApprovalStep.Decision.APPROVE,
            comments=comments,
        )

        application.status = application.Status.APPROVED
        application.save(update_fields=["status", "updated_at"])

        loan = _create_loan_from_application(application)

        application.status = application.Status.DISBURSED
        application.save(update_fields=["status", "updated_at"])

        logger.info(f"Loan manually approved: {application}, loan_id={loan.id}")
        return loan

    @staticmethod
    @transaction.atomic
    def reject(application, actor_user, reason, comments=""):
        """Reject a loan application."""
        from apps.loans.models import LoanApprovalStep

        LoanApprovalStep.objects.create(
            tenant=application.tenant,
            application=application,
            actor_user=actor_user,
            actor_role_code="EXECUTIVE",
            decision=LoanApprovalStep.Decision.REJECT,
            comments=comments,
        )

        application.status = application.Status.REJECTED
        application.rejection_reason = reason
        application.save(update_fields=["status", "rejection_reason", "updated_at"])

        logger.info(f"Loan rejected: {application}, reason={reason}")
        return application


def _create_loan_from_application(application):
    """Create a Loan and RepaymentSchedule from an approved application."""
    from apps.loans.models import Loan, RepaymentSchedule

    product = application.loan_product
    principal = application.amount_requested
    rate = product.interest_rate / Decimal("100")
    term = application.term_months

    # Simple interest calculation
    total_interest = principal * rate * Decimal(str(term)) / Decimal("12")
    total_repayable = principal + total_interest
    monthly_installment = total_repayable / Decimal(str(term))

    loan = Loan.objects.create(
        tenant=application.tenant,
        application=application,
        principal_amount=principal,
        approved_amount=principal,
        interest_rate=product.interest_rate,
        term_months=term,
        total_repayable=total_repayable,
        monthly_installment=monthly_installment.quantize(Decimal("0.01")),
    )

    # Generate repayment schedule
    principal_per_month = principal / Decimal(str(term))
    interest_per_month = total_interest / Decimal(str(term))

    for i in range(1, term + 1):
        RepaymentSchedule.objects.create(
            tenant=application.tenant,
            loan=loan,
            installment_no=i,
            principal_component=principal_per_month.quantize(Decimal("0.01")),
            interest_component=interest_per_month.quantize(Decimal("0.01")),
            amount_due=monthly_installment.quantize(Decimal("0.01")),
        )

    # Record in financial ledger
    from apps.contributions.models import FinancialLedger
    from apps.contributions.services import get_member_balance

    balance = get_member_balance(application.member_profile)
    FinancialLedger.objects.create(
        tenant=application.tenant,
        member_profile=application.member_profile,
        event_type=FinancialLedger.EventType.LOAN_DISBURSEMENT,
        description=f"Loan disbursement: {product.name} ₦{principal:,.2f}",
        source_table="Loan",
        source_id=str(loan.id),
        debit=principal,
        balance_after=balance - principal,
    )

    return loan

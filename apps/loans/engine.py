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

from .interest import calculate_repayment
from .services import effective_auto_approval_threshold

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
    # True when the guarantor rule is the *only* failing rule. The application is
    # not rejected in that case — it waits for guarantors to confirm.
    blocked_on_guarantors: bool = False
    # The amount above which executive approval is required. This is the
    # society's effective threshold, which the rule set may override.
    approval_threshold: Optional[Decimal] = None

    def to_dict(self):
        return {
            "eligible": self.eligible,
            "max_borrowable": str(self.max_borrowable),
            "approval_mode": self.approval_mode,
            "approval_threshold": (
                str(self.approval_threshold) if self.approval_threshold is not None else None
            ),
            "message": self.message,
            "blocked_on_guarantors": self.blocked_on_guarantors,
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

    Rules 5 and 6 need an application to evaluate against. Pass one via
    `application` to enforce them; without it they are reported for information
    only (a member checking eligibility has not named guarantors yet).
    """

    def __init__(self, member_profile, loan_product, application=None):
        self.member = member_profile
        self.product = loan_product
        self.tenant = member_profile.tenant
        self.application = application

    def evaluate(self, amount_requested: Optional[Decimal] = None) -> EligibilityResult:
        """Run all eligibility checks and return the result."""
        results = []

        results.append(self._check_membership_duration())
        results.append(self._check_contribution_history())
        results.append(self._check_outstanding_loans())

        max_borrowable = self._calculate_max_borrowable()

        if amount_requested is not None:
            results.append(self._check_amount(amount_requested, max_borrowable))

        guarantor_result = self._check_guarantors()
        results.append(guarantor_result)

        all_passed = all(r.passed for r in results)
        approval_mode = "auto"

        # The society's rule set may override the product's own threshold, so
        # the escalation point is not read straight off the product.
        threshold = effective_auto_approval_threshold(self.tenant, self.product)

        if amount_requested is not None and amount_requested > threshold:
            approval_mode = "manual"

        # Missing guarantors are a "come back when they confirm", not a rejection.
        blocked_on_guarantors = not guarantor_result.passed and all(
            r.passed for r in results if r is not guarantor_result
        )

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
            blocked_on_guarantors=blocked_on_guarantors,
            approval_threshold=threshold,
        )

    def _check_membership_duration(self) -> RuleResult:
        """Check if member has been active long enough."""
        from apps.users.models import Membership

        membership = Membership.objects.filter(
            tenant=self.tenant, user=self.member.user, status=Membership.Status.ACTIVE
        ).first()

        if not membership:
            return RuleResult("membership_duration", False, "No active membership found.")

        # joined_at is when the member actually joined the cooperative. Falling back
        # to the row's created_at would reset every member's tenure to zero on a bulk
        # import, locking imported members out of loans for months.
        joined_on = self.member.joined_at or timezone.localdate(membership.created_at)
        source = "joined_at" if self.member.joined_at else "membership_record"

        months = self._months_between(joined_on, timezone.localdate())
        required = self.product.min_membership_months
        passed = months >= required

        return RuleResult(
            "membership_duration",
            passed,
            f"{'✓' if passed else '✗'} Membership: {months} months (required: {required})",
            {
                "actual_months": months,
                "required_months": required,
                "joined_on": joined_on.isoformat(),
                "source": source,
            },
        )

    @staticmethod
    def _months_between(start, end) -> int:
        """Whole calendar months elapsed between two dates."""
        if end < start:
            return 0
        months = (end.year - start.year) * 12 + (end.month - start.month)
        if end.day < start.day:
            months -= 1
        return max(months, 0)

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

    def _check_guarantors(self) -> RuleResult:
        """
        Check that enough guarantors have *actively* confirmed.

        Passive or assumed consent is never accepted, and a guarantor only counts
        if they are an active member in good standing and are not the applicant.
        """
        from apps.loans.models import LoanGuarantor

        required = self.product.guarantor_required_count

        if required == 0:
            return RuleResult(
                "guarantors", True, "✓ No guarantors required for this product.",
                {"required_count": 0, "confirmed_count": 0},
            )

        if self.application is None:
            # Pre-application check — the member has not named anyone yet, so this
            # is informational rather than a failure.
            return RuleResult(
                "guarantors", True,
                f"This product requires {required} guarantor(s) who must confirm in the app.",
                {"required_count": required, "confirmed_count": 0, "informational": True},
            )

        guarantors = list(
            LoanGuarantor.objects.filter(application=self.application)
            .select_related("guarantor_member__user")
        )

        confirmed = [g for g in guarantors if g.status == LoanGuarantor.Status.CONFIRMED]
        declined = [g for g in guarantors if g.status == LoanGuarantor.Status.DECLINED]
        valid = [g for g in confirmed if self._guarantor_in_good_standing(g.guarantor_member)]

        valid_count = len(valid)
        passed = valid_count >= required

        if passed:
            message = f"✓ Guarantors: {valid_count} confirmed (required: {required})"
        elif declined and len(guarantors) - len(declined) < required:
            message = (
                f"✗ Guarantors: {len(declined)} declined — "
                f"{valid_count} of {required} confirmed. Name a replacement guarantor."
            )
        else:
            message = f"✗ Guarantors: {valid_count} of {required} confirmed."

        return RuleResult(
            "guarantors",
            passed,
            message,
            {
                "required_count": required,
                "named_count": len(guarantors),
                "confirmed_count": len(confirmed),
                "valid_count": valid_count,
                "declined_count": len(declined),
                "rejected_as_ineligible": len(confirmed) - valid_count,
            },
        )

    def _guarantor_in_good_standing(self, guarantor_profile) -> bool:
        """A guarantor must be an active member, not the applicant, and not in default."""
        from apps.loans.models import Loan
        from apps.users.models import Membership

        if guarantor_profile.id == self.member.id:
            return False

        is_active_member = Membership.objects.filter(
            tenant=self.tenant,
            user=guarantor_profile.user,
            status=Membership.Status.ACTIVE,
        ).exists()

        if not is_active_member:
            return False

        return not Loan.objects.filter(
            tenant=self.tenant,
            application__member_profile=guarantor_profile,
            status=Loan.Status.DEFAULTED,
        ).exists()

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
        from apps.notifications.services import notify_loan_decision

        application.status = application.Status.APPROVED
        application.save(update_fields=["status", "updated_at"])

        loan = _create_loan_from_application(application)

        # Update application status to disbursed (bursary model)
        application.status = application.Status.DISBURSED
        application.save(update_fields=["status", "updated_at"])

        notify_loan_decision(application, "approved")

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
        from apps.notifications.services import notify_loan_decision

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

        notify_loan_decision(application, "approved")

        logger.info(f"Loan manually approved: {application}, loan_id={loan.id}")
        return loan

    @staticmethod
    @transaction.atomic
    def reject(application, actor_user, reason, comments=""):
        """Reject a loan application."""
        from apps.loans.models import LoanApprovalStep
        from apps.notifications.services import notify_loan_decision

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

        notify_loan_decision(application, "rejected", reason)

        logger.info(f"Loan rejected: {application}, reason={reason}")
        return application


def _create_loan_from_application(application):
    """Create a Loan and RepaymentSchedule from an approved application."""
    from apps.loans.models import Loan, RepaymentSchedule

    product = application.loan_product
    principal = application.amount_requested
    term = application.term_months

    # The same calculator that quotes the member a price before they apply
    # writes the contract, so the two can never disagree.
    quote = calculate_repayment(
        principal,
        product.interest_rate,
        term,
        method=product.interest_method,
    )

    loan = Loan.objects.create(
        tenant=application.tenant,
        application=application,
        principal_amount=principal,
        approved_amount=principal,
        interest_rate=product.interest_rate,
        interest_method=product.interest_method,
        term_months=term,
        total_repayable=quote.total_repayable,
        monthly_installment=quote.monthly_installment,
    )

    # Generate repayment schedule
    for installment in quote.installments:
        RepaymentSchedule.objects.create(
            tenant=application.tenant,
            loan=loan,
            installment_no=installment.installment_no,
            principal_component=installment.principal_component,
            interest_component=installment.interest_component,
            amount_due=installment.amount_due,
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

"""
Loans app — Models for the full loan lifecycle.

Covers loan products (configurable rule packages), applications,
guarantor workflow, approval steps, approved loan contracts,
and repayment schedule tracking.
"""
from decimal import Decimal

from django.db import models

from common.models import TenantScopedModel


class LoanProduct(TenantScopedModel):
    """
    Configurable loan rule package.
    Each tenant can define multiple loan products with different rules.
    """

    name = models.CharField(max_length=100, help_text="Loan product name (e.g., 'Standard Loan', 'Emergency Loan')")
    description = models.TextField(blank=True, default="")

    # Eligibility rules
    min_membership_months = models.PositiveIntegerField(
        default=6, help_text="Minimum months of active membership required."
    )
    min_contribution_months = models.PositiveIntegerField(
        default=6, help_text="Minimum consecutive months of confirmed contributions."
    )
    guarantor_required_count = models.PositiveSmallIntegerField(
        default=2, help_text="Number of guarantors required."
    )

    # Amount rules
    max_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("500000.00"),
        help_text="Absolute maximum loan amount.",
    )
    max_multiplier = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("2.00"),
        help_text="Maximum loan as a multiplier of total contributions (e.g., 2x savings).",
    )

    # Interest and terms
    interest_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00"),
        help_text="Annual interest rate as a percentage.",
    )
    max_term_months = models.PositiveIntegerField(
        default=24, help_text="Maximum repayment period in months."
    )
    min_term_months = models.PositiveIntegerField(
        default=1, help_text="Minimum repayment period in months."
    )

    # Approval rules
    auto_approval_threshold = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("100000.00"),
        help_text="Loans at or below this amount can be auto-approved if all rules pass.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.tenant.code}: {self.name}"


class LoanApplication(TenantScopedModel):
    """
    Loan request submitted by a member.
    Goes through eligibility evaluation, guarantor confirmation,
    and approval (automatic or manual).
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        GUARANTOR_PENDING = "guarantor_pending", "Awaiting Guarantors"
        EVALUATING = "evaluating", "Under Evaluation"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        ESCALATED = "escalated", "Escalated to Executives"
        CANCELLED = "cancelled", "Cancelled"
        DISBURSED = "disbursed", "Disbursed"

    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="loan_applications",
    )
    loan_product = models.ForeignKey(
        LoanProduct, on_delete=models.PROTECT, related_name="applications"
    )
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField(help_text="Reason for the loan.")
    term_months = models.PositiveIntegerField(help_text="Requested repayment period in months.")
    status = models.CharField(
        max_length=30, choices=Status.choices, default=Status.DRAFT, db_index=True
    )

    # Evaluation result
    rule_evaluation = models.JSONField(
        null=True, blank=True,
        help_text="JSON record of the eligibility evaluation results.",
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)

    # Rejection/cancellation reason
    rejection_reason = models.TextField(blank=True, default="")

    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Loan App: {self.member_profile.user.email} ₦{self.amount_requested} ({self.status})"


class LoanGuarantor(TenantScopedModel):
    """
    Guarantor for a loan application.
    Guarantors must be active members in good standing.
    They must actively confirm their agreement within the app.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Confirmation"
        CONFIRMED = "confirmed", "Confirmed"
        DECLINED = "declined", "Declined"

    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="guarantors"
    )
    guarantor_member = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="guarantor_commitments",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    decline_reason = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("application", "guarantor_member")]

    def __str__(self):
        return f"Guarantor: {self.guarantor_member.user.email} for {self.application}"


class LoanApprovalStep(TenantScopedModel):
    """
    Manual approval/rejection step by an executive.
    Used when loans are escalated beyond the auto-approval threshold.
    """

    class Decision(models.TextChoices):
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        ABSTAIN = "abstain", "Abstain"

    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="approval_steps"
    )
    actor_user = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.CASCADE,
        related_name="loan_approval_decisions",
    )
    actor_role_code = models.CharField(max_length=50)
    decision = models.CharField(max_length=20, choices=Decision.choices)
    comments = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-decided_at"]

    def __str__(self):
        return f"{self.actor_user.email}: {self.decision} on {self.application}"


class Loan(TenantScopedModel):
    """
    Approved loan contract.
    Created when a LoanApplication is approved.
    Tracks the principal, approved amount, and lifecycle status.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        REPAYING = "repaying", "Repaying"
        CLOSED = "closed", "Fully Repaid"
        DEFAULTED = "defaulted", "Defaulted"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="loan"
    )
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_amount = models.DecimalField(max_digits=12, decimal_places=2)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2)
    term_months = models.PositiveIntegerField()
    total_repayable = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Total amount to be repaid (principal + interest).",
    )
    monthly_installment = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Monthly repayment installment.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    disbursement_mode = models.CharField(
        max_length=50, default="bursary",
        help_text="How the loan was/will be disbursed.",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-opened_at"]

    def __str__(self):
        return f"Loan: {self.application.member_profile.user.email} ₦{self.approved_amount} ({self.status})"

    @property
    def total_paid(self):
        return self.repayment_schedule.filter(
            status=RepaymentSchedule.Status.PAID
        ).aggregate(total=models.Sum("amount_received"))["total"] or Decimal("0.00")

    @property
    def outstanding_balance(self):
        return self.total_repayable - self.total_paid


class RepaymentSchedule(TenantScopedModel):
    """
    Individual repayment installment for a loan.
    Each installment maps to a contribution cycle for bursary integration.
    """

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PAID = "paid", "Paid"
        PARTIAL = "partial", "Partially Paid"
        OVERDUE = "overdue", "Overdue"
        WAIVED = "waived", "Waived"

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="repayment_schedule")
    installment_no = models.PositiveIntegerField()
    due_cycle = models.ForeignKey(
        "contributions.ContributionCycle",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="loan_repayments",
        help_text="The contribution cycle this installment is attached to.",
    )
    principal_component = models.DecimalField(max_digits=12, decimal_places=2)
    interest_component = models.DecimalField(max_digits=12, decimal_places=2)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["installment_no"]
        unique_together = [("loan", "installment_no")]

    def __str__(self):
        return f"Installment {self.installment_no}/{self.loan.term_months}: ₦{self.amount_due}"

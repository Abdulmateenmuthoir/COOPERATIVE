"""
Contributions app — Models for the source-deduction contribution engine.

This is the most critical module in the platform. It handles:
- Contribution plans (fixed + extra)
- Monthly contribution cycles
- Per-member contribution entries
- Penalty tracking for missed contributions
- Financial ledger (immutable member-visible history)
- Financial adjustments (controlled corrections)
"""
from decimal import Decimal

from django.db import models

from common.models import TenantScopedModel


class ContributionPlan(TenantScopedModel):
    """
    Defines the recurring contribution configuration for a society.
    A tenant can have multiple plans (e.g., different tiers), but typically
    has one active default plan.
    """

    plan_name = models.CharField(max_length=100, help_text="Name of the contribution plan (e.g., 'Standard Monthly')")
    amount_fixed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Fixed monthly contribution amount deducted from salary.",
    )
    allows_extra = models.BooleanField(
        default=True,
        help_text="Whether members can make voluntary extra contributions on top of the fixed amount.",
    )
    is_default = models.BooleanField(
        default=False, help_text="Whether this is the default plan for new members."
    )
    effective_from = models.DateField(help_text="Date from which this plan is effective.")
    effective_to = models.DateField(
        null=True, blank=True, help_text="Date until which this plan is effective. Null = currently active."
    )
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"{self.tenant.code}: {self.plan_name} (₦{self.amount_fixed})"

    @property
    def is_active(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.effective_to:
            return self.effective_from <= today <= self.effective_to
        return self.effective_from <= today


class ContributionCycle(TenantScopedModel):
    """
    Represents a monthly contribution processing period.
    Each cycle corresponds to one month's deductions.

    Lifecycle: open → processing → closed
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PROCESSING = "processing", "Processing"
        CLOSED = "closed", "Closed"

    cycle_month = models.PositiveSmallIntegerField(help_text="Month number (1-12)")
    cycle_year = models.PositiveIntegerField(help_text="Year (e.g., 2026)")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    generated_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_cycles",
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        unique_together = [("tenant", "cycle_month", "cycle_year")]
        ordering = ["-cycle_year", "-cycle_month"]

    def __str__(self):
        return f"{self.tenant.code}: {self.cycle_year}-{self.cycle_month:02d} ({self.status})"

    @property
    def period_display(self):
        import calendar
        month_name = calendar.month_name[self.cycle_month]
        return f"{month_name} {self.cycle_year}"


class ContributionEntry(TenantScopedModel):
    """
    Per-member contribution record for a specific cycle.
    Tracks what was due, what was received, and the current status.
    """

    class EntryType(models.TextChoices):
        REGULAR = "regular", "Regular Contribution"
        EXTRA = "extra", "Extra/Voluntary Contribution"
        ADJUSTMENT = "adjustment", "Manual Adjustment"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        MISSED = "missed", "Missed"
        PARTIAL = "partial", "Partially Received"

    cycle = models.ForeignKey(ContributionCycle, on_delete=models.CASCADE, related_name="entries")
    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="contribution_entries",
    )
    entry_type = models.CharField(max_length=20, choices=EntryType.choices, default=EntryType.REGULAR)
    amount_due = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Amount expected from the member for this cycle.",
    )
    amount_received = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0.00"),
        help_text="Amount actually received/confirmed from bursary.",
    )
    source_reference = models.CharField(
        max_length=200, blank=True, default="",
        help_text="Bursary reference or deduction schedule ID.",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    confirmed_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_entries",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-cycle__cycle_year", "-cycle__cycle_month"]

    def __str__(self):
        return f"{self.member_profile.user.email}: ₦{self.amount_due} ({self.status})"


class PenaltyEntry(TenantScopedModel):
    """
    Penalty applied for missed or late contributions.
    Penalty amounts are determined by the tenant's rule set.
    """

    class PenaltyType(models.TextChoices):
        LATE_PAYMENT = "late_payment", "Late Payment"
        MISSED_PAYMENT = "missed_payment", "Missed Payment"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPLIED = "applied", "Applied to Ledger"
        WAIVED = "waived", "Waived"

    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="penalty_entries",
    )
    cycle = models.ForeignKey(
        ContributionCycle, on_delete=models.CASCADE, related_name="penalties"
    )
    penalty_type = models.CharField(max_length=30, choices=PenaltyType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(help_text="Explanation of why the penalty was applied.")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    waived_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waived_penalties",
    )
    waived_reason = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Penalty: {self.member_profile.user.email} ₦{self.amount} ({self.penalty_type})"


class FinancialLedger(TenantScopedModel):
    """
    Immutable, member-visible financial history.
    Every contribution, penalty, loan disbursement, and repayment
    creates a ledger entry. This is the single source of truth
    for a member's financial position.

    Ledger entries are APPEND-ONLY. Corrections are made via
    FinancialAdjustment entries that create new ledger records.
    """

    class EventType(models.TextChoices):
        CONTRIBUTION_CREDIT = "contribution_credit", "Contribution Credit"
        EXTRA_CONTRIBUTION = "extra_contribution", "Extra Contribution"
        PENALTY_DEBIT = "penalty_debit", "Penalty Debit"
        LOAN_DISBURSEMENT = "loan_disbursement", "Loan Disbursement"
        LOAN_REPAYMENT = "loan_repayment", "Loan Repayment"
        ADJUSTMENT_CREDIT = "adjustment_credit", "Adjustment Credit"
        ADJUSTMENT_DEBIT = "adjustment_debit", "Adjustment Debit"

    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices, db_index=True)
    description = models.CharField(max_length=500, blank=True, default="")

    # Link to source record
    source_table = models.CharField(max_length=100, help_text="Model name that generated this entry.")
    source_id = models.CharField(max_length=255, help_text="PK of the source record.")

    # Double-entry style
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    balance_after = models.DecimalField(
        max_digits=12, decimal_places=2,
        help_text="Member's total balance after this entry.",
    )
    posted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-posted_at"]
        indexes = [
            models.Index(fields=["tenant", "member_profile", "-posted_at"]),
        ]

    def __str__(self):
        return f"{self.member_profile.user.email}: {self.event_type} ₦{self.credit - self.debit}"

    def save(self, *args, **kwargs):
        # Immutable — prevent updates
        if self.pk and FinancialLedger.objects.filter(pk=self.pk).exists():
            raise ValueError("Ledger entries are immutable. Use FinancialAdjustment for corrections.")
        super().save(*args, **kwargs)


class FinancialAdjustment(TenantScopedModel):
    """
    Controlled corrections to the financial ledger.
    Every adjustment creates a new ledger entry (never modifies existing ones).
    All adjustments require approval and are fully audited.
    """

    class AdjustmentType(models.TextChoices):
        CREDIT = "credit", "Credit (Add)"
        DEBIT = "debit", "Debit (Subtract)"

    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="financial_adjustments",
    )
    adjustment_type = models.CharField(max_length=10, choices=AdjustmentType.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField(help_text="Explanation for the adjustment.")
    approved_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        related_name="approved_adjustments",
    )

    def __str__(self):
        return f"Adjustment: {self.member_profile.user.email} {self.adjustment_type} ₦{self.amount}"

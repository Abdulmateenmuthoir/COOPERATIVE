"""
Schedules app — Deduction schedule generation and export.

Generates monthly schedules that aggregate each member's contribution
amount + loan repayment + penalties into a single formatted document
for the bursary/payroll office.
"""
from decimal import Decimal

from django.db import models

from common.models import TenantScopedModel


class ScheduleBatch(TenantScopedModel):
    """
    A generated deduction schedule batch.
    Contains all line items for a given period, ready for bursary export.
    """

    class BatchType(models.TextChoices):
        DEDUCTION = "deduction", "Deduction Schedule"
        REPAYMENT = "repayment", "Repayment Schedule"
        COMBINED = "combined", "Combined Schedule"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        FINALIZED = "finalized", "Finalized"
        EXPORTED = "exported", "Exported"
        SUBMITTED = "submitted", "Submitted to Bursary"

    cycle = models.ForeignKey(
        "contributions.ContributionCycle",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="schedule_batches",
    )
    batch_type = models.CharField(max_length=20, choices=BatchType.choices, default=BatchType.COMBINED)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    generated_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        related_name="generated_schedules",
    )
    file_url = models.FileField(
        upload_to="schedules/%Y/%m/",
        blank=True,
        help_text="Exported schedule file.",
    )
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    member_count = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Schedule: {self.tenant.code} {self.batch_type} ({self.status})"


class ScheduleLine(TenantScopedModel):
    """
    Per-member line item in a schedule batch.
    Aggregates contributions, repayments, and penalties.
    """

    batch = models.ForeignKey(ScheduleBatch, on_delete=models.CASCADE, related_name="lines")
    member_profile = models.ForeignKey(
        "users.MemberProfile",
        on_delete=models.CASCADE,
        related_name="schedule_lines",
    )
    contribution_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    repayment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    penalty_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["member_profile__user__last_name"]

    def __str__(self):
        return f"{self.member_profile.user.full_name}: ₦{self.total_amount}"

    def save(self, *args, **kwargs):
        self.total_amount = self.contribution_amount + self.repayment_amount + self.penalty_amount
        super().save(*args, **kwargs)

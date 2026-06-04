"""
Schedule generation service.

Generates deduction schedules by aggregating each member's:
- Monthly contribution amount
- Active loan repayment installment
- Outstanding penalties
"""
import io
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@transaction.atomic
def generate_schedule(tenant, cycle, generated_by, batch_type="combined"):
    """
    Generate a deduction schedule for all active members in a cycle.
    Returns a ScheduleBatch with populated ScheduleLines.
    """
    from apps.contributions.models import ContributionEntry, ContributionPlan, PenaltyEntry
    from apps.loans.models import RepaymentSchedule
    from apps.schedules.models import ScheduleBatch, ScheduleLine
    from apps.users.models import MemberProfile, Membership

    batch = ScheduleBatch.objects.create(
        tenant=tenant,
        cycle=cycle,
        batch_type=batch_type,
        generated_by=generated_by,
        status=ScheduleBatch.Status.DRAFT,
    )

    # Get active members
    active_memberships = Membership.objects.filter(
        tenant=tenant, status=Membership.Status.ACTIVE
    ).select_related("user")

    profiles = MemberProfile.objects.filter(
        tenant=tenant,
        user__in=[m.user for m in active_memberships],
        employment_status=MemberProfile.EmploymentStatus.ACTIVE,
    ).select_related("user")

    # Get default plan
    default_plan = ContributionPlan.objects.filter(
        tenant=tenant, is_default=True, effective_to__isnull=True
    ).first()

    total_amount = Decimal("0.00")
    member_count = 0

    for profile in profiles:
        contribution_amount = default_plan.amount_fixed if default_plan else Decimal("0.00")

        # Check for active loan repayments due this cycle
        repayment_amount = Decimal("0.00")
        repayments = RepaymentSchedule.objects.filter(
            tenant=tenant,
            loan__application__member_profile=profile,
            loan__status__in=["active", "repaying"],
            status=RepaymentSchedule.Status.SCHEDULED,
        ).order_by("installment_no")

        if repayments.exists():
            next_repayment = repayments.first()
            repayment_amount = next_repayment.amount_due

        # Check for outstanding penalties
        penalty_amount = PenaltyEntry.objects.filter(
            tenant=tenant,
            member_profile=profile,
            status=PenaltyEntry.Status.APPLIED,
        ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

        # Need import for Sum
        from django.db.models import Sum
        penalty_amount = PenaltyEntry.objects.filter(
            tenant=tenant,
            member_profile=profile,
            status=PenaltyEntry.Status.PENDING,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        line_total = contribution_amount + repayment_amount + penalty_amount

        if line_total > 0:
            ScheduleLine.objects.create(
                tenant=tenant,
                batch=batch,
                member_profile=profile,
                contribution_amount=contribution_amount,
                repayment_amount=repayment_amount,
                penalty_amount=penalty_amount,
            )
            total_amount += line_total
            member_count += 1

    batch.total_amount = total_amount
    batch.member_count = member_count
    batch.save(update_fields=["total_amount", "member_count", "updated_at"])

    logger.info(f"Generated schedule: {batch}, {member_count} members, ₦{total_amount:,.2f}")
    return batch


def export_schedule_csv(batch):
    """Export a schedule batch as CSV content."""
    import csv

    lines = batch.lines.select_related("member_profile__user").all()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "S/N", "Name", "Employee No", "Payroll No", "Department",
        "Contribution (₦)", "Loan Repayment (₦)", "Penalty (₦)", "Total (₦)",
    ])

    for idx, line in enumerate(lines, 1):
        writer.writerow([
            idx,
            line.member_profile.user.full_name,
            line.member_profile.employee_no,
            line.member_profile.payroll_no,
            line.member_profile.department,
            f"{line.contribution_amount:.2f}",
            f"{line.repayment_amount:.2f}",
            f"{line.penalty_amount:.2f}",
            f"{line.total_amount:.2f}",
        ])

    # Summary row
    writer.writerow([])
    writer.writerow(["", "", "", "", "TOTAL", f"{batch.total_amount:.2f}"])
    writer.writerow(["", "", "", "", "Members", batch.member_count])

    return output.getvalue()


def export_schedule_excel(batch):
    """Export a schedule batch as Excel content."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Deduction Schedule"

    # Title
    ws.merge_cells("A1:I1")
    ws["A1"] = f"Deduction Schedule — {batch.tenant.name}"
    ws["A1"].font = Font(bold=True, size=14)

    if batch.cycle:
        ws.merge_cells("A2:I2")
        ws["A2"] = f"Period: {batch.cycle.period_display}"
        ws["A2"].font = Font(size=12)

    # Headers
    headers = [
        "S/N", "Name", "Employee No", "Payroll No", "Department",
        "Contribution (₦)", "Loan Repayment (₦)", "Penalty (₦)", "Total (₦)",
    ]
    header_fill = PatternFill(start_color="1a56db", end_color="1a56db", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Data
    lines = batch.lines.select_related("member_profile__user").all()
    for idx, line in enumerate(lines, 1):
        row = idx + 4
        ws.cell(row=row, column=1, value=idx)
        ws.cell(row=row, column=2, value=line.member_profile.user.full_name)
        ws.cell(row=row, column=3, value=line.member_profile.employee_no)
        ws.cell(row=row, column=4, value=line.member_profile.payroll_no)
        ws.cell(row=row, column=5, value=line.member_profile.department)
        ws.cell(row=row, column=6, value=float(line.contribution_amount))
        ws.cell(row=row, column=7, value=float(line.repayment_amount))
        ws.cell(row=row, column=8, value=float(line.penalty_amount))
        ws.cell(row=row, column=9, value=float(line.total_amount))

    # Column widths
    widths = [5, 30, 15, 15, 20, 18, 18, 15, 15]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()

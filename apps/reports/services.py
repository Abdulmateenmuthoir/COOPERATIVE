"""
Reporting and analytics service.

Aggregates data for executive dashboards and periodic reports.
"""
from decimal import Decimal

from django.db.models import Count, Sum, Q
from django.utils import timezone

from apps.contributions.models import ContributionEntry, FinancialLedger
from apps.loans.models import Loan, LoanApplication
from apps.users.models import Membership


def get_executive_dashboard_summary(tenant):
    """
    Returns high-level summary metrics for the society executive dashboard.
    """
    # 1. Membership Metrics
    active_members = Membership.objects.filter(
        tenant=tenant, status=Membership.Status.ACTIVE
    ).count()
    pending_members = Membership.objects.filter(
        tenant=tenant, status=Membership.Status.PENDING
    ).count()

    # 2. Financial Metrics (Overall Portfolio)
    total_savings = FinancialLedger.objects.filter(
        tenant=tenant,
        event_type__in=[
            FinancialLedger.EventType.CONTRIBUTION_CREDIT,
            FinancialLedger.EventType.EXTRA_CONTRIBUTION
        ]
    ).aggregate(total=Sum("credit"))["total"] or Decimal("0.00")

    # 3. Loan Portfolio
    loans = Loan.objects.filter(tenant=tenant)
    active_loans = loans.filter(status__in=[Loan.Status.ACTIVE, Loan.Status.REPAYING])
    
    total_loans_disbursed = loans.aggregate(total=Sum("approved_amount"))["total"] or Decimal("0.00")
    total_outstanding = active_loans.aggregate(
        total_repayable=Sum("total_repayable")
    )["total_repayable"] or Decimal("0.00")

    # To get exact outstanding, we'd sum the actual outstanding property or compute in DB.
    # For a high-level DB aggregation, we can estimate or compute exact in python if dataset is small,
    # but for scalable analytics, we'd use a dedicated 'outstanding_balance' field updated on repayment.
    
    # 4. Pending Actions
    pending_loans = LoanApplication.objects.filter(
        tenant=tenant, status__in=[
            LoanApplication.Status.SUBMITTED,
            LoanApplication.Status.ESCALATED,
        ]
    ).count()

    return {
        "membership": {
            "active_members": active_members,
            "pending_approvals": pending_members,
        },
        "financials": {
            "total_savings": total_savings,
            "total_loans_disbursed": total_loans_disbursed,
        },
        "loans": {
            "active_loan_count": active_loans.count(),
            "pending_applications": pending_loans,
        }
    }


def get_contribution_performance(tenant, year=None):
    """
    Returns monthly contribution performance for a given year.
    Used for plotting charts on the dashboard.
    """
    if not year:
        year = timezone.now().year

    # Aggregate by cycle_month for the given year
    entries = ContributionEntry.objects.filter(
        tenant=tenant,
        cycle__cycle_year=year
    ).values("cycle__cycle_month").annotate(
        due=Sum("amount_due"),
        received=Sum("amount_received"),
    ).order_by("cycle__cycle_month")

    months_data = []
    for entry in entries:
        months_data.append({
            "month": entry["cycle__cycle_month"],
            "expected": entry["due"] or Decimal("0.00"),
            "actual": entry["received"] or Decimal("0.00"),
            "collection_rate": (
                (entry["received"] / entry["due"] * 100) 
                if entry["due"] and entry["due"] > 0 else 0
            )
        })

    return months_data

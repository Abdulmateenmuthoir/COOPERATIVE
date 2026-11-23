"""
Contributions business logic — cycle generation, confirmation, and penalty calculation.
"""
import logging
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def generate_cycle_entries(cycle):
    """
    Generate ContributionEntry records for all active members in the cycle's tenant.
    Called when a new ContributionCycle is created or manually triggered.

    Each active member gets a PENDING entry with amount_due set from their
    contribution plan (or the tenant's default plan).
    """
    from apps.contributions.models import ContributionEntry, ContributionPlan
    from apps.users.models import MemberProfile, Membership

    tenant = cycle.tenant

    # Get the active default contribution plan
    default_plan = ContributionPlan.objects.filter(
        tenant=tenant, is_default=True, effective_to__isnull=True
    ).first()

    if not default_plan:
        logger.warning(f"No active default contribution plan for tenant {tenant.code}")
        return 0

    # Get all active member profiles
    active_memberships = Membership.objects.filter(
        tenant=tenant, status=Membership.Status.ACTIVE
    ).select_related("user")

    active_member_profiles = MemberProfile.objects.filter(
        tenant=tenant,
        user__in=[m.user for m in active_memberships],
        employment_status=MemberProfile.EmploymentStatus.ACTIVE,
    )

    entries_created = 0
    for profile in active_member_profiles:
        # Check if entry already exists for this member+cycle
        existing = ContributionEntry.objects.filter(
            tenant=tenant, cycle=cycle, member_profile=profile, entry_type=ContributionEntry.EntryType.REGULAR
        ).exists()

        if not existing:
            from apps.contributions.models import MemberContributionAgreement
            from datetime import date
            period_date = date(cycle.cycle_year, cycle.cycle_month, 1)
            agreement = MemberContributionAgreement.objects.filter(
                tenant=tenant, member_profile=profile, plan=default_plan,
                effective_from__lte=period_date,
            ).filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=period_date)).order_by("-effective_from").first()
            ContributionEntry.objects.create(
                tenant=tenant,
                cycle=cycle,
                member_profile=profile,
                entry_type=ContributionEntry.EntryType.REGULAR,
                amount_due=agreement.amount if agreement else default_plan.amount_fixed,
                contribution_agreement=agreement,
                policy_version=agreement.policy_version if agreement else default_plan.policy_version,
                rule_snapshot={
                    "minimum_amount": str(default_plan.minimum_amount) if default_plan.minimum_amount is not None else None,
                    "qualifying_membership_months": default_plan.qualifying_membership_months,
                    "qualifying_periods": default_plan.qualifying_periods,
                    "minimum_paid_periods": default_plan.minimum_paid_periods,
                    "minimum_paid_percentage": str(default_plan.minimum_paid_percentage) if default_plan.minimum_paid_percentage is not None else None,
                    "grace_period_days": default_plan.grace_period_days,
                    "withdrawal_policy": default_plan.withdrawal_policy,
                },
                status=ContributionEntry.Status.PENDING,
            )
            entries_created += 1

    logger.info(f"Generated {entries_created} contribution entries for {tenant.code} {cycle.period_display}")
    return entries_created


@transaction.atomic
def confirm_contribution(entry, amount_received, confirmed_by, source_reference=""):
    """
    Confirm a contribution entry and update the member's financial ledger.

    This is called when the bursary confirms that a deduction was processed.
    """
    from apps.contributions.models import FinancialLedger

    entry.amount_received = amount_received
    entry.source_reference = source_reference
    entry.confirmed_by = confirmed_by
    entry.confirmed_at = timezone.now()

    if amount_received >= entry.amount_due:
        entry.status = entry.Status.CONFIRMED
    elif amount_received > 0:
        entry.status = entry.Status.PARTIAL
    else:
        entry.status = entry.Status.MISSED

    entry.save()

    # Create ledger entry
    if amount_received > 0:
        # Get current balance
        last_ledger = FinancialLedger.objects.filter(
            tenant=entry.tenant, member_profile=entry.member_profile
        ).order_by("-posted_at").first()

        current_balance = last_ledger.balance_after if last_ledger else Decimal("0.00")

        event_type = FinancialLedger.EventType.CONTRIBUTION_CREDIT
        if entry.entry_type == entry.EntryType.EXTRA:
            event_type = FinancialLedger.EventType.EXTRA_CONTRIBUTION

        FinancialLedger.objects.create(
            tenant=entry.tenant,
            member_profile=entry.member_profile,
            event_type=event_type,
            description=f"Contribution for {entry.cycle.period_display}",
            source_table="ContributionEntry",
            source_id=str(entry.id),
            credit=amount_received,
            balance_after=current_balance + amount_received,
        )

    return entry


@transaction.atomic
def bulk_confirm_contributions(cycle, confirmed_by, entries_data=None):
    """
    Bulk confirm all pending contributions in a cycle.

    entries_data: optional list of dicts with member_profile_id and amount_received.
    If not provided, confirms all entries at their amount_due.
    """
    from apps.contributions.models import ContributionEntry

    entries = ContributionEntry.objects.filter(
        tenant=cycle.tenant, cycle=cycle, status=ContributionEntry.Status.PENDING
    )

    confirmed_count = 0
    for entry in entries:
        if entries_data:
            # Find matching data
            data = next(
                (d for d in entries_data if str(d.get("member_profile_id")) == str(entry.member_profile_id)),
                None,
            )
            amount = Decimal(str(data["amount_received"])) if data else entry.amount_due
        else:
            amount = entry.amount_due

        confirm_contribution(entry, amount, confirmed_by)
        confirmed_count += 1

    # Update cycle status
    cycle.status = cycle.Status.CLOSED
    cycle.closed_at = timezone.now()
    cycle.save(update_fields=["status", "closed_at", "updated_at"])

    return confirmed_count


@transaction.atomic
def apply_penalty(member_profile, cycle, penalty_type, amount, reason):
    """
    Apply a penalty to a member and record it in the ledger.
    """
    from apps.contributions.models import FinancialLedger, PenaltyEntry

    penalty = PenaltyEntry.objects.create(
        tenant=member_profile.tenant,
        member_profile=member_profile,
        cycle=cycle,
        penalty_type=penalty_type,
        amount=amount,
        reason=reason,
        status=PenaltyEntry.Status.APPLIED,
    )

    # Update ledger
    last_ledger = FinancialLedger.objects.filter(
        tenant=member_profile.tenant, member_profile=member_profile
    ).order_by("-posted_at").first()

    current_balance = last_ledger.balance_after if last_ledger else Decimal("0.00")

    FinancialLedger.objects.create(
        tenant=member_profile.tenant,
        member_profile=member_profile,
        event_type=FinancialLedger.EventType.PENALTY_DEBIT,
        description=f"Penalty: {reason}",
        source_table="PenaltyEntry",
        source_id=str(penalty.id),
        debit=amount,
        balance_after=current_balance - amount,
    )

    return penalty


def check_and_apply_penalties(cycle):
    """
    After a cycle is closed, check for missed contributions and apply
    penalties according to the tenant's rule set.
    """
    from apps.contributions.models import ContributionEntry, PenaltyEntry
    from apps.core.models import TenantRuleSet

    tenant = cycle.tenant

    # Get active rule set
    rule_set = TenantRuleSet.objects.filter(
        tenant=tenant, active_to__isnull=True
    ).first()

    if not rule_set or not rule_set.rules.get("penalty"):
        return 0

    penalty_config = rule_set.rules["penalty"]
    penalty_rate = Decimal(str(penalty_config.get("missed_payment_rate", "0.00")))
    penalty_flat = Decimal(str(penalty_config.get("missed_payment_flat", "0.00")))

    # Find missed entries
    missed_entries = ContributionEntry.objects.filter(
        tenant=tenant, cycle=cycle, status=ContributionEntry.Status.MISSED
    )

    penalties_applied = 0
    for entry in missed_entries:
        # Check if penalty already applied
        existing = PenaltyEntry.objects.filter(
            tenant=tenant,
            member_profile=entry.member_profile,
            cycle=cycle,
        ).exists()

        if not existing:
            # Calculate penalty amount
            if penalty_rate > 0:
                penalty_amount = entry.amount_due * penalty_rate
            else:
                penalty_amount = penalty_flat

            if penalty_amount > 0:
                apply_penalty(
                    member_profile=entry.member_profile,
                    cycle=cycle,
                    penalty_type=PenaltyEntry.PenaltyType.MISSED_PAYMENT,
                    amount=penalty_amount,
                    reason=f"Missed contribution for {cycle.period_display}",
                )
                penalties_applied += 1

    return penalties_applied


def get_member_balance(member_profile):
    """Get a member's current financial balance from the ledger."""
    from apps.contributions.models import FinancialLedger

    last_entry = FinancialLedger.objects.filter(
        tenant=member_profile.tenant, member_profile=member_profile
    ).order_by("-posted_at").first()

    return last_entry.balance_after if last_entry else Decimal("0.00")


def get_member_contribution_summary(member_profile):
    """Get a summary of a member's contributions across all cycles."""
    from django.db.models import Count, Q, Sum

    from apps.contributions.models import ContributionEntry

    entries = ContributionEntry.objects.filter(
        tenant=member_profile.tenant,
        member_profile=member_profile,
        entry_type=ContributionEntry.EntryType.REGULAR,
    )

    summary = entries.aggregate(
        total_cycles=Count("id"),
        total_due=Sum("amount_due"),
        total_received=Sum("amount_received"),
        confirmed_count=Count("id", filter=Q(status=ContributionEntry.Status.CONFIRMED)),
        missed_count=Count("id", filter=Q(status=ContributionEntry.Status.MISSED)),
    )

    return {
        "total_cycles": summary["total_cycles"] or 0,
        "total_due": summary["total_due"] or Decimal("0.00"),
        "total_received": summary["total_received"] or Decimal("0.00"),
        "confirmed_count": summary["confirmed_count"] or 0,
        "missed_count": summary["missed_count"] or 0,
        "current_balance": get_member_balance(member_profile),
        "compulsory_balance": sum(
            ContributionEntry.objects.filter(
                tenant=member_profile.tenant,
                member_profile=member_profile,
                entry_type=ContributionEntry.EntryType.REGULAR,
                status__in=[ContributionEntry.Status.CONFIRMED, ContributionEntry.Status.PARTIAL],
            ).values_list("amount_received", flat=True),
            Decimal("0.00"),
        ),
    }

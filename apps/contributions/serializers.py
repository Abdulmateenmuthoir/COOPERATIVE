"""
Contributions app serializers.
"""
from rest_framework import serializers

from .models import (
    ContributionCycle,
    ContributionEntry,
    ContributionPlan,
    FinancialAdjustment,
    FinancialLedger,
    PenaltyEntry,
)


class ContributionPlanSerializer(serializers.ModelSerializer):
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = ContributionPlan
        fields = [
            "id", "plan_name", "amount_fixed", "allows_extra", "is_default",
            "effective_from", "effective_to", "description", "is_active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ContributionCycleSerializer(serializers.ModelSerializer):
    period_display = serializers.ReadOnlyField()
    entry_count = serializers.SerializerMethodField()
    confirmed_count = serializers.SerializerMethodField()
    generated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ContributionCycle
        fields = [
            "id", "cycle_month", "cycle_year", "period_display", "status",
            "generated_by", "generated_by_name", "generated_at", "closed_at",
            "notes", "entry_count", "confirmed_count", "created_at",
        ]
        read_only_fields = ["id", "generated_by", "generated_at", "closed_at", "created_at"]

    def get_entry_count(self, obj):
        return obj.entries.count()

    def get_confirmed_count(self, obj):
        return obj.entries.filter(status=ContributionEntry.Status.CONFIRMED).count()

    def get_generated_by_name(self, obj):
        """Display name of the officer who generated the cycle."""
        if not obj.generated_by:
            return None
        return obj.generated_by.full_name


class ContributionEntrySerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    member_email = serializers.SerializerMethodField()
    member_payroll_no = serializers.SerializerMethodField()
    confirmed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ContributionEntry
        fields = [
            "id", "cycle", "member_profile", "member_name", "member_email",
            "member_payroll_no", "entry_type", "amount_due", "amount_received",
            "source_reference", "status", "confirmed_by", "confirmed_by_name",
            "confirmed_at", "created_at",
        ]
        read_only_fields = ["id", "confirmed_by", "confirmed_at", "created_at"]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name

    def get_member_email(self, obj):
        return obj.member_profile.user.email

    def get_member_payroll_no(self, obj):
        return obj.member_profile.payroll_no

    def get_confirmed_by_name(self, obj):
        """Display name of the officer who confirmed the entry."""
        if not obj.confirmed_by:
            return None
        return obj.confirmed_by.full_name


class ContributionConfirmSerializer(serializers.Serializer):
    """Serializer for confirming a single contribution entry."""
    amount_received = serializers.DecimalField(max_digits=12, decimal_places=2)
    source_reference = serializers.CharField(max_length=200, required=False, default="")


class BulkConfirmSerializer(serializers.Serializer):
    """Serializer for bulk confirming contributions in a cycle."""
    entries = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        help_text="Optional list of {member_profile_id, amount_received}. If empty, confirms all at amount_due.",
    )


class PenaltyEntrySerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    waived_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PenaltyEntry
        fields = [
            "id", "member_profile", "member_name", "cycle", "penalty_type",
            "amount", "reason", "status", "waived_by", "waived_by_name",
            "waived_reason", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name

    def get_waived_by_name(self, obj):
        """Display name of the officer who waived the penalty."""
        if not obj.waived_by:
            return None
        return obj.waived_by.full_name


class FinancialLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialLedger
        fields = [
            "id", "member_profile", "event_type", "description",
            "source_table", "source_id", "debit", "credit",
            "balance_after", "posted_at",
        ]
        read_only_fields = fields  # Fully read-only


class FinancialAdjustmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialAdjustment
        fields = [
            "id", "member_profile", "adjustment_type", "amount",
            "reason", "approved_by", "created_at",
        ]
        read_only_fields = ["id", "approved_by", "created_at"]


class MemberBalanceSerializer(serializers.Serializer):
    """Serializer for member balance/summary response."""
    current_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_cycles = serializers.IntegerField()
    total_due = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_received = serializers.DecimalField(max_digits=12, decimal_places=2)
    confirmed_count = serializers.IntegerField()
    missed_count = serializers.IntegerField()

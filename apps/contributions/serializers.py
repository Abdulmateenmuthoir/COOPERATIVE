"""
Contributions app serializers.
"""
from rest_framework import serializers
from decimal import Decimal

from .models import (
    ContributionCycle,
    ContributionEntry,
    ContributionPlan,
    FinancialAdjustment,
    FinancialLedger,
    PenaltyEntry,
    ShareProduct,
    Shareholding,
    ExitRequest,
    MemberContributionAgreement,
    DividendDeclaration,
    DividendEntitlement,
)


class ContributionPlanSerializer(serializers.ModelSerializer):
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = ContributionPlan
        fields = [
            "id", "plan_name", "amount_fixed", "allows_extra", "is_default",
            "effective_from", "effective_to", "description", "is_active",
            "minimum_amount", "qualifying_membership_months", "qualifying_periods",
            "minimum_paid_periods", "minimum_paid_percentage", "grace_period_days",
            "withdrawal_policy", "policy_version",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "policy_version", "created_at", "updated_at"]

    def validate(self, attrs):
        amount = attrs.get("amount_fixed", getattr(self.instance, "amount_fixed", None))
        minimum = attrs.get("minimum_amount", getattr(self.instance, "minimum_amount", None))
        if minimum is not None and amount is not None and minimum > amount:
            raise serializers.ValidationError({"minimum_amount": "Cannot exceed the fixed contribution amount."})
        percentage = attrs.get("minimum_paid_percentage", getattr(self.instance, "minimum_paid_percentage", None))
        if percentage is not None and not (0 <= percentage <= 100):
            raise serializers.ValidationError({"minimum_paid_percentage": "Must be between 0 and 100."})
        return attrs


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
            "contribution_agreement", "policy_version", "rule_snapshot",
            "source_reference", "status", "confirmed_by", "confirmed_by_name",
            "confirmed_at", "created_at",
        ]
        read_only_fields = ["id", "contribution_agreement", "policy_version", "rule_snapshot", "confirmed_by", "confirmed_at", "created_at"]

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
    compulsory_balance = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    total_cycles = serializers.IntegerField()
    total_due = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_received = serializers.DecimalField(max_digits=12, decimal_places=2)
    confirmed_count = serializers.IntegerField()
    missed_count = serializers.IntegerField()


class ShareProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShareProduct
        fields = "__all__"
        read_only_fields = ["id", "tenant", "issued_units", "version", "created_at", "updated_at"]

    def validate(self, attrs):
        price = attrs.get("price_per_unit", getattr(self.instance, "price_per_unit", 0))
        minimum = attrs.get("min_units", getattr(self.instance, "min_units", 1))
        maximum = attrs.get("max_units", getattr(self.instance, "max_units", None))
        if price <= 0:
            raise serializers.ValidationError({"price_per_unit": "Must be greater than zero."})
        if maximum and maximum < minimum:
            raise serializers.ValidationError({"max_units": "Must be greater than or equal to min_units."})
        if attrs.get("ownership_model", getattr(self.instance, "ownership_model", None)) == ShareProduct.OwnershipModel.UNITARY and minimum > 1:
            raise serializers.ValidationError({"min_units": "Unitary ownership permits exactly one unit per member."})
        return attrs


class ShareholdingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shareholding
        fields = ["id", "product", "member_profile", "units", "units_paid", "amount_paid", "unit_price", "status", "certificate_reference", "issued_at", "created_at"]
        read_only_fields = ["id", "units_paid", "amount_paid", "unit_price", "status", "issued_at", "created_at"]


class ExitRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExitRequest
        fields = ["id", "member_profile", "requested_exit_date", "reason", "status", "gross_contribution_balance", "deductions", "proposed_payable", "decision_by", "decision_reason", "decided_at", "policy_version", "payment_reference", "created_at"]
        read_only_fields = ["id", "member_profile", "status", "gross_contribution_balance", "deductions", "proposed_payable", "decision_by", "decision_reason", "decided_at", "policy_version", "payment_reference", "created_at"]


class ExitReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    gross_contribution_balance = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    deductions = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    proposed_payable = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    reason = serializers.CharField()

    def validate(self, attrs):
        if attrs["decision"] == "approve":
            for field in ("gross_contribution_balance", "proposed_payable"):
                if field not in attrs:
                    raise serializers.ValidationError({field: "Required when approving a settlement estimate."})
            deductions_total = sum(
                (serializers.DecimalField(max_digits=12, decimal_places=2).run_validation(item.get("amount", "0")) for item in attrs.get("deductions", [])),
                start=Decimal("0.00"),
            )
            if attrs["gross_contribution_balance"] - deductions_total != attrs["proposed_payable"]:
                raise serializers.ValidationError({"proposed_payable": "Must equal gross contribution balance minus itemized deductions."})
        return attrs


class MemberContributionAgreementSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.CharField(source="approved_by.full_name", read_only=True)

    class Meta:
        model = MemberContributionAgreement
        fields = ["id", "member_profile", "plan", "amount", "effective_from", "effective_to", "reason", "policy_version", "approved_by", "approved_by_name", "created_at"]
        read_only_fields = ["id", "policy_version", "approved_by", "approved_by_name", "created_at"]

    def validate(self, attrs):
        member = attrs.get("member_profile")
        plan = attrs.get("plan")
        request = self.context.get("request")
        if request and (member.tenant_id != request.tenant.id or plan.tenant_id != request.tenant.id):
            raise serializers.ValidationError("Member and plan must belong to this society.")
        if attrs["amount"] <= 0:
            raise serializers.ValidationError({"amount": "Must be greater than zero."})
        if attrs.get("effective_to") and attrs["effective_to"] < attrs["effective_from"]:
            raise serializers.ValidationError({"effective_to": "Must not precede effective_from."})
        if plan.minimum_amount and attrs["amount"] < plan.minimum_amount:
            raise serializers.ValidationError({"amount": "Below the plan minimum."})
        return attrs


class DividendDeclarationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DividendDeclaration
        fields = ["id", "financial_year", "record_date", "per_share_amount", "status", "agm_reference", "proposed_by", "approved_by", "approved_at", "created_at"]
        read_only_fields = fields


class DividendEntitlementSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source="member_profile.user.full_name", read_only=True)

    class Meta:
        model = DividendEntitlement
        fields = ["id", "declaration", "member_profile", "member_name", "eligible_units", "amount", "status", "payment_reference"]
        read_only_fields = fields


class DividendProposalSerializer(serializers.Serializer):
    financial_year = serializers.CharField(max_length=20)
    record_date = serializers.DateField()
    per_share_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class DividendApprovalSerializer(serializers.Serializer):
    agm_reference = serializers.CharField(max_length=120)


class DividendPaymentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["paid", "withheld", "reinvested"])
    payment_reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")

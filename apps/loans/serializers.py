"""Loans app serializers."""
from rest_framework import serializers

from .models import (
    Loan,
    LoanApplication,
    LoanApprovalStep,
    LoanGuarantor,
    LoanProduct,
    RepaymentSchedule,
)


class LoanProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanProduct
        fields = [
            "id", "name", "description", "min_membership_months",
            "min_contribution_months", "guarantor_required_count",
            "max_amount", "max_multiplier", "interest_rate", "interest_method",
            "max_term_months", "min_term_months", "auto_approval_threshold",
            "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class LoanGuarantorSerializer(serializers.ModelSerializer):
    guarantor_name = serializers.SerializerMethodField()
    guarantor_email = serializers.SerializerMethodField()

    class Meta:
        model = LoanGuarantor
        fields = [
            "id", "guarantor_member", "guarantor_name", "guarantor_email",
            "status", "confirmed_at", "decline_reason",
        ]
        read_only_fields = ["id", "status", "confirmed_at"]

    def get_guarantor_name(self, obj):
        return obj.guarantor_member.user.full_name

    def get_guarantor_email(self, obj):
        return obj.guarantor_member.user.email


class LoanApprovalStepSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = LoanApprovalStep
        fields = [
            "id", "actor_user", "actor_name", "actor_role_code",
            "decision", "comments", "decided_at",
        ]

    def get_actor_name(self, obj):
        return obj.actor_user.full_name


class LoanApplicationListSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    product_name = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = [
            "id", "member_profile", "member_name", "loan_product",
            "product_name", "amount_requested", "term_months",
            "status", "submitted_at", "created_at",
        ]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name

    def get_product_name(self, obj):
        return obj.loan_product.name


class LoanApplicationDetailSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    product = LoanProductSerializer(source="loan_product", read_only=True)
    guarantors = LoanGuarantorSerializer(many=True, read_only=True)
    approval_steps = LoanApprovalStepSerializer(many=True, read_only=True)

    class Meta:
        model = LoanApplication
        fields = [
            "id", "member_profile", "member_name", "product",
            "amount_requested", "purpose", "term_months", "status",
            "rule_evaluation", "evaluated_at", "rejection_reason",
            "submitted_at", "guarantors", "approval_steps", "created_at",
        ]
        read_only_fields = [
            "id", "status", "rule_evaluation", "evaluated_at",
            "rejection_reason", "submitted_at", "created_at",
        ]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name


class LoanGuaranteeRequestSerializer(serializers.ModelSerializer):
    """
    Restricted view of a loan application, used when the viewer is only a
    named guarantor.

    A guarantor needs enough detail to decide, but not the applicant's
    contact details, the other guarantors, the internal rule evaluation or
    the approval trail.
    """

    member_name = serializers.SerializerMethodField()
    product = LoanProductSerializer(source="loan_product", read_only=True)
    product_name = serializers.SerializerMethodField()
    guarantor_status = serializers.SerializerMethodField()
    guarantor_id = serializers.SerializerMethodField()

    class Meta:
        model = LoanApplication
        fields = [
            "id", "member_name", "product", "product_name",
            "amount_requested", "purpose", "term_months", "status",
            "submitted_at", "guarantor_status", "guarantor_id", "created_at",
        ]
        # Only model fields may be listed here — the derived fields above are
        # declared on the serializer, and DRF rejects the two overlapping.
        read_only_fields = [
            "id", "amount_requested", "purpose", "term_months",
            "status", "submitted_at", "created_at",
        ]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name

    def get_product_name(self, obj):
        return obj.loan_product.name

    def _viewer_guarantor(self, obj):
        # Tagged by the viewset so the lookup is not repeated per row.
        return getattr(obj, "_viewer_guarantor", None)

    def get_guarantor_status(self, obj):
        guarantor = self._viewer_guarantor(obj)
        return guarantor.status if guarantor else None

    def get_guarantor_id(self, obj):
        guarantor = self._viewer_guarantor(obj)
        return str(guarantor.id) if guarantor else None


class LoanApplicationCreateSerializer(serializers.ModelSerializer):
    guarantor_member_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="List of MemberProfile IDs to serve as guarantors.",
    )

    class Meta:
        model = LoanApplication
        fields = [
            "loan_product", "amount_requested", "purpose",
            "term_months", "guarantor_member_ids",
        ]

    def validate_term_months(self, value):
        product_id = self.initial_data.get("loan_product")
        if not product_id:
            return value

        request = self.context.get("request")
        tenant = getattr(request, "tenant", None)

        # Scoped to the caller's own society — a product id belonging to
        # another tenant must not influence this validation.
        products = LoanProduct.objects.all()
        if tenant is not None:
            products = products.filter(tenant=tenant)

        product = products.filter(id=product_id).first()
        if not product:
            return value

        max_term = product.max_term_months
        if tenant is not None:
            # The society's rule set may cap the term below the product's own
            # ceiling.
            from .services import effective_max_term_months

            max_term = effective_max_term_months(tenant, product)

        if value < product.min_term_months or value > max_term:
            raise serializers.ValidationError(
                f"Term must be between {product.min_term_months} and {max_term} months."
            )
        return value


class RepaymentScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = RepaymentSchedule
        fields = [
            "id", "installment_no", "due_cycle", "principal_component",
            "interest_component", "amount_due", "amount_received",
            "status", "paid_at",
        ]
        read_only_fields = fields


class LoanSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    total_paid = serializers.ReadOnlyField()
    outstanding_balance = serializers.ReadOnlyField()
    repayment_schedule = RepaymentScheduleSerializer(many=True, read_only=True)

    class Meta:
        model = Loan
        fields = [
            "id", "application", "member_name", "principal_amount",
            "approved_amount", "interest_rate", "interest_method", "term_months",
            "total_repayable", "monthly_installment", "status",
            "total_paid", "outstanding_balance", "disbursement_mode",
            "opened_at", "closed_at", "repayment_schedule",
        ]
        read_only_fields = fields

    def get_member_name(self, obj):
        return obj.application.member_profile.user.full_name


class LoanApprovalSerializer(serializers.Serializer):
    """Serializer for manual loan approval/rejection."""
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(required=False, default="")
    comments = serializers.CharField(required=False, default="")


class EligibilityCheckSerializer(serializers.Serializer):
    """Serializer for eligibility check request."""
    loan_product_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    term_months = serializers.IntegerField(min_value=1, required=False)


class LoanQuoteSerializer(serializers.Serializer):
    """
    Request body for a repayment quote.

    A member asks "what will this cost me?" — the answer is the same
    calculation that writes the loan contract, so it is never a guess.
    """

    loan_product_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    term_months = serializers.IntegerField(min_value=1)


class RepaymentQuoteSerializer(serializers.Serializer):
    """The priced loan — a read-only view of `RepaymentQuote`."""

    principal = serializers.CharField()
    annual_rate = serializers.CharField()
    term_months = serializers.IntegerField()
    interest_method = serializers.CharField()
    interest_method_label = serializers.CharField()
    total_interest = serializers.CharField()
    total_repayable = serializers.CharField()
    monthly_installment = serializers.CharField()
    schedule = serializers.ListField(child=serializers.DictField())

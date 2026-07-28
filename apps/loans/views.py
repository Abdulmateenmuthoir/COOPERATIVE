"""
Loans app views — Loan Products, Applications, Guarantors, Approval, and Repayments.
"""
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditing.services import create_audit_log
from common.mixins import TenantScopedViewSetMixin
from common.permissions import IsExecutiveOrAbove, IsTenantMember

from .engine import LoanApprovalEngine, LoanEligibilityEngine
from .models import (
    Loan,
    LoanApplication,
    LoanGuarantor,
    LoanProduct,
)
from .serializers import (
    EligibilityCheckSerializer,
    LoanApprovalSerializer,
    LoanApplicationCreateSerializer,
    LoanApplicationDetailSerializer,
    LoanApplicationListSerializer,
    LoanGuarantorSerializer,
    LoanProductSerializer,
    LoanSerializer,
)


class LoanProductViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Manage loan products (rule packages) for a tenant.
    """

    queryset = LoanProduct.objects.all()
    serializer_class = LoanProductSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsTenantMember()]
        return [IsExecutiveOrAbove()]


class LoanApplicationViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Loan application lifecycle management.
    """

    queryset = LoanApplication.objects.select_related("member_profile__user", "loan_product")
    permission_classes = [IsTenantMember]

    def get_serializer_class(self):
        if self.action == "list":
            return LoanApplicationListSerializer
        if self.action == "create":
            return LoanApplicationCreateSerializer
        return LoanApplicationDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        # Regular members only see their own applications
        if not self.request.user.is_platform_user:
            from apps.users.models import Membership
            membership = Membership.objects.filter(
                tenant=self.request.tenant,
                user=self.request.user,
                status=Membership.Status.ACTIVE,
            ).first()
            if membership and membership.role.code == "MEMBER":
                from apps.users.models import MemberProfile
                profile = MemberProfile.objects.filter(
                    tenant=self.request.tenant, user=self.request.user
                ).first()
                if profile:
                    qs = qs.filter(member_profile=profile)
        return qs

    def perform_create(self, serializer):
        """Create loan application with guarantors."""
        from apps.users.models import MemberProfile

        profile = MemberProfile.objects.filter(
            tenant=self.request.tenant, user=self.request.user
        ).first()

        if not profile:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"detail": "Member profile not found."})

        guarantor_ids = serializer.validated_data.pop("guarantor_member_ids", [])

        application = serializer.save(
            tenant=self.request.tenant,
            member_profile=profile,
            status=LoanApplication.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )

        # Create guarantor records
        for gid in guarantor_ids:
            guarantor_profile = MemberProfile.objects.filter(
                tenant=self.request.tenant, id=gid
            ).first()
            if guarantor_profile:
                LoanGuarantor.objects.create(
                    tenant=self.request.tenant,
                    application=application,
                    guarantor_member=guarantor_profile,
                )

        # Evaluate eligibility. Guarantors have not confirmed yet at submission time,
        # so any product requiring them lands in GUARANTOR_PENDING rather than approved.
        engine = LoanEligibilityEngine(profile, application.loan_product, application=application)
        result = engine.evaluate(application.amount_requested)
        application.rule_evaluation = result.to_dict()
        application.evaluated_at = timezone.now()

        if result.eligible and result.approval_mode == "auto":
            application.save()
            # auto_approve creates the Loan and repayment schedule, then marks disbursed.
            LoanApprovalEngine.auto_approve(application)
        elif result.eligible:
            application.save()
            LoanApprovalEngine.escalate_to_executives(application)
        else:
            if result.blocked_on_guarantors:
                application.status = LoanApplication.Status.GUARANTOR_PENDING
            else:
                application.status = LoanApplication.Status.REJECTED
                application.rejection_reason = result.message
            application.save()

        create_audit_log(
            request=self.request,
            action_code="loan_application_submitted",
            action_category="create",
            description=f"Loan application ₦{application.amount_requested} — {application.status}",
            entity_type="LoanApplication",
            entity_id=str(application.id),
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve_or_reject(self, request, pk=None):
        """
        POST /api/v1/loans/applications/{id}/approve/
        Manual approval or rejection by executives.
        """
        application = self.get_object()
        serializer = LoanApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data["decision"] == "approve":
            loan = LoanApprovalEngine.manual_approve(
                application, request.user, serializer.validated_data.get("comments", "")
            )
            create_audit_log(
                request=request,
                action_code="loan_approved",
                action_category="approve",
                description=f"Loan ₦{application.amount_requested} approved",
                entity_type="LoanApplication",
                entity_id=str(application.id),
            )
            return Response({
                "detail": "Loan approved.",
                "loan_id": str(loan.id),
            })
        else:
            LoanApprovalEngine.reject(
                application, request.user,
                serializer.validated_data.get("reason", ""),
                serializer.validated_data.get("comments", ""),
            )
            create_audit_log(
                request=request,
                action_code="loan_rejected",
                action_category="reject",
                description=f"Loan ₦{application.amount_requested} rejected",
                entity_type="LoanApplication",
                entity_id=str(application.id),
            )
            return Response({"detail": "Loan rejected."})

    @action(detail=True, methods=["post"], url_path="confirm-guarantor")
    def confirm_guarantor(self, request, pk=None):
        """
        POST /api/v1/loans/applications/{id}/confirm-guarantor/
        A guarantor confirms or declines their commitment.
        """
        application = self.get_object()
        from apps.users.models import MemberProfile

        profile = MemberProfile.objects.filter(
            tenant=request.tenant, user=request.user
        ).first()

        guarantor = LoanGuarantor.objects.filter(
            application=application, guarantor_member=profile
        ).first()

        if not guarantor:
            return Response(
                {"detail": "You are not a guarantor for this application."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        decision = request.data.get("decision", "confirm")
        if decision == "confirm":
            guarantor.status = LoanGuarantor.Status.CONFIRMED
            guarantor.confirmed_at = timezone.now()
            guarantor.save()

            # Nobody left to hear from — re-run the rules now that consent is in.
            still_pending = application.guarantors.filter(
                status=LoanGuarantor.Status.PENDING
            ).exists()

            if not still_pending and application.status == LoanApplication.Status.GUARANTOR_PENDING:
                engine = LoanEligibilityEngine(
                    application.member_profile,
                    application.loan_product,
                    application=application,
                )
                result = engine.evaluate(application.amount_requested)
                application.rule_evaluation = result.to_dict()
                application.evaluated_at = timezone.now()
                application.save(update_fields=["rule_evaluation", "evaluated_at", "updated_at"])

                if result.eligible and result.approval_mode == "auto":
                    LoanApprovalEngine.auto_approve(application)
                elif result.eligible:
                    LoanApprovalEngine.escalate_to_executives(application)

            return Response({"detail": "Guarantor confirmation recorded."})
        else:
            guarantor.status = LoanGuarantor.Status.DECLINED
            guarantor.decline_reason = request.data.get("reason", "")
            guarantor.save()
            return Response({"detail": "Guarantor declined."})


class EligibilityCheckView(viewsets.ViewSet):
    """
    Check loan eligibility.
    POST /api/v1/loans/eligibility/
    """

    permission_classes = [IsTenantMember]

    def create(self, request):
        serializer = EligibilityCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.users.models import MemberProfile
        profile = MemberProfile.objects.filter(
            tenant=request.tenant, user=request.user
        ).first()

        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)

        product = LoanProduct.objects.filter(
            tenant=request.tenant, id=serializer.validated_data["loan_product_id"]
        ).first()

        if not product:
            return Response({"detail": "Loan product not found."}, status=404)

        engine = LoanEligibilityEngine(profile, product)
        amount = serializer.validated_data.get("amount")
        result = engine.evaluate(amount)

        return Response(result.to_dict())


class LoanViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Active loans with repayment schedules.
    GET /api/v1/loans/active/
    """

    queryset = Loan.objects.select_related("application__member_profile__user").prefetch_related("repayment_schedule")
    serializer_class = LoanSerializer
    permission_classes = [IsTenantMember]

    def get_queryset(self):
        qs = super().get_queryset()
        # Members see only their own loans
        from apps.users.models import Membership, MemberProfile
        membership = Membership.objects.filter(
            tenant=self.request.tenant,
            user=self.request.user,
            status=Membership.Status.ACTIVE,
        ).first()
        if membership and membership.role.code == "MEMBER":
            profile = MemberProfile.objects.filter(
                tenant=self.request.tenant, user=self.request.user
            ).first()
            if profile:
                qs = qs.filter(application__member_profile=profile)
        return qs

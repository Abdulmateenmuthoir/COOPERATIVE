"""
Loans app views — Loan Products, Applications, Guarantors, Approval, and Repayments.
"""
from django.db.models import Q
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditing.services import create_audit_log
from common.mixins import TenantScopedViewSetMixin
from common.permissions import (
    HasTenantPermission,
    IsExecutiveOrAbove,
    IsTenantMember,
)

from .engine import LoanApprovalEngine, LoanEligibilityEngine
from .interest import InterestCalculationError, calculate_repayment
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
    LoanGuaranteeRequestSerializer,
    LoanGuarantorSerializer,
    LoanProductSerializer,
    LoanQuoteSerializer,
    LoanSerializer,
)
from .services import (
    default_interest_method,
    default_interest_rate,
    effective_max_term_months,
)


class LoanProductViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Manage loan products (rule packages) for a tenant.
    """

    queryset = LoanProduct.objects.all()
    serializer_class = LoanProductSerializer
    search_fields = ["name", "description"]
    filterset_fields = ["is_active"]
    ordering_fields = ["name", "max_amount", "interest_rate", "created_at"]

    def get_permissions(self):
        if self.action in ["list", "retrieve", "product_eligibility", "estimate"]:
            return [IsTenantMember()]
        # Loan products are society configuration — a rule package, not a
        # running task. Only the society admin configures them, expressed as the
        # `manage_loan_products` permission (only SOCIETY_ADMIN holds it).
        return [HasTenantPermission(permission_code="manage_loan_products")]

    def perform_create(self, serializer):
        """
        Create a product, filling in the society's house rate and interest
        basis when the caller did not state them.

        The rule set lets a cooperative set its rate and basis once, so
        every product it creates starts from the same footing.
        """
        tenant = self.request.tenant
        defaults = {}

        if "interest_rate" not in serializer.validated_data:
            rate = default_interest_rate(tenant)
            if rate is not None:
                defaults["interest_rate"] = rate

        if "interest_method" not in serializer.validated_data:
            method = default_interest_method(tenant)
            if method is not None:
                defaults["interest_method"] = method

        previous = serializer.validated_data.get("previous_version")
        if previous and previous.tenant_id != tenant.id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"previous_version": "Must belong to this society."})
        if previous and (not previous.is_active or previous.next_versions.exists()):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"previous_version": "Choose the active latest product version."})
        version = previous.version + 1 if previous else 1
        product = serializer.save(tenant=tenant, version=version, **defaults)
        if previous:
            previous.is_active = False
            previous.save(update_fields=["is_active", "updated_at"])

    def perform_update(self, serializer):
        product = self.get_object()
        sensitive = set(serializer.validated_data) - {"description", "is_active"}
        if sensitive and product.applications.exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({
                "detail": "Loan terms with existing applications cannot be edited. Create a new loan product version instead."
            })
        serializer.save(version=product.version + 1)

    @action(detail=True, methods=["get"], url_path="eligibility")
    def product_eligibility(self, request, pk=None):
        from apps.users.models import MemberProfile
        product = self.get_object()
        profile = MemberProfile.objects.filter(tenant=request.tenant, user=request.user).first()
        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)
        amount = request.query_params.get("amount")
        try:
            amount = Decimal(amount) if amount is not None else None
            term = int(request.query_params["term_months"]) if "term_months" in request.query_params else None
        except (ValueError, TypeError, InvalidOperation):
            return Response({"detail": "amount and term_months must be valid numeric values."}, status=400)
        if amount is not None and (not amount.is_finite() or amount <= 0):
            return Response({"amount": "Must be a finite amount greater than zero."}, status=400)
        result = LoanEligibilityEngine(profile, product).evaluate(amount)
        data = result.to_dict()
        if term is not None:
            max_term = effective_max_term_months(request.tenant, product)
            if term < product.min_term_months or term > max_term:
                return Response({"detail": f"Term must be between {product.min_term_months} and {max_term} months."}, status=400)
            try:
                data["quote"] = calculate_repayment(amount or result.max_borrowable, product.interest_rate, term, method=product.interest_method, rate_period=product.rate_period).to_dict()
            except InterestCalculationError as exc:
                return Response({"detail": str(exc)}, status=400)
        return Response(data)

    @action(detail=True, methods=["post"], url_path="estimate")
    def estimate(self, request, pk=None):
        product = self.get_object()
        serializer = LoanQuoteSerializer(data={**request.data, "loan_product_id": str(product.id)})
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data["amount"]
        term = serializer.validated_data["term_months"]
        max_term = effective_max_term_months(request.tenant, product)
        if term < product.min_term_months or term > max_term:
            return Response({"detail": f"Term must be between {product.min_term_months} and {max_term} months."}, status=400)
        try:
            return Response(calculate_repayment(amount, product.interest_rate, term, method=product.interest_method, rate_period=product.rate_period).to_dict())
        except InterestCalculationError as exc:
            return Response({"detail": str(exc)}, status=400)


class LoanApplicationViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Loan application lifecycle management.
    """

    queryset = LoanApplication.objects.select_related("member_profile__user", "loan_product")
    permission_classes = [IsTenantMember]
    search_fields = [
        "member_profile__user__email",
        "member_profile__user__first_name",
        "member_profile__user__last_name",
        "loan_product__name",
        "purpose",
    ]
    filterset_fields = ["status"]
    ordering_fields = ["created_at", "amount_requested", "status", "submitted_at"]

    # Deciding an application is an officer act, not a member one. The
    # `approve_loans` permission is held by EXECUTIVE and SOCIETY_ADMIN only —
    # a MEMBER (whose queryset resolves to their own applications) and a
    # read-only COMMITTEE_MEMBER are both refused.
    required_permissions = ["approve_loans"]

    def get_permissions(self):
        if self.action == "approve_or_reject":
            return [HasTenantPermission()]
        return [IsTenantMember()]

    def get_serializer_class(self):
        if self.action == "list":
            return LoanApplicationListSerializer
        if self.action == "create":
            return LoanApplicationCreateSerializer
        if self.action == "retrieve":
            # A guarantor only sees the restricted view of an application.
            if self._viewer_is_officer_or_applicant():
                return LoanApplicationDetailSerializer
            return LoanGuaranteeRequestSerializer
        return LoanApplicationDetailSerializer

    def _viewer_profile(self):
        """The member profile of the signed-in user in this tenant, if any."""
        from apps.users.models import MemberProfile

        return MemberProfile.objects.filter(
            tenant=self.request.tenant, user=self.request.user
        ).first()

    def _viewer_membership(self):
        from apps.users.models import Membership

        return Membership.objects.filter(
            tenant=self.request.tenant,
            user=self.request.user,
            status=Membership.Status.ACTIVE,
        ).first()

    def _viewer_is_officer_or_applicant(self):
        """
        True when the signed-in user is a society officer (anything other
        than MEMBER) or the applicant on the application being read.
        """
        if self.request.user.is_platform_user:
            return True

        membership = self._viewer_membership()
        if not membership:
            return False
        if membership.role.code != "MEMBER":
            return True

        profile = self._viewer_profile()
        if not profile:
            return False

        return LoanApplication.objects.filter(
            pk=self.kwargs.get("pk"), member_profile=profile
        ).exists()

    def get_queryset(self):
        qs = super().get_queryset()
        # Regular members see their own applications *and* any application
        # where they are named as a guarantor. `?scope=` narrows that down to
        # one side of the split.
        if not self.request.user.is_platform_user:
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
                    scope = (self.request.query_params.get("scope") or "").lower()
                    if scope == "mine":
                        qs = qs.filter(member_profile=profile)
                    elif scope == "guarantor":
                        qs = qs.filter(guarantors__guarantor_member=profile).distinct()
                    else:
                        qs = qs.filter(
                            Q(member_profile=profile)
                            | Q(guarantors__guarantor_member=profile)
                        ).distinct()
        return qs

    def retrieve(self, request, *args, **kwargs):
        """Serve the restricted view when the viewer is only a guarantor."""
        instance = self.get_object()
        serializer_class = self.get_serializer_class()

        if serializer_class is LoanGuaranteeRequestSerializer:
            self._attach_viewer_guarantor(instance)

        serializer = serializer_class(instance, context=self.get_serializer_context())
        return Response(serializer.data)

    def _attach_viewer_guarantor(self, application):
        """Tag an application with the viewer's own guarantor record."""
        profile = self._viewer_profile()
        if profile is None:
            return None

        guarantor = application.guarantors.filter(
            guarantor_member=profile
        ).first()
        application._viewer_guarantor = guarantor
        return guarantor

    @action(detail=True, methods=["get"], url_path="guarantee-request")
    def guarantee_request(self, request, pk=None):
        """
        GET /api/v1/loans/applications/{id}/guarantee-request/
        The restricted view of an application, from the point of view of the
        signed-in user as a guarantor.
        """
        application = self.get_object()
        self._attach_viewer_guarantor(application)

        serializer = LoanGuaranteeRequestSerializer(
            application, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="guarantor-requests")
    def guarantor_requests(self, request):
        """
        GET /api/v1/loans/applications/guarantor-requests/
        Applications where the signed-in member is named as a guarantor.
        """
        profile = self._viewer_profile()
        if profile is None:
            return Response([])

        applications = (
            LoanApplication.objects.filter(
                tenant=request.tenant, guarantors__guarantor_member=profile
            )
            .select_related("loan_product", "member_profile__user")
            .prefetch_related("guarantors")
            .distinct()
        )

        for application in applications:
            application._viewer_guarantor = next(
                (
                    guarantor
                    for guarantor in application.guarantors.all()
                    if guarantor.guarantor_member_id == profile.id
                ),
                None,
            )

        serializer = LoanGuaranteeRequestSerializer(
            applications, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        """
        Create an application and return the *detail* representation.

        The create serializer only carries the submitted fields, so the
        response would not carry the new id, the evaluated status or the
        guarantor records. The client needs those to link to the application
        it just created.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        detail = LoanApplicationDetailSerializer(
            serializer.instance, context=self.get_serializer_context()
        )
        return Response(detail.data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        """Create loan application with guarantors."""
        from apps.users.models import MemberProfile
        from apps.notifications.services import notify_guarantor_request

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
            terms_snapshot={
                "product_id": str(serializer.validated_data["loan_product"].id),
                "product_version": serializer.validated_data["loan_product"].version,
                "name": serializer.validated_data["loan_product"].name,
                "min_membership_months": serializer.validated_data["loan_product"].min_membership_months,
                "min_contribution_months": serializer.validated_data["loan_product"].min_contribution_months,
                "guarantor_required_count": serializer.validated_data["loan_product"].guarantor_required_count,
                "min_amount": str(serializer.validated_data["loan_product"].min_amount) if serializer.validated_data["loan_product"].min_amount is not None else None,
                "max_amount": str(serializer.validated_data["loan_product"].max_amount) if serializer.validated_data["loan_product"].max_amount is not None else None,
                "max_multiplier": str(serializer.validated_data["loan_product"].max_multiplier),
                "interest_rate": str(serializer.validated_data["loan_product"].interest_rate),
                "rate_period": serializer.validated_data["loan_product"].rate_period,
                "interest_method": serializer.validated_data["loan_product"].interest_method,
                "min_term_months": serializer.validated_data["loan_product"].min_term_months,
                "max_term_months": serializer.validated_data["loan_product"].max_term_months,
                "required_share_units": serializer.validated_data["loan_product"].required_share_units,
                "contribution_base": serializer.validated_data["loan_product"].contribution_base,
                "contribution_lookback_months": serializer.validated_data["loan_product"].contribution_lookback_months,
            },
        )

        # Create guarantor records
        for gid in guarantor_ids:
            guarantor_profile = MemberProfile.objects.filter(
                tenant=self.request.tenant, id=gid
            ).first()
            if guarantor_profile:
                guarantor = LoanGuarantor.objects.create(
                    tenant=self.request.tenant,
                    application=application,
                    guarantor_member=guarantor_profile,
                )
                notify_guarantor_request(application, guarantor)

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
        from apps.notifications.services import notify_guarantor_response

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

            notify_guarantor_response(application, guarantor)
            return Response({"detail": "Guarantor confirmation recorded."})
        else:
            guarantor.status = LoanGuarantor.Status.DECLINED
            guarantor.decline_reason = request.data.get("reason", "")
            guarantor.save()
            notify_guarantor_response(application, guarantor)
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
        term = serializer.validated_data.get("term_months")
        result = engine.evaluate(amount)

        data = result.to_dict()

        # When the member has told us the amount and the term, price the
        # loan in the same breath — one call, one answer.
        if amount is not None and term:
            max_term = effective_max_term_months(request.tenant, product)
            if term < product.min_term_months or term > max_term:
                return Response({"detail": f"Term must be between {product.min_term_months} and {max_term} months."}, status=400)
            try:
                quote = calculate_repayment(
                    amount,
                    product.interest_rate,
                    term,
                    method=product.interest_method,
                    rate_period=product.rate_period,
                )
            except InterestCalculationError as exc:
                return Response({"detail": str(exc)}, status=400)
            data["quote"] = quote.to_dict()

        return Response(data)


class LoanQuoteView(viewsets.ViewSet):
    """
    Price a loan before applying.
    POST /api/v1/loans/quote/
    """

    permission_classes = [IsTenantMember]

    def create(self, request):
        serializer = LoanQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        product = LoanProduct.objects.filter(
            tenant=request.tenant, id=serializer.validated_data["loan_product_id"]
        ).first()

        if not product:
            return Response({"detail": "Loan product not found."}, status=404)

        term = serializer.validated_data["term_months"]
        max_term = effective_max_term_months(request.tenant, product)

        if term < product.min_term_months or term > max_term:
            return Response(
                {"detail": f"The repayment term must be between {product.min_term_months} and {max_term} months."},
                status=400,
            )

        try:
            quote = calculate_repayment(
                serializer.validated_data["amount"],
                product.interest_rate,
                term,
                method=product.interest_method,
                rate_period=product.rate_period,
            )
        except InterestCalculationError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(quote.to_dict())


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

"""
Contributions app views — Plans, Cycles, Entries, Ledger, and Member Balance.
"""
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditing.services import audit_action, create_audit_log
from common.mixins import TenantScopedViewSetMixin
from common.permissions import (
    HasTenantPermission,
    IsExecutiveOrAbove,
    IsTenantMember,
)

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
    DividendDeclaration,
    DividendEntitlement,
    ShareholdingSnapshot,
)
from .serializers import (
    BulkConfirmSerializer,
    ContributionConfirmSerializer,
    ContributionCycleSerializer,
    ContributionEntrySerializer,
    ContributionPlanSerializer,
    FinancialAdjustmentSerializer,
    FinancialLedgerSerializer,
    MemberBalanceSerializer,
    PenaltyEntrySerializer,
    ShareProductSerializer,
    ShareholdingSerializer,
    ExitRequestSerializer,
    ExitReviewSerializer,
    MemberContributionAgreementSerializer,
    DividendDeclarationSerializer,
    DividendProposalSerializer,
    DividendApprovalSerializer,
    DividendEntitlementSerializer,
    DividendPaymentSerializer,
)
from .services import (
    bulk_confirm_contributions,
    confirm_contribution,
    generate_cycle_entries,
    get_member_contribution_summary,
)


class ContributionPlanViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Manage contribution plans for a tenant.
    GET/POST /api/v1/contributions/plans/
    """

    queryset = ContributionPlan.objects.all()
    serializer_class = ContributionPlanSerializer
    search_fields = ["plan_name", "description"]
    # `is_active` is a model property (effective date range), not a column, so
    # it cannot be filtered server-side.
    filterset_fields = ["is_default"]
    ordering_fields = ["plan_name", "amount_fixed", "effective_from", "created_at"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsTenantMember()]
        # Plans are society configuration, not a running task: creating,
        # editing and ending them is a society-admin act, expressed as the
        # `manage_contribution_plans` permission (only SOCIETY_ADMIN holds it).
        return [HasTenantPermission(permission_code="manage_contribution_plans")]

    def perform_update(self, serializer):
        plan = self.get_object()
        serializer.save(policy_version=plan.policy_version + 1)


class ContributionCycleViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Manage monthly contribution cycles.
    """

    queryset = ContributionCycle.objects.all()
    serializer_class = ContributionCycleSerializer

    # Reading a cycle's entries and penalties is an officer act, gated on the
    # `view_financials` permission. EXECUTIVE, SOCIETY_ADMIN and the
    # read-only COMMITTEE_MEMBER all hold it; a plain MEMBER does not, and
    # must not see the society's contribution detail.
    required_permissions = ["view_financials"]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsTenantMember()]
        if self.action in ["entries", "penalties"]:
            return [HasTenantPermission()]
        return [IsExecutiveOrAbove()]
    def perform_create(self, serializer):
        """Create a new cycle and auto-generate entries for all active members."""
        cycle = serializer.save(
            tenant=self.request.tenant,
            generated_by=self.request.user,
            generated_at=timezone.now(),
        )
        entries_count = generate_cycle_entries(cycle)

        create_audit_log(
            request=self.request,
            action_code="cycle_created",
            action_category="create",
            description=f"Created contribution cycle {cycle.period_display} with {entries_count} entries",
            entity_type="ContributionCycle",
            entity_id=str(cycle.id),
        )

    @action(detail=True, methods=["get"])
    def entries(self, request, pk=None):
        """
        GET /api/v1/contributions/cycles/{id}/entries/
        List all contribution entries for this cycle.
        """
        cycle = self.get_object()
        entries = ContributionEntry.objects.filter(
            tenant=request.tenant, cycle=cycle
        ).select_related("member_profile__user")

        # Filter by status if provided
        entry_status = request.query_params.get("status")
        if entry_status:
            entries = entries.filter(status=entry_status)

        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = ContributionEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ContributionEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="confirm")
    @audit_action("bulk_confirm_contributions", "approve", "Bulk confirmed contributions")
    def confirm_entries(self, request, pk=None):
        """
        POST /api/v1/contributions/cycles/{id}/confirm/
        Bulk confirm all pending entries in this cycle.
        """
        cycle = self.get_object()

        if cycle.status == ContributionCycle.Status.CLOSED:
            return Response(
                {"detail": "This cycle is already closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = BulkConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        entries_data = serializer.validated_data.get("entries")

        count = bulk_confirm_contributions(cycle, request.user, entries_data)

        return Response({
            "detail": f"Successfully confirmed {count} contributions.",
            "confirmed_count": count,
        })

    @action(detail=True, methods=["get"])
    def penalties(self, request, pk=None):
        """
        GET /api/v1/contributions/cycles/{id}/penalties/
        List penalties for this cycle.
        """
        cycle = self.get_object()
        penalties = PenaltyEntry.objects.filter(
            tenant=request.tenant, cycle=cycle
        ).select_related("member_profile__user")
        serializer = PenaltyEntrySerializer(penalties, many=True)
        return Response(serializer.data)


class ContributionEntryViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Individual contribution entry management.
    """

    queryset = ContributionEntry.objects.select_related("member_profile__user", "cycle")
    serializer_class = ContributionEntrySerializer
    permission_classes = [IsExecutiveOrAbove]

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """
        POST /api/v1/contributions/entries/{id}/confirm/
        Confirm a single contribution entry.
        """
        entry = self.get_object()
        serializer = ContributionConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_entry = confirm_contribution(
            entry=entry,
            amount_received=serializer.validated_data["amount_received"],
            confirmed_by=request.user,
            source_reference=serializer.validated_data.get("source_reference", ""),
        )

        return Response(ContributionEntrySerializer(updated_entry).data)


class MyContributionsViewSet(TenantScopedViewSetMixin, viewsets.GenericViewSet):
    """
    Member's own contribution views.
    GET /api/v1/contributions/my/
    GET /api/v1/contributions/my/balance/

    A GenericViewSet, not a plain ViewSet: the list action paginates, and
    `paginate_queryset` only exists on GenericAPIView.
    """

    permission_classes = [IsTenantMember]
    serializer_class = ContributionEntrySerializer

    def list(self, request):
        """Get own contribution history."""
        from apps.users.models import MemberProfile

        profile = MemberProfile.objects.filter(
            tenant=request.tenant, user=request.user
        ).first()

        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)

        entries = ContributionEntry.objects.filter(
            tenant=request.tenant, member_profile=profile
        ).select_related("cycle").order_by("-cycle__cycle_year", "-cycle__cycle_month")

        page = self.paginate_queryset(entries)
        if page is not None:
            serializer = ContributionEntrySerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ContributionEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def balance(self, request):
        """Get own current balance and contribution summary."""
        from apps.users.models import MemberProfile

        profile = MemberProfile.objects.filter(
            tenant=request.tenant, user=request.user
        ).first()

        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)

        summary = get_member_contribution_summary(profile)
        serializer = MemberBalanceSerializer(summary)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """Detailed compulsory contribution progress for the signed-in member."""
        from apps.users.models import MemberProfile
        from .models import ContributionPlan
        profile = MemberProfile.objects.filter(tenant=request.tenant, user=request.user).first()
        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)
        data = get_member_contribution_summary(profile)
        plan = ContributionPlan.objects.filter(tenant=request.tenant, is_default=True).order_by("-effective_from").first()
        entries = ContributionEntry.objects.filter(
            tenant=request.tenant, member_profile=profile,
            entry_type=ContributionEntry.EntryType.REGULAR,
        ).select_related("cycle").order_by("-cycle__cycle_year", "-cycle__cycle_month")
        qualifying = 0
        for entry in entries:
            if entry.status != ContributionEntry.Status.CONFIRMED or entry.amount_received < entry.amount_due:
                break
            qualifying += 1
        data.update({
            "required_amount": str(plan.minimum_amount or plan.amount_fixed) if plan else None,
            "frequency": "monthly",
            "qualifying_periods": plan.qualifying_periods if plan else None,
            "minimum_paid_periods": plan.minimum_paid_periods if plan else None,
            "minimum_paid_percentage": str(plan.minimum_paid_percentage) if plan and plan.minimum_paid_percentage is not None else None,
            "consecutive_paid_periods": qualifying,
            "restricted_during_active_membership": bool(plan and plan.withdrawal_policy == "exit_only"),
        })
        return Response(data)


class ShareProductViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = ShareProduct.objects.all()
    serializer_class = ShareProductSerializer
    permission_classes = [IsTenantMember]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsTenantMember()]
        return [HasTenantPermission(permission_code="manage_contribution_plans")]

    def perform_create(self, serializer):
        from django.db.models import Max
        attrs = serializer.validated_data
        version = (ShareProduct.objects.filter(tenant=self.request.tenant, code=attrs["code"]).aggregate(v=Max("version"))["v"] or 0) + 1
        serializer.save(tenant=self.request.tenant, version=version)

    def perform_update(self, serializer):
        from rest_framework.exceptions import ValidationError
        product = self.get_object()
        sensitive = ["price_per_unit", "ownership_model", "min_units", "max_units", "authorized_units"]
        changed = [key for key in sensitive if key in serializer.validated_data and serializer.validated_data[key] != getattr(product, key)]
        if changed and product.holdings.exists():
            raise ValidationError({"detail": "Published share terms with subscriptions cannot be edited. Create a new product version instead."})
        serializer.save()


class ContributionAgreementViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    from .models import MemberContributionAgreement
    queryset = MemberContributionAgreement.objects.select_related("member_profile__user", "plan", "approved_by")
    serializer_class = MemberContributionAgreementSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.memberships.filter(
            tenant=self.request.tenant, status="active", role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"]
        ).exists() or self.request.user.is_platform_user:
            return qs
        return qs.filter(member_profile__user=self.request.user)

    def get_permissions(self):
        if self.action == "create":
            return [HasTenantPermission(permission_code="manage_contribution_plans")]
        return [IsTenantMember()]

    def perform_create(self, serializer):
        serializer.save(
            tenant=self.request.tenant,
            approved_by=self.request.user,
            policy_version=serializer.validated_data["plan"].policy_version,
        )


class DividendDeclarationViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = DividendDeclaration.objects.select_related("proposed_by", "approved_by").prefetch_related("entitlements")
    serializer_class = DividendDeclarationSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        return [HasTenantPermission(permission_code="manage_contribution_plans")]

    @action(detail=False, methods=["get"], url_path="eligibility-preview")
    def eligibility_preview(self, request):
        from datetime import date
        from decimal import Decimal, InvalidOperation
        record_date_raw = request.query_params.get("record_date")
        rate_raw = request.query_params.get("per_share_amount")
        if not record_date_raw or not rate_raw:
            return Response({"detail": "record_date and per_share_amount are required."}, status=400)
        try:
            record_date = date.fromisoformat(record_date_raw)
            per_share_amount = Decimal(rate_raw)
        except (ValueError, InvalidOperation):
            return Response({"detail": "Provide a valid ISO date and decimal per_share_amount."}, status=400)
        if per_share_amount <= 0:
            return Response({"per_share_amount": "Must be greater than zero."}, status=400)
        holdings = Shareholding.objects.filter(
            tenant=request.tenant, status=Shareholding.Status.PAID,
            issued_at__date__lte=record_date,
        ).select_related("member_profile__user")
        grouped = {}
        for holding in holdings:
            key = holding.member_profile_id
            row = grouped.setdefault(key, {"member_profile": str(key), "member_name": holding.member_profile.user.full_name, "paid_units": 0})
            row["paid_units"] += holding.units_paid
        rows = [{**row, "amount": str(per_share_amount * row["paid_units"])} for row in grouped.values()]
        return Response({"record_date": record_date.isoformat(), "per_share_amount": str(per_share_amount), "members": rows, "total_amount": str(sum((Decimal(row["amount"]) for row in rows), Decimal("0.00")))})

    def create(self, request, *args, **kwargs):
        from django.db import transaction
        from django.utils import timezone
        form = DividendProposalSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        values = form.validated_data
        with transaction.atomic():
            declaration = DividendDeclaration.objects.create(
                tenant=request.tenant, proposed_by=request.user, **values,
            )
            holdings = Shareholding.objects.filter(
                tenant=request.tenant, status=Shareholding.Status.PAID,
                issued_at__date__lte=values["record_date"],
            ).select_related("member_profile", "product")
            snapshots = {}
            for holding in holdings:
                key = (holding.member_profile_id, holding.product_id)
                snap = snapshots.get(key)
                if not snap:
                    snap = ShareholdingSnapshot.objects.create(
                        tenant=request.tenant, declaration=declaration,
                        member_profile=holding.member_profile, product=holding.product,
                        paid_units=0, unit_price=holding.unit_price, source_holding_ids=[],
                    )
                    snapshots[key] = snap
                snap.paid_units += holding.units_paid
                snap.source_holding_ids.append(str(holding.id))
                snap.save(update_fields=["paid_units", "source_holding_ids", "updated_at"])
            by_member = {}
            for snap in snapshots.values():
                by_member[snap.member_profile_id] = by_member.get(snap.member_profile_id, 0) + snap.paid_units
            for member_id, units in by_member.items():
                DividendEntitlement.objects.create(
                    tenant=request.tenant, declaration=declaration,
                    member_profile_id=member_id, eligible_units=units,
                    amount=values["per_share_amount"] * units,
                )
        return Response(self.get_serializer(declaration).data, status=201)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        from django.utils import timezone
        declaration = self.get_object()
        if declaration.status != DividendDeclaration.Status.PROPOSED:
            return Response({"detail": "Only a proposed declaration can be approved."}, status=400)
        form = DividendApprovalSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        declaration.status = DividendDeclaration.Status.APPROVED
        declaration.agm_reference = form.validated_data["agm_reference"]
        declaration.approved_by = request.user
        declaration.approved_at = timezone.now()
        declaration.save(update_fields=["status", "agm_reference", "approved_by", "approved_at", "updated_at"])
        declaration.entitlements.update(status=DividendEntitlement.Status.PAYABLE)
        return Response(self.get_serializer(declaration).data)


class DividendEntitlementViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = DividendEntitlement.objects.select_related("member_profile__user", "declaration")
    serializer_class = DividendEntitlementSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_platform_user or self.request.user.memberships.filter(
            tenant=self.request.tenant, status="active", role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"]
        ).exists():
            return qs
        return qs.filter(member_profile__user=self.request.user)

    def get_permissions(self):
        if self.action == "record_payment":
            return [IsExecutiveOrAbove()]
        return [IsTenantMember()]

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        form = DividendPaymentSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        entitlement = self.get_object()
        if entitlement.declaration.status != DividendDeclaration.Status.APPROVED:
            return Response({"detail": "Dividend declaration is not approved."}, status=400)
        if entitlement.status != DividendEntitlement.Status.PAYABLE:
            return Response({"detail": "Only payable entitlements may be recorded."}, status=400)
        entitlement.status = form.validated_data["status"]
        entitlement.payment_reference = form.validated_data["payment_reference"]
        entitlement.recorded_by = request.user
        entitlement.save(update_fields=["status", "payment_reference", "recorded_by", "updated_at"])
        return Response(self.get_serializer(entitlement).data)


class ShareholdingViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Shareholding.objects.select_related("product", "member_profile__user")
    serializer_class = ShareholdingSerializer
    permission_classes = [IsTenantMember]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_platform_user and not self.request.user.memberships.filter(
            tenant=self.request.tenant, status="active", role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"]
        ).exists():
            return qs.filter(member_profile__user=self.request.user)
        return qs

    def get_permissions(self):
        if self.action in ["list", "retrieve", "mine"]:
            return [IsTenantMember()]
        if self.action == "create":
            return [IsTenantMember()]
        return [IsExecutiveOrAbove()]

    @action(detail=False, methods=["get"], url_path="mine", permission_classes=[IsTenantMember])
    def mine(self, request):
        rows = Shareholding.objects.filter(
            tenant=request.tenant, member_profile__user=request.user
        ).select_related("product")
        return Response(self.get_serializer(rows, many=True).data)

    def create(self, request, *args, **kwargs):
        from django.db import transaction
        from apps.users.models import MemberProfile
        is_officer = request.user.memberships.filter(
            tenant=request.tenant, status="active", role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"]
        ).exists()
        data = request.data.copy()
        if not is_officer:
            profile = MemberProfile.objects.filter(tenant=request.tenant, user=request.user).first()
            if not profile:
                return Response({"detail": "Member profile not found."}, status=404)
            data["member_profile"] = str(profile.id)
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        product = serializer.validated_data["product"]
        member = serializer.validated_data["member_profile"]
        units = serializer.validated_data["units"]
        if product.tenant_id != self.request.tenant.id or member.tenant_id != self.request.tenant.id:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("Product and member must belong to this society.")
        if not product.is_active or product.effective_from > timezone.localdate():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"product": "This share product is not accepting subscriptions."})
        if product.ownership_model == ShareProduct.OwnershipModel.UNITARY and units > 1:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"units": "Unitary share products allow one unit per holding."})
        if product.ownership_model == ShareProduct.OwnershipModel.UNITARY and Shareholding.objects.filter(
            tenant=request.tenant, product=product, member_profile=member, status__in=["subscribed", "part_paid", "paid"]
        ).exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"member_profile": "This member already holds or has subscribed to a unit."})
        if units < product.min_units:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"units": "Requested units are below this product's minimum."})
        if product.max_units and units > product.max_units:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"units": "Requested units exceed this product's maximum."})
        if product.authorized_units and product.issued_units + units > product.authorized_units:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"units": "This issue has insufficient available units."})
        with transaction.atomic():
            product = ShareProduct.objects.select_for_update().get(pk=product.pk, tenant=request.tenant)
            if product.ownership_model == ShareProduct.OwnershipModel.UNITARY and Shareholding.objects.filter(
                tenant=request.tenant, product=product, member_profile=member,
                status__in=["subscribed", "part_paid", "paid"],
            ).exists():
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"member_profile": "This member already holds or has subscribed to a unit."})
            if product.authorized_units and product.issued_units + units > product.authorized_units:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"units": "This issue has insufficient available units."})
            holding = serializer.save(tenant=request.tenant, unit_price=product.price_per_unit)
            product.issued_units += units
            product.save(update_fields=["issued_units", "updated_at"])
            from .models import ShareTransaction
            ShareTransaction.objects.create(
                tenant=request.tenant, holding=holding,
                event=ShareTransaction.Event.SUBSCRIPTION, units=units,
                amount=product.price_per_unit * units, actor=request.user,
            )
        return Response(self.get_serializer(holding).data, status=201)

    @action(detail=True, methods=["post"], url_path="record-payment")
    def record_payment(self, request, pk=None):
        from django.db import transaction
        from rest_framework import serializers as drf_serializers
        from .models import ShareTransaction
        holding = self.get_object()
        amount = drf_serializers.DecimalField(max_digits=12, decimal_places=2).run_validation(request.data.get("amount"))
        if amount <= 0:
            return Response({"amount": "Must be greater than zero."}, status=400)
        total_due = holding.unit_price * holding.units
        paid_before = holding.amount_paid
        if paid_before + amount > total_due:
            return Response({"amount": "Payment exceeds the outstanding share subscription."}, status=400)
        with transaction.atomic():
            paid_total = paid_before + amount
            old_units_paid = holding.units_paid
            holding.amount_paid = paid_total
            holding.units_paid = min(int(paid_total // holding.unit_price), holding.units)
            holding.status = Shareholding.Status.PAID if paid_total == total_due else Shareholding.Status.PART_PAID
            if holding.status == Shareholding.Status.PAID:
                holding.issued_at = timezone.now()
            holding.save(update_fields=["amount_paid", "units_paid", "status", "issued_at", "updated_at"])
            ShareTransaction.objects.create(
                tenant=request.tenant, holding=holding, event=ShareTransaction.Event.PAYMENT,
                units=holding.units_paid - old_units_paid, amount=amount, actor=request.user,
                reference=request.data.get("reference", ""),
            )
        return Response(self.get_serializer(holding).data)


class ExitRequestViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = ExitRequest.objects.select_related("member_profile__user")
    serializer_class = ExitRequestSerializer
    permission_classes = [IsTenantMember]
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        is_officer = self.request.user.memberships.filter(
            tenant=self.request.tenant, status="active", role__code__in=["SOCIETY_ADMIN", "EXECUTIVE"]
        ).exists()
        return qs if is_officer or self.request.user.is_platform_user else qs.filter(member_profile__user=self.request.user)

    def create(self, request, *args, **kwargs):
        from apps.users.models import MemberProfile, Membership
        profile = MemberProfile.objects.filter(tenant=request.tenant, user=request.user).first()
        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)
        if not Membership.objects.filter(tenant=request.tenant, user=request.user, status=Membership.Status.ACTIVE).exists():
            return Response({"detail": "Only active members may submit an exit request."}, status=400)
        if self.get_queryset().filter(member_profile=profile, status__in=["submitted", "in_review", "approved"]).exists():
            return Response({"detail": "An open exit request already exists."}, status=400)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(tenant=request.tenant, member_profile=profile)
        return Response(serializer.data, status=201)

    def get_permissions(self):
        if self.action in ["review", "mark_settled"]:
            return [IsExecutiveOrAbove()]
        return [IsTenantMember()]

    @action(detail=False, methods=["get"], url_path="estimate")
    def estimate(self, request):
        from apps.contributions.models import ContributionEntry
        from apps.users.models import MemberProfile
        from decimal import Decimal
        profile = MemberProfile.objects.filter(tenant=request.tenant, user=request.user).first()
        if not profile:
            return Response({"detail": "Member profile not found."}, status=404)
        gross = sum(ContributionEntry.objects.filter(
            tenant=request.tenant, member_profile=profile,
            entry_type=ContributionEntry.EntryType.REGULAR,
            status__in=[ContributionEntry.Status.CONFIRMED, ContributionEntry.Status.PARTIAL],
        ).values_list("amount_received", flat=True), Decimal("0.00"))
        return Response({
            "gross_compulsory_contributions": str(gross),
            "proposed_deductions": [],
            "proposed_payable": None,
            "status": "estimate_only",
            "note": "This is a contribution total, not an approved settlement. Liabilities and deductions require review and approval.",
        })

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        from django.utils import timezone
        obj = self.get_object()
        if obj.status not in [ExitRequest.Status.SUBMITTED, ExitRequest.Status.IN_REVIEW]:
            return Response({"detail": "This request has already been decided."}, status=400)
        form = ExitReviewSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        values = form.validated_data
        obj.decision_by = request.user
        obj.decision_reason = values["reason"]
        obj.decided_at = timezone.now()
        if values["decision"] == "reject":
            obj.status = ExitRequest.Status.REJECTED
        else:
            gross = values["gross_contribution_balance"]
            payable = values["proposed_payable"]
            if payable < 0 or payable > gross:
                return Response({"detail": "Proposed payable must be between zero and gross balance."}, status=400)
            obj.gross_contribution_balance = gross
            obj.proposed_payable = payable
            obj.deductions = values.get("deductions", [])
            obj.status = ExitRequest.Status.APPROVED
        obj.save()
        return Response(self.get_serializer(obj).data)

    @action(detail=True, methods=["post"], url_path="mark-settled")
    def mark_settled(self, request, pk=None):
        obj = self.get_object()
        if obj.status != ExitRequest.Status.APPROVED:
            return Response({"detail": "Only an approved settlement can be marked settled."}, status=400)
        reference = request.data.get("payment_reference", "").strip()
        if not reference:
            return Response({"payment_reference": "This field is required."}, status=400)
        obj.status = ExitRequest.Status.SETTLED
        obj.payment_reference = reference
        obj.save(update_fields=["status", "payment_reference", "updated_at"])
        return Response(self.get_serializer(obj).data)


class FinancialLedgerViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Financial ledger — read-only view of member financial history.
    GET /api/v1/contributions/ledger/?member_profile_id=xxx
    """

    queryset = FinancialLedger.objects.all()
    serializer_class = FinancialLedgerSerializer
    # The ledger is the society's financial history. It is read-only, so a
    # COMMITTEE_MEMBER — who holds `view_financials` — may read it, while a
    # plain MEMBER, who holds no permissions, may not.
    permission_classes = [HasTenantPermission]
    required_permissions = ["view_financials"]

    def get_queryset(self):
        qs = super().get_queryset()
        member_id = self.request.query_params.get("member_profile_id")
        if member_id:
            qs = qs.filter(member_profile_id=member_id)
        return qs

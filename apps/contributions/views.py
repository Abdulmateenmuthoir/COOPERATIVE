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
    IsSocietyAdmin,
    IsTenantMember,
)

from .models import (
    ContributionCycle,
    ContributionEntry,
    ContributionPlan,
    FinancialAdjustment,
    FinancialLedger,
    PenaltyEntry,
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
        # editing and ending them is a society-admin act.
        # The `manage_contribution_plans` permission code is the formal gate;
        # we fall back to the society-admin role check for backwards compatibility.
        if self.request.role == "SOCIETY_ADMIN":
            return [IsSocietyAdmin()]
        return [HasTenantPermission(permission_code="manage_contribution_plans")]


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

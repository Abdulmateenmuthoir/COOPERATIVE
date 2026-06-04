"""Schedules app views — Schedule generation and export."""
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.auditing.services import create_audit_log
from common.mixins import TenantScopedViewSetMixin
from common.permissions import IsExecutiveOrAbove

from .models import ScheduleBatch
from .serializers import (
    GenerateScheduleSerializer,
    ScheduleBatchDetailSerializer,
    ScheduleBatchSerializer,
)
from .services import export_schedule_csv, export_schedule_excel, generate_schedule


class ScheduleBatchViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    View and manage schedule batches.
    """

    queryset = ScheduleBatch.objects.all()
    permission_classes = [IsExecutiveOrAbove]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ScheduleBatchDetailSerializer
        return ScheduleBatchSerializer

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """
        POST /api/v1/schedules/generate/
        Generate a new deduction schedule for a cycle.
        """
        serializer = GenerateScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from apps.contributions.models import ContributionCycle

        cycle = ContributionCycle.objects.filter(
            tenant=request.tenant,
            id=serializer.validated_data["cycle_id"],
        ).first()

        if not cycle:
            return Response({"detail": "Cycle not found."}, status=404)

        batch = generate_schedule(
            tenant=request.tenant,
            cycle=cycle,
            generated_by=request.user,
            batch_type=serializer.validated_data["batch_type"],
        )

        create_audit_log(
            request=request,
            action_code="schedule_generated",
            action_category="create",
            description=f"Generated {batch.batch_type} schedule: {batch.member_count} members, ₦{batch.total_amount:,.2f}",
            entity_type="ScheduleBatch",
            entity_id=str(batch.id),
        )

        return Response(ScheduleBatchDetailSerializer(batch).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="export/csv")
    def export_csv(self, request, pk=None):
        """
        GET /api/v1/schedules/{id}/export/csv/
        Export schedule as CSV.
        """
        batch = self.get_object()
        csv_content = export_schedule_csv(batch)

        # Update batch status
        batch.status = ScheduleBatch.Status.EXPORTED
        batch.save(update_fields=["status", "updated_at"])

        create_audit_log(
            request=request,
            action_code="schedule_exported",
            action_category="export",
            description=f"Exported schedule as CSV",
            entity_type="ScheduleBatch",
            entity_id=str(batch.id),
        )

        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="schedule_{batch.id}.csv"'
        return response

    @action(detail=True, methods=["get"], url_path="export/excel")
    def export_excel(self, request, pk=None):
        """
        GET /api/v1/schedules/{id}/export/excel/
        Export schedule as Excel.
        """
        batch = self.get_object()
        excel_content = export_schedule_excel(batch)

        batch.status = ScheduleBatch.Status.EXPORTED
        batch.save(update_fields=["status", "updated_at"])

        create_audit_log(
            request=request,
            action_code="schedule_exported",
            action_category="export",
            description=f"Exported schedule as Excel",
            entity_type="ScheduleBatch",
            entity_id=str(batch.id),
        )

        response = HttpResponse(
            excel_content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="schedule_{batch.id}.xlsx"'
        return response

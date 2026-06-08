"""
Reports app views.
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.mixins import TenantScopedViewSetMixin
from common.permissions import IsExecutiveOrAbove

from .services import get_contribution_performance, get_executive_dashboard_summary


class ExecutiveDashboardViewSet(TenantScopedViewSetMixin, viewsets.ViewSet):
    """
    API for executive reporting dashboards.
    """
    permission_classes = [IsExecutiveOrAbove]

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """
        GET /api/v1/reports/dashboard/summary/
        Returns high-level KPI summary for the tenant.
        """
        data = get_executive_dashboard_summary(request.tenant)
        return Response(data)

    @action(detail=False, methods=["get"])
    def contributions_chart(self, request):
        """
        GET /api/v1/reports/dashboard/contributions_chart/?year=2026
        Returns monthly performance data for charts.
        """
        year = request.query_params.get("year")
        try:
            year = int(year) if year else None
        except ValueError:
            year = None

        data = get_contribution_performance(request.tenant, year)
        return Response(data)

"""
Reports app views.
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from common.mixins import TenantScopedViewSetMixin
from common.permissions import HasTenantPermission

from .services import get_contribution_performance, get_executive_dashboard_summary


class ExecutiveDashboardViewSet(TenantScopedViewSetMixin, viewsets.ViewSet):
    """
    API for executive reporting dashboards.

    Gated on the `view_reports` permission rather than a role code, so a
    read-only COMMITTEE_MEMBER can open the dashboard — it holds that
    permission — while a plain MEMBER cannot, because it holds none.
    """

    permission_classes = [HasTenantPermission]
    required_permissions = ["view_reports"]

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

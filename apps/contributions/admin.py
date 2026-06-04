from django.contrib import admin
from .models import (
    ContributionCycle, ContributionEntry, ContributionPlan,
    FinancialAdjustment, FinancialLedger, PenaltyEntry,
)


@admin.register(ContributionPlan)
class ContributionPlanAdmin(admin.ModelAdmin):
    list_display = ["tenant", "plan_name", "amount_fixed", "is_default", "is_active", "effective_from"]
    list_filter = ["tenant", "is_default"]


@admin.register(ContributionCycle)
class ContributionCycleAdmin(admin.ModelAdmin):
    list_display = ["tenant", "cycle_year", "cycle_month", "status", "generated_at"]
    list_filter = ["status", "tenant", "cycle_year"]


@admin.register(ContributionEntry)
class ContributionEntryAdmin(admin.ModelAdmin):
    list_display = ["member_profile", "cycle", "entry_type", "amount_due", "amount_received", "status"]
    list_filter = ["status", "entry_type", "tenant"]
    search_fields = ["member_profile__user__email"]


@admin.register(PenaltyEntry)
class PenaltyEntryAdmin(admin.ModelAdmin):
    list_display = ["member_profile", "cycle", "penalty_type", "amount", "status"]
    list_filter = ["status", "penalty_type", "tenant"]


@admin.register(FinancialLedger)
class FinancialLedgerAdmin(admin.ModelAdmin):
    list_display = ["member_profile", "event_type", "debit", "credit", "balance_after", "posted_at"]
    list_filter = ["event_type", "tenant"]
    readonly_fields = [f.name for f in FinancialLedger._meta.get_fields() if hasattr(f, 'name')]

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinancialAdjustment)
class FinancialAdjustmentAdmin(admin.ModelAdmin):
    list_display = ["member_profile", "adjustment_type", "amount", "approved_by", "created_at"]
    list_filter = ["adjustment_type", "tenant"]

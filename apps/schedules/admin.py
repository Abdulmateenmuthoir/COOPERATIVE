from django.contrib import admin
from .models import ScheduleBatch, ScheduleLine


@admin.register(ScheduleBatch)
class ScheduleBatchAdmin(admin.ModelAdmin):
    list_display = ["tenant", "batch_type", "status", "member_count", "total_amount", "created_at"]
    list_filter = ["status", "batch_type", "tenant"]


@admin.register(ScheduleLine)
class ScheduleLineAdmin(admin.ModelAdmin):
    list_display = ["batch", "member_profile", "contribution_amount", "repayment_amount", "penalty_amount", "total_amount"]

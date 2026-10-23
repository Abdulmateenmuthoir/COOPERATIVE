from django.contrib import admin
from .models import (
    Loan, LoanApplication, LoanApprovalStep,
    LoanGuarantor, LoanProduct, RepaymentSchedule,
)


@admin.register(LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = ["tenant", "name", "max_amount", "interest_rate", "interest_method", "is_active"]
    list_filter = ["is_active", "interest_method", "tenant"]


@admin.register(LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = ["member_profile", "loan_product", "amount_requested", "status", "created_at"]
    list_filter = ["status", "tenant"]
    search_fields = ["member_profile__user__email"]


@admin.register(LoanGuarantor)
class LoanGuarantorAdmin(admin.ModelAdmin):
    list_display = ["application", "guarantor_member", "status", "confirmed_at"]
    list_filter = ["status"]


@admin.register(LoanApprovalStep)
class LoanApprovalStepAdmin(admin.ModelAdmin):
    list_display = ["application", "actor_user", "decision", "decided_at"]
    list_filter = ["decision"]


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ["application", "approved_amount", "interest_rate", "interest_method", "status", "opened_at"]
    list_filter = ["status", "interest_method", "tenant"]


@admin.register(RepaymentSchedule)
class RepaymentScheduleAdmin(admin.ModelAdmin):
    list_display = ["loan", "installment_no", "amount_due", "amount_received", "status"]
    list_filter = ["status"]

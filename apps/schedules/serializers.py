"""Schedules app serializers."""
from rest_framework import serializers
from .models import ScheduleBatch, ScheduleLine


class ScheduleLineSerializer(serializers.ModelSerializer):
    member_name = serializers.SerializerMethodField()
    employee_no = serializers.SerializerMethodField()
    payroll_no = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleLine
        fields = [
            "id", "member_profile", "member_name", "employee_no", "payroll_no",
            "contribution_amount", "repayment_amount", "penalty_amount", "total_amount",
        ]

    def get_member_name(self, obj):
        return obj.member_profile.user.full_name

    def get_employee_no(self, obj):
        return obj.member_profile.employee_no

    def get_payroll_no(self, obj):
        return obj.member_profile.payroll_no


class ScheduleBatchSerializer(serializers.ModelSerializer):
    cycle_display = serializers.SerializerMethodField()
    generated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleBatch
        fields = [
            "id", "cycle", "cycle_display", "batch_type", "status",
            "generated_by", "generated_by_name", "total_amount",
            "member_count", "notes", "file_url", "created_at",
        ]
        read_only_fields = ["id", "generated_by", "total_amount", "member_count", "created_at"]

    def get_cycle_display(self, obj):
        return obj.cycle.period_display if obj.cycle else None

    def get_generated_by_name(self, obj):
        return obj.generated_by.full_name if obj.generated_by else None


class ScheduleBatchDetailSerializer(ScheduleBatchSerializer):
    lines = ScheduleLineSerializer(many=True, read_only=True)

    class Meta(ScheduleBatchSerializer.Meta):
        fields = ScheduleBatchSerializer.Meta.fields + ["lines"]


class GenerateScheduleSerializer(serializers.Serializer):
    cycle_id = serializers.UUIDField()
    batch_type = serializers.ChoiceField(
        choices=ScheduleBatch.BatchType.choices,
        default="combined",
    )

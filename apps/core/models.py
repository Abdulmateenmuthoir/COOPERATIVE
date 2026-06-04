"""
Core app — Tenant management models.

These models represent the SaaS infrastructure layer: tenant records,
branding, configuration, versioned business rules, and bulk import tracking.
"""
from django.db import models

from common.models import TimestampedModel


class Tenant(TimestampedModel):
    """
    Represents a cooperative society on the platform.
    Every piece of domain data is linked to a Tenant.
    ACADA is tenant #1.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"

    class OnboardingState(models.TextChoices):
        PENDING = "pending", "Pending Setup"
        CONFIGURING = "configuring", "Configuring Rules"
        IMPORTING = "importing", "Importing Members"
        ACTIVE = "active", "Operational"

    code = models.SlugField(
        max_length=50,
        unique=True,
        help_text="Unique slug identifier for the tenant (e.g., 'acada', 'futa-coop'). Used in URLs and headers.",
    )
    name = models.CharField(max_length=255, help_text="Full display name of the cooperative society.")
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    onboarding_state = models.CharField(
        max_length=20, choices=OnboardingState.choices, default=OnboardingState.PENDING
    )
    primary_contact_email = models.EmailField(help_text="Primary contact email for the cooperative leadership.")
    primary_contact_phone = models.CharField(max_length=20, blank=True, default="")
    institution_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Name of the parent institution (e.g., University of Ibadan).",
    )
    address = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code})"


class TenantBranding(TimestampedModel):
    """
    Per-tenant branding configuration.
    Each society can display their own logo and color theme.
    """

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="branding")
    logo_url = models.URLField(blank=True, default="", help_text="URL to the society's logo image.")
    primary_color = models.CharField(
        max_length=7, default="#1a56db", help_text="Primary brand color in hex (e.g., #1a56db)."
    )
    secondary_color = models.CharField(
        max_length=7, default="#7e3af2", help_text="Secondary brand color in hex."
    )
    app_name_override = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Custom app name shown to members (overrides platform name).",
    )

    def __str__(self):
        return f"Branding for {self.tenant.name}"


class TenantSettings(TimestampedModel):
    """
    Runtime settings for a tenant.
    Controls currency, timezone, locale, and notification policies.
    """

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="settings")
    currency = models.CharField(max_length=3, default="NGN", help_text="ISO 4217 currency code.")
    timezone = models.CharField(max_length=50, default="Africa/Lagos")
    locale = models.CharField(max_length=10, default="en-NG")
    financial_year_start_month = models.PositiveSmallIntegerField(
        default=1, help_text="Month number (1-12) when the financial year starts."
    )
    notification_policy = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON configuration for notification preferences: which events trigger which channels.",
    )

    class Meta:
        verbose_name_plural = "Tenant settings"

    def __str__(self):
        return f"Settings for {self.tenant.name}"


class TenantRuleSet(TimestampedModel):
    """
    Versioned business rules for a tenant.

    Rules are stored as JSON and define contribution amounts, penalty structures,
    loan eligibility thresholds, and approval workflows. Rules are versioned so
    that historical decisions can be evaluated against the rules that were active
    at the time.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rule_sets")
    version = models.PositiveIntegerField(default=1)
    active_from = models.DateField(help_text="Date from which this rule set is effective.")
    active_to = models.DateField(null=True, blank=True, help_text="Date until which this rule set is effective. Null = currently active.")
    rules = models.JSONField(
        default=dict,
        help_text="JSON object containing all business rules. Structure documented in TenantRuleSet schema.",
    )
    notes = models.TextField(blank=True, default="", help_text="Human-readable notes about this rule version.")
    created_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_rule_sets",
    )

    class Meta:
        ordering = ["-active_from"]
        unique_together = [("tenant", "version")]

    def __str__(self):
        return f"{self.tenant.name} Rules v{self.version}"

    @property
    def is_active(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.active_to:
            return self.active_from <= today <= self.active_to
        return self.active_from <= today


class TenantMemberImport(TimestampedModel):
    """
    Tracks bulk member import operations for audit purposes.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="member_imports")
    source_file_url = models.FileField(upload_to="imports/%Y/%m/", help_text="Uploaded CSV/Excel file.")
    imported_by = models.ForeignKey(
        "users.UserAccount",
        on_delete=models.SET_NULL,
        null=True,
        related_name="member_imports",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    successful_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_log = models.JSONField(default=list, blank=True, help_text="List of row-level errors.")

    def __str__(self):
        return f"Import for {self.tenant.name} ({self.status})"

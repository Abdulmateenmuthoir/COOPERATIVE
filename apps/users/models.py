"""
Users app — Authentication, RBAC, and Member Management models.

This module implements:
- Custom user model (UserAccount) with email-based auth
- Tenant-specific member profiles (MemberProfile)
- Hybrid RBAC: Role → Permission mapping + per-user overrides
- Membership: links a user to a tenant with a specific role
"""
import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from common.models import TenantScopedModel, TimestampedModel


# ─── Custom User Manager ──────────────────────────────────────────────


class UserAccountManager(BaseUserManager):
    """Custom manager for email-based authentication."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_platform_user", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


# ─── User Model ────────────────────────────────────────────────────────


class UserAccount(AbstractBaseUser, PermissionsMixin):
    """
    Global user identity. Email-based authentication.

    A single user can be a member of multiple cooperative societies via
    the Membership model. The `is_platform_user` flag identifies
    SUPER_ADMIN users who operate at the platform level.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        DEACTIVATED = "deactivated", "Deactivated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Platform-level flags
    is_platform_user = models.BooleanField(
        default=False,
        help_text="Designates whether this user is a platform administrator (SUPER_ADMIN).",
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text="Whether login must wait until the user sets a permanent password.",
    )
    is_staff = models.BooleanField(default=False, help_text="Designates whether the user can access the Django admin.")
    is_active = models.BooleanField(default=True)

    # Tracking
    date_joined = models.DateTimeField(auto_now_add=True)
    last_login = models.DateTimeField(null=True, blank=True)

    # Custom attribute for tenant context from JWT
    current_tenant_id = None  # Set by JWT authentication, not a DB field

    objects = UserAccountManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        ordering = ["last_name", "first_name"]
        verbose_name = "User Account"
        verbose_name_plural = "User Accounts"

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


# ─── Role & Permission Models ─────────────────────────────────────────


class Permission(TimestampedModel):
    """
    Canonical permission entry.
    Permissions are platform-wide definitions; roles map to them per tenant.
    """

    code = models.CharField(max_length=100, unique=True, db_index=True)
    module = models.CharField(
        max_length=50,
        help_text="The app module this permission belongs to (e.g., 'contributions', 'loans').",
    )
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["module", "code"]

    def __str__(self):
        return f"{self.module}.{self.code}"


class Role(TimestampedModel):
    """
    Role definition. Roles can be platform-global or tenant-specific.

    Platform roles (tenant=None):
        SUPER_ADMIN — platform-level administrator

    Tenant roles:
        SOCIETY_ADMIN — cooperative president / chief admin
        EXECUTIVE — treasurer, secretary, other executives
        COMMITTEE_MEMBER — advisory/oversight committee members
        MEMBER — regular cooperative member
    """

    class Scope(models.TextChoices):
        PLATFORM = "platform", "Platform"
        TENANT = "tenant", "Tenant"

    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="roles",
        help_text="Null for platform-wide roles; set for tenant-specific custom roles.",
    )
    code = models.CharField(max_length=50, db_index=True)
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=20, choices=Scope.choices, default=Scope.TENANT)
    description = models.TextField(blank=True, default="")
    permissions = models.ManyToManyField(Permission, through="RolePermission", related_name="roles")

    class Meta:
        ordering = ["scope", "code"]

    def __str__(self):
        prefix = self.tenant.code if self.tenant else "PLATFORM"
        return f"[{prefix}] {self.name}"


class RolePermission(TimestampedModel):
    """Maps permissions to roles."""

    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="role_permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="role_permissions")

    class Meta:
        unique_together = [("role", "permission")]

    def __str__(self):
        return f"{self.role.code} → {self.permission.code}"


# ─── Membership & Member Profile ──────────────────────────────────────


class Membership(TenantScopedModel):
    """
    Links a user to a tenant with a specific role.
    A user can have memberships in multiple tenants.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REMOVED = "removed", "Removed"

    user = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    approved_by = models.ForeignKey(
        UserAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_memberships",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("tenant", "user")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.email} → {self.tenant.code} ({self.role.code})"


class MemberProfile(TenantScopedModel):
    """
    Tenant-specific member details.
    Contains payroll and institutional information needed for
    the source deduction model.
    """

    class EmploymentStatus(models.TextChoices):
        ACTIVE = "active", "Active Employment"
        ON_LEAVE = "on_leave", "On Leave"
        RETIRED = "retired", "Retired"
        TERMINATED = "terminated", "Terminated"

    user = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name="member_profiles")
    employee_no = models.CharField(
        max_length=50, blank=True, default="", help_text="Employee number at the institution."
    )
    payroll_no = models.CharField(
        max_length=50, blank=True, default="", help_text="Payroll number used for deduction schedules."
    )
    department = models.CharField(max_length=200, blank=True, default="")
    faculty = models.CharField(max_length=200, blank=True, default="")
    designation = models.CharField(
        max_length=200, blank=True, default="", help_text="Job title or academic designation."
    )
    employment_status = models.CharField(
        max_length=20, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE
    )
    date_of_birth = models.DateField(null=True, blank=True)
    next_of_kin_name = models.CharField(max_length=200, blank=True, default="")
    next_of_kin_phone = models.CharField(max_length=20, blank=True, default="")
    bank_name = models.CharField(max_length=100, blank=True, default="")
    bank_account_no = models.CharField(max_length=20, blank=True, default="")
    joined_at = models.DateField(
        null=True, blank=True, help_text="Date the member officially joined the cooperative."
    )

    class Meta:
        unique_together = [("tenant", "user")]

    def __str__(self):
        return f"{self.user.full_name} @ {self.tenant.code}"


# ─── User Permission Override ─────────────────────────────────────────


class UserPermissionOverride(TenantScopedModel):
    """
    Fine-grained per-user permission override within a tenant.

    This enables the President to grant or revoke specific permissions
    from any member without changing their role. For example, revoking
    'prepare_deductions' from a Treasurer who is under review.

    All overrides are logged in the audit trail.
    """

    class Effect(models.TextChoices):
        ALLOW = "allow", "Allow"
        DENY = "deny", "Deny"

    user = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name="permission_overrides")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="user_overrides")
    effect = models.CharField(max_length=10, choices=Effect.choices)
    reason = models.TextField(blank=True, default="", help_text="Why this override was applied.")
    granted_by = models.ForeignKey(
        UserAccount,
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_overrides",
    )

    class Meta:
        unique_together = [("tenant", "user", "permission")]

    def __str__(self):
        return f"{self.user.email}: {self.effect.upper()} {self.permission.code}"

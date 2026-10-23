"""
Users app serializers — Auth, Member Management, and RBAC.
"""
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import (
    MemberProfile,
    Membership,
    Permission,
    Role,
    UserAccount,
    UserPermissionOverride,
)


# ─── Auth Serializers ──────────────────────────────────────────────────


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token serializer that includes tenant_id in the token claims.
    The client must pass tenant_code to specify which cooperative they're logging into.
    """

    tenant_code = serializers.CharField(required=False, allow_blank=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token["email"] = user.email
        token["full_name"] = user.full_name
        token["is_platform_user"] = user.is_platform_user
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        tenant_code = (self.initial_data.get("tenant_code") or "").strip()

        if not self.user.is_platform_user:
            tenant, membership = self._resolve_society(tenant_code)

            # Inject tenant_id into the tokens
            from rest_framework_simplejwt.tokens import RefreshToken

            refresh = RefreshToken.for_user(self.user)
            refresh["tenant_id"] = str(tenant.id)
            refresh["tenant_code"] = tenant.code
            refresh["role"] = membership.role.code
            refresh["email"] = self.user.email
            refresh["full_name"] = self.user.full_name
            refresh["is_platform_user"] = self.user.is_platform_user

            data["refresh"] = str(refresh)
            data["access"] = str(refresh.access_token)
            data["tenant"] = {
                "id": str(tenant.id),
                "code": tenant.code,
                "name": tenant.name,
            }
            data["role"] = membership.role.code

        # Add user info to response
        data["user"] = {
            "id": str(self.user.id),
            "email": self.user.email,
            "full_name": self.user.full_name,
            "is_platform_user": self.user.is_platform_user,
        }

        return data

    def _resolve_society(self, tenant_code):
        """
        Work out which cooperative society this login belongs to, and the
        membership that gives the user their role.

        A society code is optional when the user belongs to exactly one
        society — asking them to type a code they can look up would be
        needless friction. With no code and no membership (or more than one)
        there is no unambiguous answer, so the login is refused with a
        message that says what to do.
        """
        from apps.core.models import Tenant

        if tenant_code:
            try:
                tenant = Tenant.objects.get(
                    code=tenant_code, status=Tenant.Status.ACTIVE
                )
            except Tenant.DoesNotExist:
                raise serializers.ValidationError(
                    {"tenant_code": "Invalid or inactive cooperative society."}
                )

            membership = (
                Membership.objects.filter(
                    tenant=tenant, user=self.user, status=Membership.Status.ACTIVE
                )
                .select_related("role")
                .first()
            )

            if not membership:
                raise serializers.ValidationError(
                    {
                        "tenant_code": "You are not an active member of this cooperative society."
                    }
                )

            return tenant, membership

        memberships = list(
            Membership.objects.filter(
                user=self.user, status=Membership.Status.ACTIVE
            ).select_related("tenant", "role")
        )

        if not memberships:
            raise serializers.ValidationError(
                {
                    "tenant_code": "You are not a member of any cooperative society. Enter your society code to continue."
                }
            )

        if len(memberships) > 1:
            raise serializers.ValidationError(
                {
                    "tenant_code": "You belong to more than one cooperative society. Enter your society code to choose the one to sign in to."
                }
            )

        membership = memberships[0]
        return membership.tenant, membership


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for new user registration."""

    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    tenant_code = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = UserAccount
        fields = [
            "email",
            "first_name",
            "last_name",
            "phone",
            "password",
            "password_confirm",
            "tenant_code",
        ]

    def validate(self, data):
        if data["password"] != data["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return data

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        tenant_code = validated_data.pop("tenant_code", None)
        password = validated_data.pop("password")

        user = UserAccount.objects.create_user(password=password, **validated_data)

        # If tenant_code provided, create a pending membership
        if tenant_code:
            from apps.core.models import Tenant

            try:
                tenant = Tenant.objects.get(code=tenant_code, status=Tenant.Status.ACTIVE)
                member_role = Role.objects.filter(code="MEMBER", tenant__isnull=True).first()
                if member_role:
                    Membership.objects.create(
                        tenant=tenant,
                        user=user,
                        role=member_role,
                        status=Membership.Status.PENDING,
                    )
            except Tenant.DoesNotExist:
                pass  # Silently ignore invalid tenant code during registration

        return user


class PasswordChangeSerializer(serializers.Serializer):
    """Serializer for password change."""

    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)
    new_password_confirm = serializers.CharField(required=True)

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, data):
        if data["new_password"] != data["new_password_confirm"]:
            raise serializers.ValidationError({"new_password_confirm": "New passwords do not match."})
        return data


# ─── User & Member Serializers ─────────────────────────────────────────


class UserAccountSerializer(serializers.ModelSerializer):
    """Read-only user representation."""

    full_name = serializers.ReadOnlyField()

    class Meta:
        model = UserAccount
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "status",
            "is_platform_user",
            "date_joined",
            "last_login",
        ]
        read_only_fields = ["id", "date_joined", "last_login"]


class MemberProfileSerializer(serializers.ModelSerializer):
    """Member profile with tenant-specific institutional data."""

    class Meta:
        model = MemberProfile
        fields = [
            "id",
            "employee_no",
            "payroll_no",
            "department",
            "faculty",
            "designation",
            "employment_status",
            "date_of_birth",
            "next_of_kin_name",
            "next_of_kin_phone",
            "bank_name",
            "bank_account_no",
            "joined_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MemberDetailSerializer(serializers.ModelSerializer):
    """Combined user + member profile for detailed member views."""

    user = UserAccountSerializer(read_only=True)
    profile = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    membership_status = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id",
            "user",
            "profile",
            "role",
            "membership_status",
            "approved_by",
            "approved_at",
            "created_at",
        ]

    def get_profile(self, obj):
        profile = MemberProfile.objects.filter(tenant=obj.tenant, user=obj.user).first()
        if profile:
            return MemberProfileSerializer(profile).data
        return None

    def get_role(self, obj):
        return {"code": obj.role.code, "name": obj.role.name}

    def get_membership_status(self, obj):
        return obj.status


class MemberDirectorySerializer(serializers.ModelSerializer):
    """
    The society's member directory, without the institutional profile.

    A plain member may see who is in their society — that is what the
    guarantor picker needs — but the member profile carries employee and
    payroll numbers, a date of birth, next-of-kin details and bank
    coordinates, and none of that is any other member's business. So the
    directory carries names, email and role only.
    """

    user = UserAccountSerializer(read_only=True)
    role = serializers.SerializerMethodField()
    membership_status = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = [
            "id",
            "user",
            "role",
            "membership_status",
            "created_at",
        ]

    def get_role(self, obj):
        return {"code": obj.role.code, "name": obj.role.name}

    def get_membership_status(self, obj):
        return obj.status


class GuarantorCandidateSerializer(serializers.ModelSerializer):
    """
    A member who can be named as a guarantor.

    Deliberately narrow: the picker needs a display name, an email to
    disambiguate two people, and the profile id the API expects. It does not
    need, and must not receive, the member's employee number, payroll
    number or any other institutional detail.
    """

    full_name = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    profile_id = serializers.SerializerMethodField()

    class Meta:
        model = Membership
        fields = ["id", "full_name", "email", "profile_id"]

    def get_full_name(self, obj):
        return obj.user.full_name

    def get_email(self, obj):
        return obj.user.email

    def get_profile_id(self, obj):
        profile = MemberProfile.objects.filter(tenant=obj.tenant, user=obj.user).first()
        return str(profile.id) if profile else None


class MemberCreateSerializer(serializers.Serializer):
    """Serializer for creating a new member (admin-initiated)."""

    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=20, required=False, default="")
    role_code = serializers.CharField(max_length=50, default="MEMBER")
    employee_no = serializers.CharField(max_length=50, required=False, default="")
    payroll_no = serializers.CharField(max_length=50, required=False, default="")
    department = serializers.CharField(max_length=200, required=False, default="")
    faculty = serializers.CharField(max_length=200, required=False, default="")
    designation = serializers.CharField(max_length=200, required=False, default="")

    def validate_email(self, value):
        # Check if user already has membership in this tenant
        tenant = self.context["request"].tenant
        existing = Membership.objects.filter(
            tenant=tenant, user__email=value
        ).exists()
        if existing:
            raise serializers.ValidationError("A member with this email already exists in this cooperative.")
        return value

    def validate_role_code(self, value):
        # Tenant-scoped roles only: a society admin must never be able to hand
        # out a platform role (SUPER_ADMIN) by posting role_code directly.
        if not Role.objects.filter(code=value, scope=Role.Scope.TENANT).exists():
            raise serializers.ValidationError(f"Tenant role '{value}' does not exist.")
        return value

    def to_representation(self, instance):
        # `create()` returns a Membership, not the input payload, so DRF's
        # default representation (which reads email/first_name off it) would
        # raise AttributeError. Render the created membership instead.
        return MemberDetailSerializer(instance, context=self.context).data

    def create(self, validated_data):
        tenant = self.context["request"].tenant
        email = validated_data["email"]
        role_code = validated_data.pop("role_code")
        profile_fields = {
            k: validated_data.pop(k) for k in ["employee_no", "payroll_no", "department", "faculty", "designation"]
        }

        # Create or get user
        user, created = UserAccount.objects.get_or_create(
            email=email,
            defaults={
                "first_name": validated_data["first_name"],
                "last_name": validated_data["last_name"],
                "phone": validated_data.get("phone", ""),
            },
        )

        if created:
            # Set a temporary password for new users
            import secrets
            temp_password = secrets.token_urlsafe(12)
            user.set_password(temp_password)
            user.save()
            # TODO: Send welcome email with temp password

        # Create membership
        role = Role.objects.filter(code=role_code).first()
        membership = Membership.objects.create(
            tenant=tenant,
            user=user,
            role=role,
            status=Membership.Status.ACTIVE,
            approved_by=self.context["request"].user,
            approved_at=timezone.now(),
        )

        # Create member profile
        MemberProfile.objects.create(
            tenant=tenant,
            user=user,
            joined_at=timezone.now().date(),
            **profile_fields,
        )

        return membership


# ─── RBAC Serializers ──────────────────────────────────────────────────


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "code", "module", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Role
        fields = ["id", "code", "name", "scope", "description", "permissions"]


class MembershipStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for approving/suspending/removing members.

    `reason` is optional, but the UI asks for one whenever the change is
    not an approval, and it is recorded in the audit trail.
    """

    status = serializers.ChoiceField(choices=Membership.Status.choices)
    reason = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )

    def update(self, instance, validated_data):
        instance.status = validated_data["status"]
        if validated_data["status"] == Membership.Status.ACTIVE:
            instance.approved_by = self.context["request"].user
            instance.approved_at = timezone.now()
        instance.save()
        return instance


class MemberRoleUpdateSerializer(serializers.Serializer):
    """Serializer for changing a member's role."""

    role_code = serializers.CharField(max_length=50)

    def validate_role_code(self, value):
        if not Role.objects.filter(code=value, scope=Role.Scope.TENANT).exists():
            raise serializers.ValidationError(f"Tenant role '{value}' does not exist.")
        return value


class UserPermissionOverrideSerializer(serializers.ModelSerializer):
    permission_code = serializers.CharField(source="permission.code", read_only=True)

    class Meta:
        model = UserPermissionOverride
        fields = [
            "id",
            "user",
            "permission",
            "permission_code",
            "effect",
            "reason",
            "granted_by",
            "created_at",
        ]
        read_only_fields = ["id", "granted_by", "created_at"]

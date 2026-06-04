"""
Users app views — Authentication, Member Management, and RBAC.
"""
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from common.mixins import TenantScopedViewSetMixin
from common.permissions import IsExecutiveOrAbove, IsSocietyAdmin, IsTenantMember

from .models import (
    MemberProfile,
    Membership,
    Permission,
    Role,
    UserAccount,
    UserPermissionOverride,
)
from .serializers import (
    CustomTokenObtainPairSerializer,
    MemberCreateSerializer,
    MemberDetailSerializer,
    MemberProfileSerializer,
    MemberRoleUpdateSerializer,
    MembershipStatusUpdateSerializer,
    PasswordChangeSerializer,
    PermissionSerializer,
    RoleSerializer,
    UserAccountSerializer,
    UserPermissionOverrideSerializer,
    UserRegistrationSerializer,
)


# ─── Auth Views ────────────────────────────────────────────────────────


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/

    Authenticate with email + password. Optionally pass `tenant_code`
    to get tenant-scoped JWT tokens.
    """

    serializer_class = CustomTokenObtainPairSerializer


class RegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/

    Register a new user. Optionally pass `tenant_code` to create
    a pending membership in that cooperative society.
    """

    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {
                "detail": "Registration successful. Your membership is pending approval.",
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "full_name": user.full_name,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class LogoutView(generics.GenericAPIView):
    """
    POST /api/v1/auth/logout/

    Blacklist the refresh token to log out.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response({"detail": "Successfully logged out."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"detail": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)


class PasswordChangeView(generics.GenericAPIView):
    """
    POST /api/v1/auth/password/change/

    Change the authenticated user's password.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PasswordChangeSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()
        return Response({"detail": "Password updated successfully."})


class CurrentUserView(generics.RetrieveAPIView):
    """
    GET /api/v1/auth/me/

    Returns the current authenticated user's profile and tenant memberships.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = UserAccountSerializer

    def get_object(self):
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        user_data = self.get_serializer(request.user).data
        # Include list of tenant memberships
        memberships = Membership.objects.filter(
            user=request.user, status=Membership.Status.ACTIVE
        ).select_related("tenant", "role")

        user_data["memberships"] = [
            {
                "tenant_id": str(m.tenant.id),
                "tenant_code": m.tenant.code,
                "tenant_name": m.tenant.name,
                "role": m.role.code,
                "role_name": m.role.name,
            }
            for m in memberships
        ]
        return Response(user_data)


# ─── Member Management Views ──────────────────────────────────────────


class MemberViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    """
    Member management within a tenant.

    GET /api/v1/members/          — List members (EXECUTIVE+)
    POST /api/v1/members/         — Create member (SOCIETY_ADMIN)
    GET /api/v1/members/{id}/     — Member detail
    PATCH /api/v1/members/{id}/   — Update member
    """

    queryset = Membership.objects.select_related("user", "role")
    serializer_class = MemberDetailSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [IsTenantMember()]
        if self.action == "create":
            return [IsSocietyAdmin()]
        return [IsExecutiveOrAbove()]

    def get_serializer_class(self):
        if self.action == "create":
            return MemberCreateSerializer
        return MemberDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        # Regular members can only see active members
        if not self.request.user.is_platform_user:
            membership = Membership.objects.filter(
                tenant=self.request.tenant,
                user=self.request.user,
                status=Membership.Status.ACTIVE,
            ).first()
            if membership and membership.role.code == "MEMBER":
                qs = qs.filter(status=Membership.Status.ACTIVE)
        return qs

    @action(detail=True, methods=["patch"], url_path="status")
    def update_status(self, request, pk=None):
        """
        PATCH /api/v1/members/{id}/status/
        Approve, suspend, or remove a member. SOCIETY_ADMIN only.
        """
        membership = self.get_object()
        serializer = MembershipStatusUpdateSerializer(
            membership, data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.update(membership, serializer.validated_data)
        return Response(MemberDetailSerializer(membership).data)

    @action(detail=True, methods=["put"], url_path="role")
    def change_role(self, request, pk=None):
        """
        PUT /api/v1/members/{id}/role/
        Change a member's role. SOCIETY_ADMIN only.
        """
        membership = self.get_object()
        serializer = MemberRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        new_role = Role.objects.get(code=serializer.validated_data["role_code"])
        membership.role = new_role
        membership.save(update_fields=["role", "updated_at"])
        return Response(MemberDetailSerializer(membership).data)

    @action(detail=True, methods=["get", "put", "patch"], url_path="profile")
    def profile(self, request, pk=None):
        """
        GET/PUT/PATCH /api/v1/members/{id}/profile/
        Manage a member's tenant-specific profile.
        """
        membership = self.get_object()
        profile, _ = MemberProfile.objects.get_or_create(
            tenant=request.tenant, user=membership.user
        )

        if request.method == "GET":
            return Response(MemberProfileSerializer(profile).data)

        serializer = MemberProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="pending")
    def pending_members(self, request):
        """
        GET /api/v1/members/pending/
        List members with pending approval status. SOCIETY_ADMIN+.
        """
        pending = self.get_queryset().filter(status=Membership.Status.PENDING)
        serializer = MemberDetailSerializer(pending, many=True)
        return Response(serializer.data)


# ─── RBAC Views ────────────────────────────────────────────────────────


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/members/roles/        — List available roles
    GET /api/v1/members/roles/{id}/   — Role detail with permissions
    """

    queryset = Role.objects.prefetch_related("permissions")
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated]


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/members/permissions/ — List all permissions
    """

    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated]

"""
Tenant-aware JWT authentication.

`CustomTokenObtainPairSerializer` writes a `tenant_id` claim into the token at
login, and `TenantMiddleware` resolves the request tenant from
`request.user.current_tenant_id`. Stock `JWTAuthentication` never sets that
attribute, so without this class the claim is inert and tenant resolution
silently falls through to the `X-Tenant-ID` header.

This class bridges the two, making the signed claim the primary source of
tenant context — which is what the design calls for, since a header is
client-supplied and a claim is not.
"""
import logging

from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger(__name__)


class TenantAwareJWTAuthentication(JWTAuthentication):
    """Populates `user.current_tenant_id` from the token's `tenant_id` claim."""

    def get_user(self, validated_token):
        user = super().get_user(validated_token)

        tenant_id = validated_token.get("tenant_id")
        if tenant_id:
            # Instance attribute shadows the class-level default on UserAccount.
            user.current_tenant_id = str(tenant_id)
            user.current_tenant_code = validated_token.get("tenant_code")
            user.current_role_code = validated_token.get("role")

        return user

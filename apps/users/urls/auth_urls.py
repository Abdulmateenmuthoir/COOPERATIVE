"""Auth URL patterns."""
from django.urls import path

from apps.users.views import (
    CurrentUserView,
    InvitationAcceptView,
    LoginView,
    LogoutView,
    PasswordChangeView,
    TokenRefreshView,
)

urlpatterns = [
    path(
        "accept-invitation/<str:uidb64>/<str:token>/",
        InvitationAcceptView.as_view(),
        name="auth-accept-invitation",
    ),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]

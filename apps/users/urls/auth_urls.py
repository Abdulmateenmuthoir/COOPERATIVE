"""Auth URL patterns."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import (
    CurrentUserView,
    LoginView,
    LogoutView,
    PasswordChangeView,
    RegisterView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("me/", CurrentUserView.as_view(), name="auth-me"),
]

"""
Root URL Configuration for the Cooperative Management SaaS Platform.

All API endpoints are versioned under /api/v1/
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from common.health import liveness, readiness

# ─── API v1 URL patterns ──────────────────────────────────────────────
api_v1_patterns = [
    path("auth/", include("apps.users.urls.auth_urls")),
    path("members/", include("apps.users.urls.member_urls")),
    path("contributions/", include("apps.contributions.urls")),
    path("loans/", include("apps.loans.urls")),
    path("schedules/", include("apps.schedules.urls")),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("platform/", include("apps.core.urls")),
]

urlpatterns = [
    # The repository is an API backend; send the site root to its API browser.
    path("", RedirectView.as_view(pattern_name="swagger-ui", permanent=False), name="home"),

    # Health checks (unauthenticated, no DRF throttling)
    path("health/", liveness, name="health-liveness"),
    path("health/ready/", readiness, name="health-readiness"),

    # Django admin
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include((api_v1_patterns, "api-v1"))),

    # OpenAPI schema and documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # Debug toolbar
    try:
        import debug_toolbar
        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

# Customize Django admin
admin.site.site_header = "Cooperative Management Platform"
admin.site.site_title = "Cooperative Admin"
admin.site.index_title = "Platform Administration"

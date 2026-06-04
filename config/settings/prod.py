"""
Production settings — extends base.
"""
from .base import *  # noqa: F401, F403

DEBUG = False

# Security
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Sentry integration
import sentry_sdk  # noqa: E402

sentry_sdk.init(
    dsn=config("SENTRY_DSN", default=""),  # noqa: F405
    traces_sample_rate=0.1,
    profiles_sample_rate=0.1,
)

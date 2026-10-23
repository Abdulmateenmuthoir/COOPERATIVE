"""Production settings for the Cooperative Management SaaS Platform.
Override base settings for production deployment (e.g., on Render).
"""

from .base import *

# ⚠️ Security: these MUST be set via environment variables in production
# Render dashboard → Add Environment Variable
DEBUG = config("DEBUG", default=False, cast=bool)

# ⚠️ Must match your deployed domain(s)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="", cast=Csv())

# 🔐 Trust the reverse proxy (Render, nginx, etc.) for headers
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# 📜 HTTP Strict Transport Security
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=True, cast=bool)

# 🍪 Cookie security (only over HTTPS)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)

# 🛡️ X-Content-Type-Options & X-Frame-Options
SECURE_BROWSER_XSS_FILTER = config("SECURE_BROWSER_XSS_FILTER", default=True, cast=bool)
SECURE_CONTENT_TYPE_NOSNIFF = config("SECURE_CONTENT_TYPE_NOSNIFF", default=True, cast=bool)

# 📦 WhiteNoise already configured in base.py via STATICFILES_STORAGE
# Ensure collectstatic has been run: python manage.py collectstatic

# 📧 Email (production should use a real SMTP service)
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)

# 🔧 Any production-specific overrides go here
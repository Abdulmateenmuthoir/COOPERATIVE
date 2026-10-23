"""
Production settings for the Cooperative Management SaaS Platform.

Loaded when DJANGO_ENV=prod (or automatically on Render, where RENDER=true).
See config/runtime.py for how the settings module is chosen.

Everything below is driven by environment variables so that a single image can
be deployed to any environment without code changes.
"""
import os
import urllib.parse

from decouple import Csv, config

from .base import *  # noqa: F401, F403

# ─── Core security ─────────────────────────────────────────────────────
# DEBUG is opt-in: anything other than an explicit "true" keeps it off.
DEBUG = config("DEBUG", default=False, cast=bool)
if DEBUG and os.getenv("RENDER"):
    # A stray .env or a copied dashboard variable must never turn on debug
    # pages (which leak settings and tracebacks) on a public deployment.
    raise RuntimeError("DEBUG must not be enabled on a Render deployment.")

SECRET_KEY = config("SECRET_KEY")  # no default on purpose: fail fast if unset

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
    cast=Csv(),
)

# Render exposes the public hostname of the service in RENDER_EXTERNAL_HOSTNAME.
# Add it automatically so a fresh deploy works before anything is configured.
_render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host and _render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _render_host]

# Django admin login and any session-authenticated POST needs the origin listed.
_derived_trusted_origins = [
    f"https://{host}"
    for host in ALLOWED_HOSTS
    if host not in {"localhost", "127.0.0.1", "[::1]"} and "*" not in host
]
CSRF_TRUSTED_ORIGINS = sorted(
    {
        *config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv()),
        *_derived_trusted_origins,
    }
)

# ─── Reverse proxy / TLS ───────────────────────────────────────────────
# Render terminates TLS at its edge and forwards X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
# Platform health checks hit the container over plain HTTP; keep them exempt.
SECURE_REDIRECT_EXEMPT = [r"^/?health/?$", r"^/?health/ready/?$"]

SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"

# HSTS: enable only once every client is known to use HTTPS (Render is HTTPS-only,
# so this is on by default). Keep it low first if you serve other hostnames.
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool
)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

# ─── Database ──────────────────────────────────────────────────────────
# Prefer a single DATABASE_URL (what Render/managed Postgres hands you).
# Fall back to the DB_* variables from base.py when it is not set.
_database_url = config("DATABASE_URL", default="").strip()
if _database_url:
    _parsed = urllib.parse.urlparse(_database_url)
    if _parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(
            f"DATABASE_URL must be a postgres:// URL, got scheme {_parsed.scheme!r}."
        )
    _options = {"connect_timeout": config("DB_CONNECT_TIMEOUT", default=10, cast=int)}
    _query = dict(urllib.parse.parse_qsl(_parsed.query))
    if "sslmode" in _query:
        _options["sslmode"] = _query["sslmode"]
    DATABASES = {  # noqa: F405
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": urllib.parse.unquote(_parsed.path.lstrip("/")),
            "USER": urllib.parse.unquote(_parsed.username or ""),
            "PASSWORD": urllib.parse.unquote(_parsed.password or ""),
            "HOST": _parsed.hostname or "",
            "PORT": str(_parsed.port or 5432),
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
            "OPTIONS": _options,
        }
    }

# ─── Static files ──────────────────────────────────────────────────────
# Hashed, pre-compressed files served by WhiteNoise straight from the container.
# Requires `python manage.py collectstatic` during the build step.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
# Never 500 a page because a template referenced an asset missing from the manifest.
WHITENOISE_MANIFEST_STRICT = False

# ─── Email ─────────────────────────────────────────────────────────────
# Console backend by default: nothing in the product sends mail yet, and a
# misconfigured SMTP host must never make an API request hang.
EMAIL_BACKEND = config(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)

# ─── Logging ───────────────────────────────────────────────────────────
# Render captures stdout; keep it structured and never write to a file.
LOGGING = {  # noqa: F405
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": config("LOG_LEVEL", default="INFO")},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {
            "handlers": ["console"],
            "level": config("APP_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}

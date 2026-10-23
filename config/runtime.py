"""
Single place where the Django settings module is decided.

Precedence:
    1. DJANGO_SETTINGS_MODULE  (set explicitly by a developer or a runner)
    2. DJANGO_ENV              ("dev", "prod", ...) -> config.settings.<env>
    3. RENDER                  (set automatically by Render) -> prod
    4. fallback                -> dev

Doing this in one function keeps manage.py, wsgi.py, asgi.py and celery.py in
sync and removes the "deployed with DEBUG=True because someone forgot an env
var" class of mistake.
"""
import os

VALID_ENVIRONMENTS = ("dev", "prod")


def settings_module() -> str:
    """Return the dotted path of the settings module to use."""
    explicit = os.getenv("DJANGO_SETTINGS_MODULE")
    if explicit:
        return explicit

    environment = os.getenv("DJANGO_ENV", "").strip().lower()
    if not environment:
        # Render injects RENDER=true into every service it runs.
        environment = "prod" if os.getenv("RENDER") else "dev"

    if environment not in VALID_ENVIRONMENTS:
        raise RuntimeError(
            f"Unknown DJANGO_ENV={environment!r}. Expected one of {VALID_ENVIRONMENTS}."
        )

    return f"config.settings.{environment}"

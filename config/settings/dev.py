"""Development settings - extends base."""
from .base import *  # noqa: F401, F403

DEBUG = True

# Add browsable API renderer in dev
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
"rest_framework.renderers.JSONRenderer",
"rest_framework.renderers.BrowsableAPIRenderer",
]
# Add throttling for development too (but at a higher rate to avoid impacting local testing)
REST_FRAMEWORK["DEFAULT_THROTTLE_CLASSES"] = [  # noqa: F405
"rest_framework.throttling.UserRateThrottle",
]
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {  # noqa: F405
"user": "1000/day",  # generous for local dev
}

# Disable the schema generation in dev to avoid leaking internal endpoints
SPECTACULAR_SETTINGS = {
    "TITLE": "Cooperative Management SaaS Platform",
    "VERSION": "1.0.0",
    "SERVERS": [{"url": "http://localhost:8000"}],
}
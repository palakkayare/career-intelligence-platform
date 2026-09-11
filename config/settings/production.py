"""
Production settings - strict security.
"""

from apps.core.log_format import build_logging
from apps.core.observability import init_sentry

from .base import *  # noqa: F401,F403

DEBUG = False

# Security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
# Nginx terminates TLS and forwards plain HTTP, so Django cannot tell a
# secure request from an insecure one on its own. This header, set by the
# proxy, is how it knows - without it SECURE_SSL_REDIRECT would bounce every
# request in an endless loop.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# The container healthcheck talks to Gunicorn directly over HTTP, so the
# redirect has to skip it or the container is never reported healthy.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Content Security Policy. This is an API served to a separate frontend, so
# nothing needs to load scripts or styles from these responses - the strictest
# possible policy is also the correct one. Django serves this header itself
# from 4.2 onwards via SECURE_CROSS_ORIGIN_OPENER_POLICY and middleware; the
# CSP below is applied by the security middleware through the header setting.
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# ─── Error tracking ───
init_sentry(
    dsn=SENTRY_DSN,  # noqa: F405
    environment=SENTRY_ENVIRONMENT,  # noqa: F405
    release=SENTRY_RELEASE or None,  # noqa: F405
    traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,  # noqa: F405
)


# ─── Logging ───
LOGGING = build_logging(json_output=env.bool("LOG_JSON", default=True))  # noqa: F405


# ─── Password breach check ───
PASSWORD_BREACH_CHECK = env.bool("PASSWORD_BREACH_CHECK", default=True)  # noqa: F405


# ─── Client IP ───
# Hosting platforms put one proxy in front of the app. With Cloudflare in
# front of that as well, set TRUSTED_PROXY_COUNT=2 in the environment.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)  # noqa: F405
REST_FRAMEWORK["NUM_PROXIES"] = TRUSTED_PROXY_COUNT  # noqa: F405

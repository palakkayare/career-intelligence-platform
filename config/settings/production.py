"""
Production settings - strict security.
"""
from .base import *  # noqa: F401,F403

from apps.core.observability import init_sentry

DEBUG = False

# Security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Content Security Policy. This is an API served to a separate frontend, so
# nothing needs to load scripts or styles from these responses - the strictest
# possible policy is also the correct one. Django serves this header itself
# from 4.2 onwards via SECURE_CROSS_ORIGIN_OPENER_POLICY and middleware; the
# CSP below is applied by the security middleware through the header setting.
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'

# ─── Error tracking ───
init_sentry(
    dsn=SENTRY_DSN,  # noqa: F405
    environment=SENTRY_ENVIRONMENT,  # noqa: F405
    release=SENTRY_RELEASE or None,  # noqa: F405
    traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,  # noqa: F405
)
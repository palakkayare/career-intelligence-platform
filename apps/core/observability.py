"""
Sentry configuration.

Kept out of settings so the scrubbing rules below are reviewable on their own.
This platform holds resumes, salary submissions and payment records, so what
gets sent to a third-party error tracker matters as much as the fact that
errors are tracked at all.
"""

import logging

logger = logging.getLogger(__name__)

# Never leave the platform in an error report. Sentry scrubs some of these by
# default; listing them explicitly means the guarantee does not depend on
# their defaults staying the same.
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "access_token",
    "refresh_token",
    "jwt",
    "signature",
    "razorpay_signature",
    "razorpay_key_secret",
    "fcm_token",
    "google_sub",
    "code_hash",
    "backup_code",
    "otp",
    "salary_inr",
    "annual_salary",
    "bonus_inr",
}

# Errors that say nothing about a defect. Filtering them keeps the signal
# usable rather than drowning real bugs in expected 4xx noise.
IGNORED_EXCEPTIONS = [
    "rest_framework.exceptions.ValidationError",
    "rest_framework.exceptions.NotAuthenticated",
    "rest_framework.exceptions.AuthenticationFailed",
    "rest_framework.exceptions.PermissionDenied",
    "rest_framework.exceptions.NotFound",
    "rest_framework.exceptions.Throttled",
    "django.http.Http404",
    "django.core.exceptions.PermissionDenied",
]


def _scrub(value, depth=0):
    """Recursively blank out anything whose key looks sensitive."""
    if depth > 6:  # guard against deeply nested or cyclic payloads
        return value

    if isinstance(value, dict):
        return {
            key: (
                "[Filtered]"
                if any(marker in str(key).lower() for marker in SENSITIVE_KEYS)
                else _scrub(inner, depth + 1)
            )
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value]
    return value


def before_send(event, hint):
    """Last gate before an event leaves the process."""
    for section in ("request", "extra", "contexts"):
        if section in event:
            event[section] = _scrub(event[section])

    # Cookies carry the session and JWT; there is no version of them that is
    # safe to ship, so the whole jar goes.
    if "request" in event:
        event["request"].pop("cookies", None)
        headers = event["request"].get("headers")
        if isinstance(headers, dict):
            event["request"]["headers"] = _scrub(headers)

    return event


def init_sentry(dsn, environment, release=None, traces_sample_rate=0.0):
    """
    Wire up Sentry. A blank DSN disables it silently, which is what makes the
    same settings file usable in environments that have no Sentry project.
    """
    if not dsn:
        logger.info("Sentry DSN not configured - error tracking disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("sentry-sdk not installed - error tracking disabled")
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(
                level=logging.INFO,  # breadcrumbs
                event_level=logging.ERROR,  # what becomes an issue
            ),
        ],
        # Off by default. This platform holds resumes, salary data and payment
        # records; usernames and IP addresses attached to every event is more
        # personal data than an error tracker needs.
        send_default_pii=False,
        before_send=before_send,
        traces_sample_rate=traces_sample_rate,
        # 4xx are client mistakes, not defects worth paging anyone about.
        ignore_errors=IGNORED_EXCEPTIONS,
        max_breadcrumbs=50,
    )
    logger.info("Sentry initialised for environment=%s", environment)
    return True

"""
Production settings - strict security.
"""

from django.core.exceptions import ImproperlyConfigured

from apps.core.deploy_checks import production_config_errors
from apps.core.log_format import build_logging
from apps.core.observability import init_sentry

from .base import *  # noqa: F401,F403

DEBUG = False

# ─── Hosts ───
# Railway's deploy healthcheck sends "Host: healthcheck.railway.app". If that
# host is not allowed Django answers 400, the healthcheck never passes and
# every deploy is rolled back.
ALLOWED_HOSTS_FROM_ENV = list(ALLOWED_HOSTS)  # noqa: F405
ALLOWED_HOSTS = ALLOWED_HOSTS_FROM_ENV + ["healthcheck.railway.app"]
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# ─── Static files ───
# No nginx in front of the app on a hosting platform, so Gunicorn serves the
# admin and browsable-API assets itself. Directly after SecurityMiddleware, so
# the HTTPS redirect still applies to them.
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# ─── Email ───
# Without this Django falls back to SMTP on localhost:25, which does not exist
# in a container: verification, password reset, invoices and digests would
# all fail.
INSTALLED_APPS += ["anymail"]  # noqa: F405
EMAIL_BACKEND = "anymail.backends.sendgrid.EmailBackend"
SENDGRID_API_KEY = env("SENDGRID_API_KEY", default="")  # noqa: F405
ANYMAIL = {"SENDGRID_API_KEY": SENDGRID_API_KEY}

# ─── Database ───
# Reuse connections for a minute instead of opening one per request; a managed
# Postgres over TLS makes each new connection noticeably slow. Health checks
# drop a connection the provider closed while it sat idle (Neon suspends).
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405
# Required behind a transaction-mode pooler (Neon's -pooler host, PgBouncer),
# and harmless without one.
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True  # noqa: F405

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

# ─── API docs ───
# A full endpoint list is a map for anyone probing the API, so in production
# the schema and the UI need a staff login (sign in at /admin/ first).
SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ["rest_framework.permissions.IsAdminUser"]  # noqa

# ─── Error tracking ───
# Railway builds from the repo, so the image's GIT_SHA build arg is empty
# there. Railway sets the commit in the environment instead.
SENTRY_RELEASE = SENTRY_RELEASE or env("RAILWAY_GIT_COMMIT_SHA", default="")  # noqa: F405
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
# How many X-Forwarded-For entries our own infrastructure adds. Measured, not
# guessed: Railway sends 2. Cloudflare in front of Railway is not simply "one
# more" - see DEPLOY.md, section 6. Required in production (deploy_checks):
# the old silent default of 1 made every user share Railway's address.
TRUSTED_PROXY_COUNT_SET = env("TRUSTED_PROXY_COUNT", default="") != ""  # noqa: F405
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)  # noqa: F405
REST_FRAMEWORK["NUM_PROXIES"] = TRUSTED_PROXY_COUNT  # noqa: F405


# ─── Refuse to start half-configured ───
# Last, so it sees the final values. Every problem is listed at once: a deploy
# that fails on one missing variable at a time takes six deploys to fix.
_config_errors = production_config_errors(
    {
        "ALLOWED_HOSTS_FROM_ENV": ALLOWED_HOSTS_FROM_ENV,
        "DATABASE_URL": env("DATABASE_URL", default=""),  # noqa: F405
        "CELERY_BROKER_URL": CELERY_BROKER_URL,  # noqa: F405
        "CELERY_RESULT_BACKEND": CELERY_RESULT_BACKEND,  # noqa: F405
        "REDIS_CACHE_URL": CACHES["default"]["LOCATION"],  # noqa: F405
        "FIELD_ENCRYPTION_KEY": FIELD_ENCRYPTION_KEY,  # noqa: F405
        "SALARY_IP_PEPPER": SALARY_IP_PEPPER,  # noqa: F405
        "TRUSTED_PROXY_COUNT_SET": TRUSTED_PROXY_COUNT_SET,
        "SENDGRID_API_KEY": SENDGRID_API_KEY,
        "RAZORPAY_KEY_ID": RAZORPAY_KEY_ID,  # noqa: F405
        "RAZORPAY_KEY_SECRET": RAZORPAY_KEY_SECRET,  # noqa: F405
        "RAZORPAY_WEBHOOK_SECRET": RAZORPAY_WEBHOOK_SECRET,  # noqa: F405
        "INVOICE_GSTIN": INVOICE_GSTIN,  # noqa: F405
    }
)
if _config_errors:
    raise ImproperlyConfigured(
        "Production settings are incomplete:\n  - " + "\n  - ".join(_config_errors)
    )

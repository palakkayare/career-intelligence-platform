"""
Base settings - common to all environments.
"""

import sys
from datetime import timedelta
from pathlib import Path

import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

# Security
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

# Application definition
DJANGO_APPS = [
    "django.contrib.admin",
    # Required for the full-text search field and index on Job. Without it
    # SearchVectorField happens to work, but Postgres-specific lookups
    # (trigram, unaccent) fail the moment they are added.
    "django.contrib.postgres",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "storages",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.skills",
    "apps.seekers",
    "apps.industries",
    "apps.recruiters",
    "apps.jobs",
    "apps.applications",
    "apps.payments",
    "apps.resumes",
    "apps.match_scores",
    "apps.notifications",
    "apps.career_intel",
    "apps.referrals",
    "apps.audit",
    "apps.interview_prep",
    "apps.gamification",
    "apps.reviews",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS
DEBUG_TOOLBAR_CONFIG = {"IS_RUNNING_TESTS": False}

MIDDLEWARE = [
    # First, so every response - even CORS and security rejections - gets an id.
    "apps.core.middleware.RequestIdMiddleware",
    "corsheaders.middleware.CorsMiddleware",  # CORS must be near the top
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.audit.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
DATABASES = {
    "default": env.db("DATABASE_URL"),
}

# Custom User model — decided on Day 1, before any migrations
AUTH_USER_MODEL = "accounts.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # India timezone
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = "static/"
# collectstatic needs somewhere to write. Only the admin and DRF's browsable
# API serve static files here - the product frontend is a separate app.
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# DRF configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # JWTAuthentication that also tells Sentry whose request it was.
        "apps.core.authentication.ObservedJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
    "DEFAULT_VERSION": "v1",
    "ALLOWED_VERSIONS": ["v1"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min",
        "register": "10/hour",
        "password_reset": "3/hour",
        "otp_request": "3/hour",
        "2fa": "10/min",
        "search": "60/min",
        "apply": "20/hour",
        "subscription": "10/hour",
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.custom_exception_handler",
    "PAGE_SIZE": 20,
}

# JWT configuration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env.int("JWT_ACCESS_TOKEN_LIFETIME_MINUTES", default=15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env.int("JWT_REFRESH_TOKEN_LIFETIME_DAYS", default=7)),
    "ROTATE_REFRESH_TOKENS": True,  # Issue a new refresh token on every refresh
    "BLACKLIST_AFTER_ROTATION": True,  # Old refresh token gets blacklisted
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY"),  # Deliberately different from SECRET_KEY
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# CORS
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
)

# ─── Frontend + email ───
# FRONTEND_URL is the base for every link the backend hands to a user:
# referral share links, password reset, email verification, unsubscribe.
# The default below only applies when FRONTEND_URL is absent from .env —
# an entry there always wins, so check .env first when a link points at the
# wrong port. Vite serves on 5173.
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@example.com")
SUPPORT_EMAIL = env("SUPPORT_EMAIL", default="support@example.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

GOOGLE_OAUTH_CLIENT_ID = env("GOOGLE_OAUTH_CLIENT_ID", default="")

TOTP_ISSUER_NAME = "Career Intelligence Platform"

# Media files (user uploads)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Image upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Job posting settings
JOB_AUTO_APPROVE = env.bool("JOB_AUTO_APPROVE", default=False)

# Free tier limits (Phase 2 mein subscription se override hogi)
FREE_TIER_APPLICATION_LIMIT = env.int("FREE_TIER_APPLICATION_LIMIT", default=5)

# Razorpay
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")

# Subscription settings
FREE_TRIAL_DAYS = env.int("FREE_TRIAL_DAYS", default=7)

if not RAZORPAY_KEY_ID and "test" not in " ".join(sys.argv):
    import warnings

    warnings.warn("RAZORPAY_KEY_ID not configured")

# Production mein test keys ka use prevent. Before launch the live site runs
# on test keys deliberately, so smoke tests can pay without real money;
# RAZORPAY_ALLOW_TEST_KEYS says that out loud and comes off at launch.
RAZORPAY_ALLOW_TEST_KEYS = env.bool("RAZORPAY_ALLOW_TEST_KEYS", default=False)
if "rzp_test_" in RAZORPAY_KEY_ID and not DEBUG and not RAZORPAY_ALLOW_TEST_KEYS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Test Razorpay keys in production! Before launch, set "
        "RAZORPAY_ALLOW_TEST_KEYS=True to deploy with test keys on purpose."
    )

# ─── Celery Configuration ───
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/2")

# Serialization
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

# Timezone
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_ENABLE_UTC = True

# Task settings
CELERY_TASK_TRACK_STARTED = True  # "started" status dikhega
CELERY_TASK_TIME_LIMIT = 300  # 5 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240  # 4 min soft warning
CELERY_TASK_ACKS_LATE = True  # Success ke baad acknowledge (crash pe retry)
CELERY_WORKER_PREFETCH_MULTIPLIER = 4  # Worker ek baar mein kitne tasks uthaye

# Retry settings
CELERY_TASK_AUTORETRY_FOR = (Exception,)  # Kisi bhi exception pe auto-retry
CELERY_TASK_MAX_RETRIES = 3
CELERY_TASK_DEFAULT_RETRY_DELAY = 60  # Retries ke beech 1 minute

# ─── AWS S3 Configuration ───
AWS_S3_USE_S3 = env.bool("AWS_S3_USE_S3", default=False)

if AWS_S3_USE_S3:
    AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="ap-south-1")
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "max-age=86400",
    }
    AWS_DEFAULT_ACL = None  # No public ACL (private bucket)
    AWS_S3_FILE_OVERWRITE = False  # Same-name files overwrite nahi honge
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_ADDRESSING_STYLE = "virtual"

    # S3 for media (user uploads), static stays local for now.
    # DEFAULT_FILE_STORAGE was removed in Django 5.1 in favour of STORAGES.
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
else:
    # Local storage (fallback for offline testing)
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

# ─── Cache Configuration (Redis) ───
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_CACHE_URL", default="redis://localhost:6379/3"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

# ─── Salary privacy ───
SALARY_K_ANONYMITY = env.int("SALARY_K_ANONYMITY", default=5)
SALARY_MIN_INR = 100_000  # ₹1L floor
SALARY_MAX_INR = 100_000_000  # ₹10Cr ceiling

# ─── Audit trail ───
AUDITED_MODELS = [
    "accounts.User",
    "jobs.Job",
    "applications.Application",
    "payments.Subscription",
    "payments.PaymentTransaction",
    "recruiters.Company",
    "skills.Skill",
]
# ─── Salary submission privacy ───
# IPs are stored as a keyed hash, never in the clear. A plain SHA-256 of an
# IPv4 address is not anonymisation - there are only about four billion of
# them, so a rainbow table takes minutes to build. The pepper is what makes
# the hash irreversible without it.
#
# Deliberately not SECRET_KEY: rotating one should not silently invalidate
# every stored hash, and a leaked SECRET_KEY should not also de-anonymise
# salary data.
SALARY_IP_PEPPER = env("SALARY_IP_PEPPER", default="")

# Per-device submission limit. One person filling in twenty salaries from
# one machine is either testing or skewing the data.
SALARY_MAX_SUBMISSIONS_PER_IP = env.int(
    "SALARY_MAX_SUBMISSIONS_PER_IP",
    default=3,
)
SALARY_IP_WINDOW_HOURS = env.int("SALARY_IP_WINDOW_HOURS", default=24)
# ─── Observability ───
# A blank DSN disables Sentry, so development and CI need no Sentry project.
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default="development")
# Set from the deploy (a git SHA or tag) so an error can be traced to code.
SENTRY_RELEASE = env("SENTRY_RELEASE", default="")
# Performance tracing is sampled, not full: 10% is enough to spot slow
# endpoints without multiplying the event bill.
SENTRY_TRACES_SAMPLE_RATE = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1)
# ─── Invoicing ───
# Kept in settings rather than hard-coded in invoice.py so the GSTIN and
# address can differ per environment and a placeholder can never reach
# production by accident.
INVOICE_COMPANY_NAME = env(
    "INVOICE_COMPANY_NAME",
    default="Career Intelligence Platform Pvt Ltd",
)
INVOICE_COMPANY_ADDRESS = env(
    "INVOICE_COMPANY_ADDRESS",
    default="Bangalore, India",
)
INVOICE_GSTIN = env("INVOICE_GSTIN", default="")
INVOICE_GST_RATE = env.float("INVOICE_GST_RATE", default=18.0)


# ─── Logging ───
# Readable text by default; production switches to JSON for a log aggregator.
# Every line carries the request id from RequestIdMiddleware.
from apps.core.log_format import build_logging  # noqa: E402

LOGGING = build_logging(json_output=env.bool("LOG_JSON", default=False))


# ─── Field encryption ───
# Fernet key for encrypted model fields (2FA secrets). Comma-separate several
# to rotate: the first encrypts, all decrypt. Losing every key makes the
# encrypted values unrecoverable, so back it up outside the server.
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default="")

# ─── Password breach check ───
# Off by default so development and tests never call a third-party API.
# production.py switches it on.
PASSWORD_BREACH_CHECK = env.bool("PASSWORD_BREACH_CHECK", default=False)
AUTH_PASSWORD_VALIDATORS += [
    {"NAME": "apps.accounts.validators.BreachedPasswordValidator"},
]

# Browsers hide response headers from frontend JavaScript unless listed here.
CORS_EXPOSE_HEADERS = ["X-Request-ID"]


# ─── Client IP ───
# How many reverse proxies in front of the app append to X-Forwarded-For.
# 0 trusts only the socket address: right locally, and the only safe answer
# when unsure, because the header is otherwise typed by the client.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)
REST_FRAMEWORK["NUM_PROXIES"] = TRUSTED_PROXY_COUNT

# ─── Login lockout ───
LOGIN_LOCKOUT_THRESHOLD = env.int("LOGIN_LOCKOUT_THRESHOLD", default=5)
LOGIN_LOCKOUT_WINDOW_MINUTES = env.int("LOGIN_LOCKOUT_WINDOW_MINUTES", default=15)

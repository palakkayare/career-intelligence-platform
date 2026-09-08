"""
Base settings - common to all environments.
"""
from pathlib import Path
import sys
from datetime import timedelta

import environ

# Build paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(
    DJANGO_DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / '.env')

# Security
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env('DJANGO_DEBUG')
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=[])

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    # Required for the full-text search field and index on Job. Without it
    # SearchVectorField happens to work, but Postgres-specific lookups
    # (trigram, unaccent) fail the moment they are added.
    'django.contrib.postgres',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'storages',
]

LOCAL_APPS = [
    'apps.core',
    'apps.accounts',
    'apps.skills',
    'apps.seekers',
    'apps.industries',
    'apps.recruiters',
    'apps.jobs',
    'apps.applications',
    'apps.payments',
    'apps.resumes',
    'apps.match_scores',
    'apps.notifications',
    'apps.career_intel',
    'apps.referrals',
    'apps.audit',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS
DEBUG_TOOLBAR_CONFIG = {'IS_RUNNING_TESTS': False}

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # CORS must be near the top
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.audit.middleware.AuditContextMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    'default': env.db('DATABASE_URL'),
}

# Custom User model — decided on Day 1, before any migrations
AUTH_USER_MODEL = 'accounts.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'  # India timezone
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# DRF configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ['v1'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'DEFAULT_THROTTLE_RATES': {
        'login': '5/min',
        'register': '10/hour',
        'password_reset': '3/hour',
        'otp_request': '3/hour',
        '2fa': '10/min',
        'search': '60/min',
        'apply': '20/hour',
        'subscription': '10/hour',
    },
    'EXCEPTION_HANDLER': 'apps.core.exceptions.custom_exception_handler',
    'PAGE_SIZE': 20,
}

# JWT configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_TOKEN_LIFETIME_MINUTES', default=15)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('JWT_REFRESH_TOKEN_LIFETIME_DAYS', default=7)),
    'ROTATE_REFRESH_TOKENS': True,       # Issue a new refresh token on every refresh
    'BLACKLIST_AFTER_ROTATION': True,    # Old refresh token gets blacklisted
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': env('JWT_SIGNING_KEY'),  # Deliberately different from SECRET_KEY
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# CORS
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000',
    'http://localhost:5173',
])

# ─── Frontend + email ───
# FRONTEND_URL is the base for every link the backend hands to a user:
# referral share links, password reset, email verification, unsubscribe.
# The default below only applies when FRONTEND_URL is absent from .env —
# an entry there always wins, so check .env first when a link points at the
# wrong port. Vite serves on 5173.
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:5173')

DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@example.com')
SUPPORT_EMAIL = env('SUPPORT_EMAIL', default='support@example.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

GOOGLE_OAUTH_CLIENT_ID = env('GOOGLE_OAUTH_CLIENT_ID', default='')

TOTP_ISSUER_NAME = 'Career Intelligence Platform'

# Media files (user uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Image upload limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024  # 5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Job posting settings
JOB_AUTO_APPROVE = env.bool('JOB_AUTO_APPROVE', default=False)

# Free tier limits (Phase 2 mein subscription se override hogi)
FREE_TIER_APPLICATION_LIMIT = env.int('FREE_TIER_APPLICATION_LIMIT', default=5)

# Razorpay
RAZORPAY_KEY_ID = env('RAZORPAY_KEY_ID', default='')
RAZORPAY_KEY_SECRET = env('RAZORPAY_KEY_SECRET', default='')
RAZORPAY_WEBHOOK_SECRET = env('RAZORPAY_WEBHOOK_SECRET', default='')

# Subscription settings
FREE_TRIAL_DAYS = env.int('FREE_TRIAL_DAYS', default=7)

if not RAZORPAY_KEY_ID and 'test' not in ' '.join(sys.argv):
    import warnings
    warnings.warn("RAZORPAY_KEY_ID not configured")

# Production mein test keys ka use prevent
if 'rzp_test_' in RAZORPAY_KEY_ID and not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured("Test Razorpay keys in production!")

# ─── Celery Configuration ───
CELERY_BROKER_URL = env('CELERY_BROKER_URL', default='redis://localhost:6379/1')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/2')

# Serialization
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# Timezone
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_ENABLE_UTC = True

# Task settings
CELERY_TASK_TRACK_STARTED = True          # "started" status dikhega
CELERY_TASK_TIME_LIMIT = 300              # 5 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 240         # 4 min soft warning
CELERY_TASK_ACKS_LATE = True              # Success ke baad acknowledge (crash pe retry)
CELERY_WORKER_PREFETCH_MULTIPLIER = 4     # Worker ek baar mein kitne tasks uthaye

# Retry settings
CELERY_TASK_AUTORETRY_FOR = (Exception,)  # Kisi bhi exception pe auto-retry
CELERY_TASK_MAX_RETRIES = 3
CELERY_TASK_DEFAULT_RETRY_DELAY = 60      # Retries ke beech 1 minute

# ─── AWS S3 Configuration ───
AWS_S3_USE_S3 = env.bool('AWS_S3_USE_S3', default=False)

if AWS_S3_USE_S3:
    AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = env('AWS_S3_REGION_NAME', default='ap-south-1')
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',
    }
    AWS_DEFAULT_ACL = None            # No public ACL (private bucket)
    AWS_S3_FILE_OVERWRITE = False     # Same-name files overwrite nahi honge
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_S3_ADDRESSING_STYLE = 'virtual'

    # S3 for media (user uploads), static stays local for now.
    # DEFAULT_FILE_STORAGE was removed in Django 5.1 in favour of STORAGES.
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
else:
    # Local storage (fallback for offline testing)
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

# ─── Cache Configuration (Redis) ───
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': env('REDIS_CACHE_URL', default='redis://localhost:6379/3'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

# ─── Salary privacy ───
SALARY_K_ANONYMITY = env.int('SALARY_K_ANONYMITY', default=5)
SALARY_MIN_INR = 100_000        # ₹1L floor
SALARY_MAX_INR = 100_000_000    # ₹10Cr ceiling

# ─── Audit trail ───
AUDITED_MODELS = [
    'accounts.User',
    'jobs.Job',
    'applications.Application',
    'payments.Subscription',
    'payments.PaymentTransaction',
    'recruiters.Company',
    'skills.Skill',
]
# ─── Invoicing ───
# Kept in settings rather than hard-coded in invoice.py so the GSTIN and
# address can differ per environment and a placeholder can never reach
# production by accident.
INVOICE_COMPANY_NAME = env(
    'INVOICE_COMPANY_NAME', default='Career Intelligence Platform Pvt Ltd',
)
INVOICE_COMPANY_ADDRESS = env(
    'INVOICE_COMPANY_ADDRESS', default='Bangalore, India',
)
INVOICE_GSTIN = env('INVOICE_GSTIN', default='')
INVOICE_GST_RATE = env.float('INVOICE_GST_RATE', default=18.0)
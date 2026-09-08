"""
Test settings.

Inherits from base rather than development so the debug toolbar never loads
during a test run. Everything here exists to make tests fast, isolated and
independent of external services (Redis, S3, SendGrid, Razorpay).
"""
import tempfile

from .base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ['*']

# Emails go to an in-memory outbox, so tests can assert on mail.outbox
# without any network call.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Celery runs tasks synchronously in-process. No broker, no worker needed.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Local memory cache instead of Redis.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# MD5 hashing is insecure but roughly 100x faster than PBKDF2. Fixtures
# create users constantly, so this is the single biggest speed win.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Throttles would otherwise make repeated API calls fail for reasons
# unrelated to what is being tested. The scopes are kept (an empty dict makes
# scope-based throttles raise ImproperlyConfigured) but set high enough never
# to fire. Tests that exercise throttling override these explicitly.
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {
        scope: '100000/hour'
        for scope in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES']  # noqa: F405
    },
}

# File uploads land in a throwaway directory instead of the real media root.
MEDIA_ROOT = tempfile.mkdtemp(prefix='cip-test-media-')
AWS_S3_USE_S3 = False

# Never let a test reach Razorpay.
RAZORPAY_KEY_ID = 'rzp_test_dummy'
RAZORPAY_KEY_SECRET = 'dummy_secret'
RAZORPAY_WEBHOOK_SECRET = 'dummy_webhook_secret'

# base.py resolves the storage backend from the env, so flipping
# AWS_S3_USE_S3 alone is not enough - it has to be forced back to local disk
# or uploads in tests hit the real bucket.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}
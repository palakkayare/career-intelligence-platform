"""
Development settings - DEBUG=True, console emails, etc.
"""
from .base import *

DEBUG = True
ALLOWED_HOSTS = ['*']

# Email - prints to console instead of sending real emails in dev
# Development — print emails to the console by default.
# Set USE_SENDGRID_IN_DEV=True in .env to send real emails via SendGrid.
if env.bool('USE_SENDGRID_IN_DEV', default=False):
    INSTALLED_APPS += ['anymail']
    EMAIL_BACKEND = 'anymail.backends.sendgrid.EmailBackend'
    ANYMAIL = {'SENDGRID_API_KEY': env('SENDGRID_API_KEY')}
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# CORS - allow all origins in dev
CORS_ALLOW_ALL_ORIGINS = True

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/0',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        },
    }
}

INSTALLED_APPS += ['debug_toolbar']

MIDDLEWARE = ['debug_toolbar.middleware.DebugToolbarMiddleware'] + MIDDLEWARE

INTERNAL_IPS = ['127.0.0.1']
"""
Custom exception handler for consistent error responses.
"""
from rest_framework.views import exception_handler
from rest_framework.exceptions import Throttled


def custom_exception_handler(exc, context):
    """
    Wrap DRF default handler to add friendly throttle messages.
    """
    response = exception_handler(exc, context)

    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait else 60
        response.data = {
            'error': 'Too many requests.',
            'detail': f'Please wait {wait} seconds before trying again.',
            'retry_after_seconds': wait,
        }

    return response
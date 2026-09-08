"""
Populates the audit thread-local for the duration of a request.
"""
from .context import clear_context, set_context


def _client_ip(request):
    """
    Prefer the left-most X-Forwarded-For entry, which is the original client
    when the app sits behind Nginx or a load balancer.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class AuditContextMiddleware:
    """
    Must sit after AuthenticationMiddleware so request.user is resolved.

    The context is always cleared in `finally`: threads are reused between
    requests, and a leaked user would be attributed to whoever comes next.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_context(
            user=getattr(request, 'user', None),
            ip_address=_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
        try:
            return self.get_response(request)
        finally:
            clear_context()

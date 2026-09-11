"""
Populates the audit thread-local for the duration of a request.
"""

from .context import clear_context, set_context


def _client_ip(request):
    """
    Only addresses appended by our own proxies are trusted; see
    apps/core/client_ip.py. The left-most X-Forwarded-For entry is typed by
    the client, and an audit trail that records whatever the client claims
    is not evidence of anything.
    """
    from apps.core.client_ip import client_ip

    return client_ip(request)


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
            user=getattr(request, "user", None),
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        try:
            return self.get_response(request)
        finally:
            clear_context()

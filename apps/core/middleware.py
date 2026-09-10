"""
Request ids.

Each request gets an id that goes out on the X-Request-ID response header,
onto every log line written while the request runs, and onto Sentry events.
A user reporting a problem can quote the header, and that one id finds the
logs and the Sentry issue together.
"""

import logging
import time
import uuid

from .log_format import request_id_var
from .observability import tag_request

logger = logging.getLogger("apps.core.requests")

REQUEST_HEADER = "HTTP_X_REQUEST_ID"
RESPONSE_HEADER = "X-Request-ID"


def incoming_request_id(request):
    """
    An id supplied by a load balancer or proxy, if it is a real UUID.

    Anything else is ignored: the header is client-controlled, and writing an
    arbitrary string into every log line lets anyone forge or pollute them.
    """
    raw = request.META.get(REQUEST_HEADER, "")
    if not raw or len(raw) > 36:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


def route_of(request):
    """
    The URL pattern, not the raw path.

    Raw paths carry things that do not belong in logs - unsubscribe tokens,
    public profile ids - and make every job detail page a separate entry.
    """
    match = getattr(request, "resolver_match", None)
    return getattr(match, "route", None) or "<unmatched>"


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = incoming_request_id(request) or str(uuid.uuid4())
        request.request_id = request_id
        token = request_id_var.set(request_id)
        tag_request(request_id)
        started = time.monotonic()

        try:
            response = self.get_response(request)
            response[RESPONSE_HEADER] = request_id

            # DRF copies the JWT user back onto the Django request, so by the
            # time the response is here, request.user is the real user.
            user = getattr(request, "user", None)
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "route": route_of(request),
                    "status_code": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    "user_id": user.pk if getattr(user, "is_authenticated", False) else None,
                },
            )
            return response
        finally:
            request_id_var.reset(token)

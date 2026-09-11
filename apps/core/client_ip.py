"""
The client's IP address, read the way the deployment actually delivers it.

X-Forwarded-For is a plain request header. Anyone can send
"X-Forwarded-For: 1.2.3.4" and, if the first entry is trusted, be recorded as
1.2.3.4 - and get a fresh rate limit and a fresh lockout counter with every
request. Only entries appended by our own proxies are trustworthy, and those
are at the right-hand end of the list.

TRUSTED_PROXY_COUNT says how many proxies sit in front of the app. The same
number is given to DRF as NUM_PROXIES, so throttling and lockout agree on who
the client is.
"""

import ipaddress

from django.conf import settings


def client_ip(request):
    remote_addr = request.META.get("REMOTE_ADDR")
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if proxies <= 0 or not forwarded:
        return remote_addr

    addresses = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not addresses:
        return remote_addr

    # Same selection DRF makes for NUM_PROXIES.
    candidate = addresses[-min(proxies, len(addresses))]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        # A malformed value would otherwise reach an inet column and fail
        # the whole request.
        return remote_addr

"""
Request context for audit signals.

Signals fire deep inside the ORM with no access to the request, so the acting
user and their IP are stashed in a thread-local by middleware and read back
here. Anything happening outside a request - a Celery task, a management
command, a shell session - simply finds an empty context and is recorded as a
system action.
"""

import threading

_state = threading.local()


def set_context(user=None, ip_address=None, user_agent=""):
    _state.user = user if (user and user.is_authenticated) else None
    _state.ip_address = ip_address
    _state.user_agent = (user_agent or "")[:500]


def clear_context():
    for attr in ("user", "ip_address", "user_agent"):
        if hasattr(_state, attr):
            delattr(_state, attr)


def get_context():
    return {
        "user": getattr(_state, "user", None),
        "ip_address": getattr(_state, "ip_address", None),
        "user_agent": getattr(_state, "user_agent", ""),
    }

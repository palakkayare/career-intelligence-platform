"""
Throttles for expensive or abuse-prone endpoints.

Auth-specific throttles live in apps.accounts.throttles; these cover the
platform-wide limits the blueprint sets out in Phase 3.
"""

from rest_framework.throttling import UserRateThrottle


class SearchThrottle(UserRateThrottle):
    """
    60 searches per minute per user.

    Search runs a full-text query with ranking on every call, so this is as
    much about protecting the database as about abuse. Generous enough that a
    person typing quickly never notices it.
    """

    scope = "search"


class ApplyThrottle(UserRateThrottle):
    """
    20 applications per hour per user.

    Separate from the plan quota, which counts a rolling 30 days. This is the
    burst limit: it stops scripted mass-applying without touching what a
    legitimate Pro subscriber does in an afternoon.
    """

    scope = "apply"

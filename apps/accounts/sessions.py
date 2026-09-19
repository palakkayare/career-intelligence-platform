"""Ending a user's sessions."""


def revoke_all_sessions(user):
    """
    Blacklist every outstanding refresh token of `user`, logging them out on
    every device once their short-lived access token expires. Returns how
    many tokens were newly blacklisted.
    """
    try:
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )
    except ImportError:  # blacklist app not installed
        return 0

    count = 0
    for token in OutstandingToken.objects.filter(user=user):
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        if created:
            count += 1
    return count

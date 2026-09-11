"""
Login lockout: stop password guessing against one account from one address.

After LOGIN_LOCKOUT_THRESHOLD failed attempts for an email from an IP within
LOGIN_LOCKOUT_WINDOW_MINUTES, further attempts from that IP are refused
without checking the password, until the oldest of those failures ages out.

Keyed on email *and* IP, deliberately:

- Email alone would let anyone lock anyone out. Five wrong passwords typed
  against a victim's address would shut the victim out, repeatably.
- The count is kept for any email string, registered or not, so a lock
  reveals nothing about whether an account exists.

Built on LoginHistory, which already records every attempt, rather than on
the cache: no second copy of the same facts, and it survives a cache flush.
Attempts refused by the lock are not recorded, so a lock always ends on time.
"""

import math
from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def _threshold():
    return getattr(settings, "LOGIN_LOCKOUT_THRESHOLD", 5)


def _window():
    return timedelta(minutes=getattr(settings, "LOGIN_LOCKOUT_WINDOW_MINUTES", 15))


class LoginLockoutService:
    @classmethod
    def seconds_remaining(cls, email, ip):
        """0 if attempts are allowed; otherwise seconds until they are."""
        from .models import LoginHistory

        now = timezone.now()
        window = _window()
        threshold = _threshold()

        recent = LoginHistory.objects.filter(
            ip_address=ip,
            email_attempted__iexact=email,
            created_at__gte=now - window,
        )

        # A successful login clears the slate.
        last_success = (
            recent.filter(status=LoginHistory.Status.SUCCESS)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        failures = recent.filter(status=LoginHistory.Status.FAILED)
        if last_success is not None:
            failures = failures.filter(created_at__gt=last_success)

        latest = list(
            failures.order_by("-created_at").values_list("created_at", flat=True)[:threshold]
        )
        if len(latest) < threshold:
            return 0

        unlock_at = latest[-1] + window
        return max(1, math.ceil((unlock_at - now).total_seconds()))

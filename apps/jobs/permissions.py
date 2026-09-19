from rest_framework import permissions

from apps.core.permissions import IsPlatformAdmin
from apps.recruiters.permissions import IsRecruiter  # noqa: F401  re-exported


class IsJobOwnerOrReadOnly(permissions.BasePermission):
    """Only the recruiter who posted can modify."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not hasattr(request.user, "recruiter_profile"):
            return False
        return obj.posted_by_id == request.user.recruiter_profile.id


class IsAdminUser(IsPlatformAdmin):
    """
    Internal admin. Kept as a name here because the job views import it;
    the rule itself lives in apps.core.permissions.
    """

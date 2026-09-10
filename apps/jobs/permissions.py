from rest_framework import permissions

from apps.recruiters.permissions import IsRecruiter  # noqa: F401  re-exported


class IsJobOwnerOrReadOnly(permissions.BasePermission):
    """Only the recruiter who posted can modify."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if not hasattr(request.user, "recruiter_profile"):
            return False
        return obj.posted_by_id == request.user.recruiter_profile.id


class IsAdminUser(permissions.BasePermission):
    """Internal admin (User.role='admin' or is_superuser)."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role == "admin" or request.user.is_superuser

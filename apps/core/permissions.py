"""Permissions shared across apps."""

from rest_framework import permissions


class IsPlatformAdmin(permissions.BasePermission):
    """
    Someone who runs the platform: job approvals, review moderation, the
    revenue and health dashboards.

    The rule is the user's own role, not Django's `is_staff`. Both were in
    use before - job approval checked the role while moderation and the admin
    dashboards checked `is_staff` - so an admin created without the Django
    flag could approve jobs but got 403 on everything else, and a staff user
    who was not an admin got the opposite half. `is_superuser` still counts,
    because a superuser can do all of it from the Django admin anyway.
    """

    message = "Only platform administrators can do this."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (getattr(user, "role", None) == "admin" or user.is_superuser)
        )

from rest_framework import permissions


class IsSeeker(permissions.BasePermission):
    """User must have role='seeker'."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "seeker"


class CanViewProfile(permissions.BasePermission):
    """
    Visibility-based access:
    - PUBLIC: any authenticated user
    - RECRUITERS_ONLY: recruiters or self
    - PRIVATE: only self
    """

    def has_object_permission(self, request, view, obj):
        # Self-view always allowed
        if obj.user_id == request.user.id:
            return True

        if obj.visibility == "public":
            return request.user.is_authenticated

        if obj.visibility == "recruiters_only":
            return request.user.role == "recruiter"

        # private
        return False

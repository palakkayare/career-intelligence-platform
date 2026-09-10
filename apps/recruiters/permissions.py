from rest_framework import permissions


class IsRecruiter(permissions.BasePermission):
    """User must have role='recruiter'."""

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "recruiter"


class IsCompanyAdminOrReadOnly(permissions.BasePermission):
    """
    Only company admins can modify the company.
    Anyone authenticated can view.
    """

    def has_object_permission(self, request, view, obj):
        # obj is a Company instance
        if request.method in permissions.SAFE_METHODS:
            return True

        if not hasattr(request.user, "recruiter_profile"):
            return False

        profile = request.user.recruiter_profile
        return profile.company_id == obj.id and profile.is_company_admin


class CanViewRecruiterContact(permissions.BasePermission):
    """
    Visibility-based contact (phone, email).
    Note: This permission is checked at serializer level
    using context, not as object permission. Stub here for clarity.
    """

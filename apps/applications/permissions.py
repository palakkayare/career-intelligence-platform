from rest_framework import permissions


class IsApplicationOwner(permissions.BasePermission):
    """Seeker who submitted this application."""

    def has_object_permission(self, request, view, obj):
        if request.user.role != "seeker":
            return False
        return obj.seeker.user_id == request.user.id


class IsApplicationRecruiter(permissions.BasePermission):
    """Recruiter who posted the job that this application is for."""

    def has_object_permission(self, request, view, obj):
        if request.user.role != "recruiter":
            return False
        if not hasattr(request.user, "recruiter_profile"):
            return False
        return obj.job.posted_by_id == request.user.recruiter_profile.id

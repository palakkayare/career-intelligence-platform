"""
DRF permission classes for plan-gated views.

Use these for hard access gates (403 for non-Pro users), e.g. a
match-score endpoint. For quota checks (applications, job posts)
prefer service-level validation instead — a quota is a business
rule, not a permission, and deserves a 400 with a clear message.
"""

from rest_framework import permissions

from .services import FeatureGateService


class HasProAccess(permissions.BasePermission):
    """Allow only users on any paid plan (Pro or Business)."""

    message = "This feature requires a Pro or Business subscription."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        plan = FeatureGateService.get_user_plan(request.user)
        return bool(plan and plan.is_paid)


class HasFeature(permissions.BasePermission):
    """
    Generic feature-flag gate. Do not use directly — build a concrete
    class via the factory: HasFeature.create('match_score').
    """

    feature_name = None

    def has_permission(self, request, view):
        if not request.user.is_authenticated or not self.feature_name:
            return False
        return FeatureGateService.has_feature(request.user, self.feature_name)

    @classmethod
    def create(cls, feature):
        """Build a permission class bound to one specific feature flag."""
        return type(
            f'Has{feature.title().replace("_", "")}',
            (cls,),
            {
                "feature_name": feature,
                "message": f"Your current plan does not include the {feature} feature.",
            },
        )


# Pre-built gates for the features we know are coming (Steps 17+)
HasMatchScore = HasFeature.create("match_score")
HasSkillGap = HasFeature.create("skill_gap")
HasCareerPath = HasFeature.create("career_path")
HasCandidateSearch = HasFeature.create("candidate_search")

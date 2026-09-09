"""
Recruiter and company services.
"""
from rest_framework.exceptions import ValidationError


class CompanyTeamService:
    """
    Team size limits.

    The plan belongs to a person, not a company, so the limit is read from
    whoever created the company - they are the one paying for the Business
    seat that the rest of the team sits under.
    """

    @classmethod
    def team_limit(cls, company):
        """
        Seats this company is allowed. None means unlimited.

        Seeker plans leave max_team_members unset because team size means
        nothing to them - but None reads as unlimited here, so a recruiter on
        a Pro trial would get an unlimited team. Anything that is not a
        Business plan falls back to the free allowance.
        """
        from apps.payments.models import Plan
        from apps.payments.services import FeatureGateService

        def free_limit():
            free = Plan.objects.filter(tier=Plan.Tier.FREE).first()
            return free.max_team_members if free else 1

        if company.created_by_id is None:
            return free_limit()

        plan = FeatureGateService.get_user_plan(company.created_by)

        if plan.tier != Plan.Tier.BUSINESS:
            return free_limit()

        return plan.max_team_members
    @classmethod
    def current_size(cls, company):
        return company.recruiters.count()

    @classmethod
    def check_can_add(cls, company):
        """
        Raise if the company has no seat left. Returns the limit otherwise.
        """
        limit = cls.team_limit(company)

        if limit is None:
            return None

        used = cls.current_size(company)
        if used >= limit:
            raise ValidationError({
                'detail': (
                    f'{company.name} has used all {limit} of its team seats. '
                    f'Upgrade the company plan to add more recruiters.'
                ),
            })

        return limit
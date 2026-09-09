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

        A company with no creator on file falls back to the free tier rather
        than to unlimited, so a data gap cannot become a free upgrade.
        """
        from apps.payments.services import FeatureGateService

        if company.created_by_id is None:
            from apps.payments.models import Plan

            free = Plan.objects.filter(tier=Plan.Tier.FREE).first()
            return free.max_team_members if free else 1

        plan = FeatureGateService.get_user_plan(company.created_by)
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


class TalentPoolService:
    """
    Running a saved candidate search.

    Results are always computed from the stored filters, never cached. A
    cached list would keep showing seekers who have since gone private or
    closed their account, which is exactly the guarantee the discoverable()
    queryset exists to make.
    """

    @classmethod
    def members(cls, pool, page=1, page_size=20):
        """Current members of the pool."""
        from .candidate_services import CandidateSearchService

        return CandidateSearchService.search(
            recruiter=pool.recruiter,
            filters=pool.filters or {},
            page=page,
            page_size=page_size,
        )

    @classmethod
    def new_since_last_check(cls, pool):
        """
        Seekers who have entered the pool since the last sweep.

        "Entered" means their profile was created after the marker - a
        seeker who edited an old profile has not newly joined, and treating
        them as new would send the same recruiter the same person twice.
        """
        from .candidate_services import CandidateSearchService

        qs = CandidateSearchService._base_queryset()
        qs = CandidateSearchService._apply_filters(qs, pool.filters or {})

        if pool.last_checked_at:
            qs = qs.filter(created_at__gt=pool.last_checked_at)

        return qs.select_related('user')

    @classmethod
    def mark_checked(cls, pool):
        from django.utils import timezone

        pool.last_checked_at = timezone.now()
        pool.save(update_fields=['last_checked_at'])
        return pool

    @classmethod
    def notify_new_members(cls, pool, limit=10):
        """
        Tell the recruiter about new arrivals, then move the marker.

        Returns the number reported. The marker moves even when nothing was
        found, so an idle pool does not re-scan the same window forever.
        """
        from apps.notifications.models import NotificationKind
        from apps.notifications.service import NotificationService

        if not pool.notify_on_new:
            return 0

        new_members = list(cls.new_since_last_check(pool)[:limit])

        if new_members:
            first = new_members[0]
            NotificationService.create(
                user=pool.recruiter.user,
                kind=NotificationKind.NEW_MATCHING_CANDIDATE,
                title=(
                    f'{len(new_members)} new candidates in "{pool.name}"'
                ),
                message=(
                    f'{first.full_name or "A candidate"} and '
                    f'{len(new_members) - 1} others match "{pool.name}".'
                    if len(new_members) > 1
                    else f'{first.full_name or "A candidate"} matches '
                         f'"{pool.name}".'
                ),
                link=f'/candidates/pools/{pool.pk}/',
                context={
                    'pool_name': pool.name,
                    'new_count': len(new_members),
                },
            )

        cls.mark_checked(pool)
        return len(new_members)
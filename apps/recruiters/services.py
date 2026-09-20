"""
Recruiter and company services.
"""

from rest_framework.exceptions import PermissionDenied, ValidationError


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

        A company with no creator on file, or a creator whose plan cannot be
        resolved, falls back to the free tier rather than to unlimited: a data
        gap must not become a free upgrade, and it must not crash the join
        either.
        """
        from apps.payments.services import FeatureGateService

        plan = None
        if company.created_by_id is not None:
            plan = FeatureGateService.get_user_plan(company.created_by)
        if plan is None:
            from apps.payments.models import Plan

            free = Plan.objects.filter(tier=Plan.Tier.FREE).first()
            return free.max_team_members if free else 1

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
            raise ValidationError(
                {
                    "detail": (
                        f"{company.name} has used all {limit} of its team seats. "
                        f"Upgrade the company plan to add more recruiters."
                    ),
                }
            )

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

        return qs.select_related("user")

    @classmethod
    def mark_checked(cls, pool):
        from django.utils import timezone

        pool.last_checked_at = timezone.now()
        pool.save(update_fields=["last_checked_at"])
        return pool

    @classmethod
    def notify_new_members(cls, pool, limit=10):
        """
        Tell the recruiter about new arrivals, then move the marker.

        Returns the number reported. The marker moves even when nothing was
        found, so an idle pool does not re-scan the same window forever.
        """
        from apps.notifications import links
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
                title=(f'{len(new_members)} new candidates in "{pool.name}"'),
                message=(
                    f'{first.full_name or "A candidate"} and '
                    f'{len(new_members) - 1} others match "{pool.name}".'
                    if len(new_members) > 1
                    else f'{first.full_name or "A candidate"} matches ' f'"{pool.name}".'
                ),
                link=links.candidate_search(),
                context={
                    "pool_name": pool.name,
                    "new_count": len(new_members),
                },
            )

        cls.mark_checked(pool)
        return len(new_members)


class CompanyJoinService:
    """
    Joining an existing company.

    A request waits for one of the company's admins. Two cases are decided
    on the spot, because waiting would be either impossible or pointless:
      - the company has no members yet, so nobody could approve. Admin
        rights come with that only for the company's own creator: whoever
        walks into an empty company first must not end up running it;
      - the recruiter's email domain matches the company's website domain,
        which is as good a proof of belonging as an admin's click.
    """

    @staticmethod
    def _domain(value):
        if not value:
            return ""
        value = str(value).strip().lower()
        if "@" in value:
            value = value.rsplit("@", 1)[1]
        value = value.split("//")[-1].split("/")[0]
        return value[4:] if value.startswith("www.") else value

    @classmethod
    def email_domain_matches(cls, recruiter, company):
        company_domain = cls._domain(company.website)
        return bool(company_domain) and cls._domain(recruiter.user.email) == company_domain

    @classmethod
    def request_to_join(cls, recruiter, company, message=""):
        """
        Returns (join_request, joined) - `joined` is True when the recruiter
        is already in the company as a result of this call.
        """
        from django.utils import timezone

        from .models import CompanyJoinRequest, RecruiterProfile

        if recruiter.company_id:
            raise ValidationError("You are already part of a company. Leave first.")

        CompanyTeamService.check_can_add(company)

        empty_company = not RecruiterProfile.objects.filter(company=company).exists()
        auto = empty_company or cls.email_domain_matches(recruiter, company)
        # Only the creator takes the admin seat. With no creator on file
        # nobody does: an admin is something a person is given, not something
        # they get by arriving first.
        as_admin = empty_company and company.created_by_id == recruiter.user_id

        existing = CompanyJoinRequest.objects.filter(
            company=company, recruiter=recruiter, status=CompanyJoinRequest.Status.PENDING
        ).first()
        if existing and not auto:
            return existing, False

        join_request = existing or CompanyJoinRequest(
            company=company, recruiter=recruiter, message=message[:300]
        )
        if auto:
            join_request.status = CompanyJoinRequest.Status.APPROVED
            join_request.decided_at = timezone.now()
            join_request.save()
            cls._place(recruiter, company, as_admin=as_admin)
            return join_request, True

        join_request.save()

        from apps.notifications.triggers import notify_company_join_requested

        notify_company_join_requested(join_request)
        return join_request, False

    @classmethod
    def decide(cls, join_request, admin, approve):
        """Approve or reject a pending request. `admin` must run the company."""
        from django.utils import timezone

        from .models import CompanyJoinRequest

        if not admin.is_company_admin or admin.company_id != join_request.company_id:
            raise PermissionDenied("Only an admin of this company can decide join requests.")
        if join_request.status != CompanyJoinRequest.Status.PENDING:
            raise ValidationError("This request has already been decided.")

        recruiter = join_request.recruiter
        if approve:
            if recruiter.company_id:
                # They joined somewhere else while the request sat here.
                join_request.status = CompanyJoinRequest.Status.CANCELLED
                join_request.decided_by = admin
                join_request.decided_at = timezone.now()
                join_request.save()
                raise ValidationError("That recruiter has already joined another company.")
            CompanyTeamService.check_can_add(join_request.company)
            cls._place(recruiter, join_request.company, as_admin=False)

        join_request.status = (
            CompanyJoinRequest.Status.APPROVED if approve else CompanyJoinRequest.Status.REJECTED
        )
        join_request.decided_by = admin
        join_request.decided_at = timezone.now()
        join_request.save()

        from apps.notifications.triggers import notify_company_join_decided

        notify_company_join_decided(join_request, approved=approve)
        return join_request

    @staticmethod
    def _place(recruiter, company, as_admin):
        recruiter.company = company
        recruiter.is_company_admin = as_admin
        recruiter.save(update_fields=["company", "is_company_admin"])

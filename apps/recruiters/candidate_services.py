"""
Candidate discovery services: search, profile preview and contact reveal.
"""

import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q, Count, Case, When, Value, IntegerField
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied

from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.seekers.models import SeekerProfile

from .models import CandidateView, RecruiterCredits

logger = logging.getLogger(__name__)

# A seeker is logged as a "search result view" at most once per recruiter
# inside this window. Without it the audit table grows on every keystroke.
SEARCH_VIEW_DEDUPE_HOURS = 24

# Upper bound on how many candidates we re-rank by match score in memory.
MATCH_SCORE_RANKING_LIMIT = 1000


class CandidateSearchService:
    """Search seekers using recruiter-supplied filters."""

    @classmethod
    def search(cls, recruiter, filters: dict, target_job_id=None,
               page=1, page_size=20):
        """
        Supported filter keys:
            skill_ids               list[int]
            experience_years_min    int
            experience_years_max    int
            location_city           str
            min_profile_strength    int  (0-100)
            q                       str  (free-text)
        """
        qs = cls._base_queryset()
        qs = cls._apply_filters(qs, filters)

        # Annotate how many of the requested skills each seeker actually has
        if filters.get('skill_ids'):
            qs = qs.annotate(
                matched_skills_count=Count(
                    'skills',
                    filter=Q(skills__id__in=filters['skill_ids']),
                    distinct=True,
                ),
            )

        # ---- Ordering ----
        if target_job_id:
            qs = cls._order_by_match_score(qs, target_job_id)
        elif filters.get('skill_ids'):
            qs = qs.order_by('-matched_skills_count', '-updated_at')
        else:
            # Nothing to rank by, so lead with the profiles a recruiter can
            # actually assess. A half-filled profile at the top of the list
            # wastes the one screen they look at.
            qs = qs.order_by('-profile_strength', '-updated_at')

        # ---- Pagination ----
        total = qs.count()
        offset = (page - 1) * page_size
        seekers = list(
            qs[offset:offset + page_size]
            .select_related('user')
            .prefetch_related('skills')
        )

        # ---- Audit trail (search-result level only) ----
        cls._record_search_views(recruiter, seekers, target_job_id)

        # ---- Attach match scores for the response ----
        match_scores_map = {}
        if target_job_id and seekers:
            match_scores_map = {
                ms.seeker_id: ms
                for ms in MatchScore.objects.filter(
                    seeker__in=seekers,
                    job_id=target_job_id,
                )
            }

        return {
            'total': total,
            'page': page,
            'page_size': page_size,
            'has_next': offset + page_size < total,
            'seekers': seekers,
            'match_scores_map': match_scores_map,
        }

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    @classmethod
    def _base_queryset(cls):
        """Only active, verified seekers who opted in to being discovered."""
        return SeekerProfile.discoverable()

    @classmethod
    def _apply_filters(cls, qs, filters):
        if filters.get('skill_ids'):
            qs = qs.filter(skills__id__in=filters['skill_ids']).distinct()

        if filters.get('location_city'):
            qs = qs.filter(location__icontains=filters['location_city'])

        if filters.get('experience_years_min') is not None:
            qs = qs.filter(
                years_of_experience__gte=filters['experience_years_min']
            )

        if filters.get('experience_years_max') is not None:
            qs = qs.filter(
                years_of_experience__lte=filters['experience_years_max']
            )

        # Feature 15. Only filterable now that the score is a stored column
        # rather than something computed on read.
        if filters.get('min_profile_strength') is not None:
            qs = qs.filter(
                profile_strength__gte=filters['min_profile_strength'],
            )

        if filters.get('q'):
            term = filters['q']
            qs = qs.filter(
                Q(full_name__icontains=term)
                | Q(current_title__icontains=term)
                | Q(target_role__icontains=term)
                | Q(bio__icontains=term)
            )

        return qs

    @classmethod
    def _order_by_match_score(cls, qs, target_job_id):
        """
        Re-rank the queryset by the pre-computed MatchScore for a given job.
        Seekers without a score are appended at the end.
        """
        job = Job.objects.filter(pk=target_job_id, is_deleted=False).first()
        if not job:
            # Unknown job — fall back to recency instead of failing the search
            return qs.order_by('-updated_at')

        candidate_ids = list(
            qs.values_list('id', flat=True)[:MATCH_SCORE_RANKING_LIMIT]
        )
        if not candidate_ids:
            return qs.none()

        scored_ids = list(
            MatchScore.objects
            .filter(seeker_id__in=candidate_ids, job=job)
            .order_by('-overall_score')
            .values_list('seeker_id', flat=True)
        )
        scored = set(scored_ids)
        unscored_ids = [sid for sid in candidate_ids if sid not in scored]
        final_order = scored_ids + unscored_ids

        # CASE/WHEN preserves our Python-side ordering inside SQL
        preserved_order = Case(
            *[When(pk=sid, then=Value(index))
              for index, sid in enumerate(final_order)],
            output_field=IntegerField(),
        )
        return (
            qs.filter(pk__in=final_order)
              .annotate(_match_order=preserved_order)
              .order_by('_match_order')
        )

    @classmethod
    def _record_search_views(cls, recruiter, seekers, target_job_id):
        """Bulk-log one search-result view per seeker, skipping recent duplicates."""
        if not seekers:
            return

        cutoff = timezone.now() - timedelta(hours=SEARCH_VIEW_DEDUPE_HOURS)
        already_logged = set(
            CandidateView.objects
            .filter(
                recruiter=recruiter,
                seeker__in=seekers,
                view_kind=CandidateView.ViewKind.SEARCH_RESULT,
                created_at__gte=cutoff,
            )
            .values_list('seeker_id', flat=True)
        )

        target_job = (
            Job.objects.filter(pk=target_job_id).first()
            if target_job_id else None
        )

        views = [
            CandidateView(
                recruiter=recruiter,
                seeker=seeker,
                view_kind=CandidateView.ViewKind.SEARCH_RESULT,
                target_job=target_job,
            )
            for seeker in seekers
            if seeker.id not in already_logged
        ]
        if views:
            CandidateView.objects.bulk_create(views)


class CandidateProfileService:
    """Profile detail view and credit-gated contact reveal."""

    @classmethod
    def get_profile(cls, recruiter, seeker, target_job_id=None):
        """
        Return the seeker with contact still masked, unless this recruiter
        has already paid a credit for them. Logs a 'detail' view.
        """
        previously_revealed = CandidateView.objects.filter(
            recruiter=recruiter,
            seeker=seeker,
            contact_revealed=True,
        ).exists()

        target_job = (
            Job.objects.filter(pk=target_job_id).first()
            if target_job_id else None
        )

        CandidateView.objects.create(
            recruiter=recruiter,
            seeker=seeker,
            view_kind=CandidateView.ViewKind.DETAIL,
            target_job=target_job,
            contact_revealed=previously_revealed,
        )

        return {
            'seeker': seeker,
            'contact_revealed': previously_revealed,
        }

    @classmethod
    @transaction.atomic
    def reveal_contact(cls, recruiter, seeker):
        """
        Unlock a seeker's contact details. Costs one credit.
        Idempotent: revealing the same seeker again is free.
        """
        # Row-level lock so two concurrent requests cannot both pass the
        # "credits remaining" check and over-spend the wallet.
        credits = (
            RecruiterCredits.objects
            .select_for_update()
            .filter(recruiter=recruiter)
            .first()
        )
        if credits is None:
            raise ValidationError({
                'detail': 'No credit allocation found for your account.',
            })

        # Lazy reset in case the nightly Beat task has not run yet
        if credits.is_cycle_expired():
            credits.reset_cycle()

        already_revealed = CandidateView.objects.filter(
            recruiter=recruiter,
            seeker=seeker,
            contact_revealed=True,
        ).exists()

        if already_revealed:
            logger.info(
                'Recruiter %s re-opened already revealed seeker %s (no charge)',
                recruiter.id, seeker.id,
            )
            return {
                'already_revealed': True,
                'credits_remaining': credits.remaining,
                'seeker': seeker,
            }

        if credits.remaining <= 0:
            raise PermissionDenied({
                'detail': (
                    f'You have used all your contact reveals for this cycle '
                    f'({credits.reveals_used_this_month}/'
                    f'{credits.monthly_reveal_limit}). '
                    f'Your limit resets on '
                    f'{credits.cycle_ends_on.strftime("%d %b %Y")}.'
                ),
            })

        # Spend the credit
        credits.reveals_used_this_month += 1
        credits.save(update_fields=['reveals_used_this_month'])

        # Mark the most recent detail view as revealed, or create a new record
        view = (
            CandidateView.objects
            .filter(
                recruiter=recruiter,
                seeker=seeker,
                view_kind=CandidateView.ViewKind.DETAIL,
                contact_revealed=False,
            )
            .order_by('-created_at')
            .first()
        )
        if view:
            view.contact_revealed = True
            view.revealed_at = timezone.now()
            view.save(update_fields=['contact_revealed', 'revealed_at'])
        else:
            CandidateView.objects.create(
                recruiter=recruiter,
                seeker=seeker,
                view_kind=CandidateView.ViewKind.DETAIL,
                contact_revealed=True,
                revealed_at=timezone.now(),
            )

        cls._notify_seeker(recruiter, seeker)

        return {
            'already_revealed': False,
            'credits_remaining': credits.remaining,
            'seeker': seeker,
        }

    @staticmethod
    def _notify_seeker(recruiter, seeker):
        """Tell the seeker their contact details were unlocked."""
        from apps.notifications.models import NotificationKind
        from apps.notifications.service import NotificationService

        company_name = (
            recruiter.company.name if recruiter.company_id else 'a company'
        )
        try:
            NotificationService.create(
                user=seeker.user,
                kind=NotificationKind.PROFILE_VIEWED,
                title='A recruiter unlocked your contact details',
                message=(
                    f'{recruiter.full_name} from {company_name} viewed your '
                    f'contact information. They may reach out to you soon.'
                ),
                link='/seekers/me/who-viewed/',
                context={
                    'recruiter_name': recruiter.full_name,
                    'company_name': company_name,
                },
            )
        except Exception as exc:
            # Notification failure must never roll back a paid reveal
            logger.error('Failed to send profile-viewed notification: %s', exc)
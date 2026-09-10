"""
Review services.
"""
import logging

from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import (
    CompanyResponse,
    CompanyReview,
    InterviewExperience,
    ReviewHelpfulVote,
    ReviewReport,
)

logger = logging.getLogger(__name__)

# Reports needed before a review is hidden pending moderation. Above one so
# that a handful of coordinated reports cannot bury a fair review, low
# enough that genuinely abusive content does not sit up for days.
REPORT_HIDE_THRESHOLD = 3

# How long the author can edit after posting. Long enough to fix a typo,
# short enough that a review cannot be quietly rewritten after a company
# responds to it.
EDIT_WINDOW_HOURS = 24


class ReviewService:
    """Writing and reading company reviews."""

    @classmethod
    def create(cls, author, company, data):
        """
        Post a review.

        Verification is checked here rather than trusted from the client:
        an is_verified badge the submitter controls is worth nothing.
        """
        if CompanyReview.objects.filter(company=company, author=author).exists():
            raise ValidationError({
                'detail': 'You have already reviewed this company. '
                          'You can edit your existing review instead.',
            })

        return CompanyReview.objects.create(
            company=company,
            author=author,
            is_verified_employee=cls._looks_like_an_employee(author, company),
            **data,
        )

    @staticmethod
    def _looks_like_an_employee(author, company):
        """
        Weak verification: did this person apply to this company through the
        platform?

        It proves interest, not employment. The badge is labelled as what it
        is rather than implying the platform confirmed a payslip - claiming
        stronger verification than we have would be worse than none.
        """
        from apps.applications.models import Application

        profile = getattr(author, 'seeker_profile', None)
        if profile is None:
            return False

        return Application.all_objects.filter(
            seeker=profile, job__company=company,
        ).exists()

    @classmethod
    def update(cls, review, author, data):
        """Edit within the window. Only the author, only for a while."""
        if review.author_id != author.id:
            raise PermissionDenied('This is not your review.')

        age_hours = (timezone.now() - review.created_at).total_seconds() / 3600
        if age_hours > EDIT_WINDOW_HOURS:
            raise ValidationError({
                'detail': f'Reviews can only be edited within '
                          f'{EDIT_WINDOW_HOURS} hours of posting.',
            })

        for field, value in data.items():
            setattr(review, field, value)
        review.save()
        return review

    @classmethod
    def delete(cls, review, author):
        """
        Withdraw a review. Soft delete, so a company response does not end
        up orphaned and the moderation history survives.
        """
        if review.author_id != author.id:
            raise PermissionDenied('This is not your review.')

        review.soft_delete()
        return review

    @classmethod
    def published_for(cls, company):
        return (
            CompanyReview.objects
            .filter(
                company=company,
                status=CompanyReview.Status.PUBLISHED,
                is_deleted=False,
            )
            .select_related('company')
            .prefetch_related('company_response')
        )

    @classmethod
    def summary(cls, company):
        """
        Aggregate ratings for a company.

        Returns has_reviews=False rather than zeros when there are none.
        A company showing 0.0 stars because nobody has reviewed it would be
        actively misleading.
        """
        reviews = cls.published_for(company)

        aggregates = reviews.aggregate(
            count=Count('id'),
            culture=Avg('rating_culture'),
            management=Avg('rating_management'),
            growth=Avg('rating_growth'),
            salary=Avg('rating_salary'),
            recommend=Count('id', filter=Q(would_recommend=True)),
        )

        if not aggregates['count']:
            return {'has_reviews': False, 'review_count': 0}

        dimensions = {
            'culture': round(aggregates['culture'], 1),
            'management': round(aggregates['management'], 1),
            'growth': round(aggregates['growth'], 1),
            'salary': round(aggregates['salary'], 1),
        }

        return {
            'has_reviews': True,
            'review_count': aggregates['count'],
            'overall': round(sum(dimensions.values()) / 4, 1),
            'ratings': dimensions,
            'recommend_pct': round(
                aggregates['recommend'] / aggregates['count'] * 100, 1,
            ),
            'verified_pct': round(
                reviews.filter(is_verified_employee=True).count()
                / aggregates['count'] * 100, 1,
            ),
        }

    @classmethod
    def mark_helpful(cls, review, user):
        """
        Vote a review useful. Idempotent, and never by its own author.
        """
        if review.author_id == user.id:
            raise ValidationError({
                'detail': 'You cannot mark your own review helpful.',
            })

        _, created = ReviewHelpfulVote.objects.get_or_create(
            review=review, user=user,
        )

        if created:
            CompanyReview.objects.filter(pk=review.pk).update(
                helpful_count=F('helpful_count') + 1,
            )
            review.refresh_from_db(fields=['helpful_count'])

        return review, created


class ModerationService:
    """Reports and what happens to them."""

    @classmethod
    @transaction.atomic
    def report(cls, review, reporter, reason, detail=''):
        """
        Flag a review.

        Hiding happens at a threshold, not on the first report. One click
        hiding content would let a company bury anything it disliked.
        """
        if review.author_id == reporter.id:
            raise ValidationError({
                'detail': 'You cannot report your own review. '
                          'Delete it instead.',
            })

        _, created = ReviewReport.objects.get_or_create(
            review=review, reported_by=reporter,
            defaults={'reason': reason, 'detail': detail},
        )

        if not created:
            return review, False

        CompanyReview.objects.filter(pk=review.pk).update(
            report_count=F('report_count') + 1,
        )
        review.refresh_from_db(fields=['report_count'])

        if review.report_count >= REPORT_HIDE_THRESHOLD:
            review.status = CompanyReview.Status.UNDER_REVIEW
            review.save(update_fields=['status'])
            logger.info(
                'Review %s hidden after %s reports',
                review.pk, review.report_count,
            )

        return review, True

    @classmethod
    def restore(cls, review, admin_notes=''):
        """Moderator decided the review is fine. Report count resets."""
        review.status = CompanyReview.Status.PUBLISHED
        review.report_count = 0
        review.save(update_fields=['status', 'report_count'])

        review.reports.update(reviewed_by_admin=True, admin_notes=admin_notes)
        return review

    @classmethod
    def remove(cls, review, admin_notes=''):
        """Moderator agreed with the reports."""
        review.status = CompanyReview.Status.REMOVED
        review.save(update_fields=['status'])

        review.reports.update(reviewed_by_admin=True, admin_notes=admin_notes)
        return review

    @classmethod
    def queue(cls):
        """Reviews waiting on a moderator, most-reported first."""
        return (
            CompanyReview.objects
            .filter(status=CompanyReview.Status.UNDER_REVIEW, is_deleted=False)
            .select_related('company')
            .order_by('-report_count', 'created_at')
        )


class ResponseService:
    """A company replying to a review."""

    @classmethod
    def respond(cls, review, recruiter, text):
        """
        Post the company's reply.

        Only a recruiter at that company, and only once. A second reply
        turns the page into an argument, which helps nobody reading it.
        """
        if recruiter.company_id != review.company_id:
            raise PermissionDenied(
                'You can only respond to reviews of your own company.',
            )

        if hasattr(review, 'company_response'):
            raise ValidationError({
                'detail': 'This review already has a company response.',
            })

        return CompanyResponse.objects.create(
            review=review,
            responder=recruiter,
            responder_name=recruiter.full_name,
            responder_title=recruiter.position,
            response=text,
        )


class InterviewExperienceService:
    """Interview accounts. Separate audience from reviews."""

    @classmethod
    def create(cls, author, company, data):
        """
        Post an interview experience.

        Unlike reviews there is no one-per-company limit: interviewing at
        the same company twice, years apart, is two genuinely different
        experiences and both are worth reading.
        """
        return InterviewExperience.objects.create(
            company=company, author=author, **data,
        )

    @classmethod
    def published_for(cls, company):
        return InterviewExperience.objects.filter(
            company=company,
            status=CompanyReview.Status.PUBLISHED,
            is_deleted=False,
        )

    @classmethod
    def summary(cls, company):
        experiences = cls.published_for(company)
        total = experiences.count()

        if not total:
            return {'has_experiences': False, 'count': 0}

        difficulty_counts = dict(
            experiences.values_list('difficulty')
            .annotate(n=Count('id'))
            .values_list('difficulty', 'n')
        )

        return {
            'has_experiences': True,
            'count': total,
            'positive_pct': round(
                experiences.filter(was_experience_positive=True).count()
                / total * 100, 1,
            ),
            'offer_pct': round(
                experiences.filter(
                    outcome=InterviewExperience.Outcome.OFFER,
                ).count() / total * 100, 1,
            ),
            'avg_rounds': round(
                experiences.aggregate(n=Avg('rounds'))['n'] or 0, 1,
            ),
            'difficulty_breakdown': difficulty_counts,
        }

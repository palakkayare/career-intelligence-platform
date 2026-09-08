"""
apps/career_intel/salary_services.py

Salary submission plus privacy-preserving aggregation.

The single most important rule in this module: no endpoint may ever return an
individual submission row. Everything that leaves get_insights() is a summary
statistic computed over at least K submissions.
"""

import logging
from datetime import datetime

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import ValidationError

from . import salary_algorithm
from .models import SalarySubmission, TargetRole

logger = logging.getLogger(__name__)


class SalaryService:
    """Salary submission and privacy-preserving aggregation."""

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def submit(cls, user, data: dict) -> SalarySubmission:
        """
        Create a salary submission.

        Validates that:
          - the salary falls inside a sane range
          - the same user has not already submitted for this role + year
        """
        # --- Validate the salary range ---
        salary = data.get('salary_inr') or 0

        if salary < settings.SALARY_MIN_INR:
            raise ValidationError({
                'salary_inr': (
                    f'Salary is too low (the minimum is '
                    f'₹{settings.SALARY_MIN_INR / 100000:.1f}L per year).'
                ),
            })

        if salary > settings.SALARY_MAX_INR:
            raise ValidationError({
                'salary_inr': (
                    f'Salary is too high (the maximum is '
                    f'₹{settings.SALARY_MAX_INR / 10000000:.1f}Cr per year).'
                ),
            })

        # --- Prevent a duplicate entry from the same user for the same year ---
        if user:
            existing = SalarySubmission.objects.filter(
                user=user,
                effective_year=data['effective_year'],
                role_title__iexact=data['role_title'],
            ).first()

            if existing:
                raise ValidationError({
                    'detail': (
                        'You have already submitted a salary for this role and year. '
                        'Delete the earlier submission if you want to replace it.'
                    ),
                })

        # --- Auto-link to a TargetRole when the title matches the taxonomy ---
        if not data.get('target_role') and data.get('role_title'):
            target_role = TargetRole.objects.filter(
                name__iexact=data['role_title'],
            ).first()
            if target_role:
                data['target_role'] = target_role

        submission = SalarySubmission.objects.create(user=user, **data)

        logger.info(
            "Salary submission created: id=%s role=%s city=%s year=%s",
            submission.id,
            submission.role_title,
            submission.location_city,
            submission.effective_year,
        )
        return submission

    # ------------------------------------------------------------------
    # Aggregated insights
    # ------------------------------------------------------------------
    @classmethod
    def get_insights(cls, filters: dict) -> dict:
        """
        Return aggregated salary insights, guarded by K-anonymity.

        Supported filter keys:
          - role_title (str)
          - target_role_id (int)
          - location_city (str)
          - company_size_bucket (str)
          - experience_years_bucket (str)
          - industry_id (int)
          - effective_year (int) -- optional, defaults to the last 2 years

        Deliberately unsupported: company name, exact age, exact experience,
        department. Those combinations narrow the result set down to single
        individuals (see the privacy notes in the feature doc).
        """
        # Flagged submissions never take part in any aggregate.
        qs = SalarySubmission.objects.filter(is_flagged=False)

        # --- Apply only the filters that are safe for privacy ---
        if filters.get('role_title'):
            qs = qs.filter(role_title__iexact=filters['role_title'])

        if filters.get('target_role_id'):
            qs = qs.filter(target_role_id=filters['target_role_id'])

        if filters.get('location_city'):
            qs = qs.filter(location_city__iexact=filters['location_city'])

        if filters.get('company_size_bucket'):
            qs = qs.filter(company_size_bucket=filters['company_size_bucket'])

        if filters.get('experience_years_bucket'):
            qs = qs.filter(experience_years_bucket=filters['experience_years_bucket'])

        if filters.get('industry_id'):
            qs = qs.filter(industry_id=filters['industry_id'])

        # Default to the last 2 years so inflation and market shifts do not
        # distort the picture.
        if filters.get('effective_year'):
            qs = qs.filter(effective_year=filters['effective_year'])
        else:
            current_year = datetime.now().year
            qs = qs.filter(effective_year__gte=current_year - 2)

        # --- K-anonymity check ---
        k = settings.SALARY_K_ANONYMITY
        count = qs.count()

        if count < k:
            return {
                'has_data': False,
                'count': count,
                'k_threshold': k,
                'message': (
                    f'Not enough data ({count} submissions found, at least {k} are '
                    f'needed to protect privacy). Try broadening your filters.'
                ),
            }

        # --- Compute the aggregates ---
        salaries = list(qs.values_list('salary_inr', flat=True))

        # Remove values outside the sane market range before computing statistics.
        salaries = salary_algorithm.trim_outliers_simple(
            salaries,
            min_inr=settings.SALARY_MIN_INR,
            max_inr=settings.SALARY_MAX_INR,
        )

        # Re-check K: trimming may have pushed the sample below the threshold.
        if len(salaries) < k:
            return {
                'has_data': False,
                'count': len(salaries),
                'k_threshold': k,
                'message': 'Not enough valid data left after filtering out invalid values.',
            }

        aggregates = salary_algorithm.calculate_aggregates(salaries)

        # --- Build the response: summary numbers only, no raw rows ---
        return {
            'has_data': True,
            'filters_applied': {key: value for key, value in filters.items() if value},
            'sample_size': aggregates['count'],
            'k_threshold': k,
            'salary_range_inr': {
                'min': aggregates['min'],
                'p10': aggregates['p10'],
                'p25': aggregates['p25'],
                'median': aggregates['median'],
                'p75': aggregates['p75'],
                'p90': aggregates['p90'],
                'max': aggregates['max'],
                'mean': aggregates['mean'],
            },
            'salary_range_lpa': {
                'min': salary_algorithm.format_inr_lpa(aggregates['min']),
                'p25': salary_algorithm.format_inr_lpa(aggregates['p25']),
                'median': salary_algorithm.format_inr_lpa(aggregates['median']),
                'p75': salary_algorithm.format_inr_lpa(aggregates['p75']),
                'max': salary_algorithm.format_inr_lpa(aggregates['max']),
            },
            'verified_share': cls._compute_verified_share(qs),
            'message': (
                f"Based on {aggregates['count']} submissions. "
                f"Median: ₹{aggregates['median'] / 100000:.1f} LPA."
            ),
        }

    # ------------------------------------------------------------------
    # Personal comparison
    # ------------------------------------------------------------------
    @classmethod
    def get_user_comparison(cls, user) -> dict:
        """
        Compare the user's most recent submission against the market.

        If the exact filter set has too little data, the filters are widened
        (experience is dropped first) rather than failing outright.
        """
        submission = (
            SalarySubmission.objects
            .filter(user=user, is_flagged=False)
            .order_by('-effective_year', '-submitted_at')
            .first()
        )

        if not submission:
            return {
                'has_submission': False,
                'message': 'Submit your own salary first at /salary/submit/.',
            }

        # First attempt: role + city + experience bucket.
        filters = {
            'role_title': submission.role_title,
            'location_city': submission.location_city,
            'experience_years_bucket': submission.experience_years_bucket,
        }
        insights = cls.get_insights(filters)

        # Graceful degradation: retry with role + city only.
        if not insights['has_data']:
            filters.pop('experience_years_bucket', None)
            insights = cls.get_insights(filters)

        if not insights['has_data']:
            return {
                'has_submission': True,
                'has_market_data': False,
                'message': (
                    'There is not enough market data for your role yet. '
                    'Invite others to contribute so these insights improve.'
                ),
                'your_submission': {
                    'salary_lpa': salary_algorithm.format_inr_lpa(float(submission.salary_inr)),
                },
            }

        # --- Work out where this salary sits in the market ---
        position = salary_algorithm.determine_market_position(
            submission.salary_inr,
            insights['salary_range_inr'],
        )
        message = salary_algorithm.market_position_message(
            position,
            submission.salary_inr,
            insights['salary_range_inr'],
        )

        return {
            'has_submission': True,
            'has_market_data': True,
            'your_submission': {
                'role_title': submission.role_title,
                'location_city': submission.location_city,
                'salary_lpa': salary_algorithm.format_inr_lpa(float(submission.salary_inr)),
                'experience': submission.experience_years_bucket,
                'effective_year': submission.effective_year,
            },
            'market_position': position,
            'market_insights': insights,
            'message': message,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_verified_share(qs) -> float:
        """Percentage of submissions in this queryset that are verified."""
        total = qs.count()
        if total == 0:
            return 0.0
        verified = qs.filter(is_verified=True).count()
        return round(verified / total * 100, 1)
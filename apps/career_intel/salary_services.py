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


def _publish(value, band):
    """Round a figure to the response's publication band."""
    return salary_algorithm.round_for_publication(value, band=band)


def hash_ip(ip_address):
    """
    One-way, keyed hash of an IP address.

    HMAC rather than a bare digest. There are only about four billion IPv4
    addresses, so sha256(ip) is reversible by anyone willing to spend an
    afternoon building a table - the pepper is the whole protection.

    Returns '' for a missing address or an unconfigured pepper, so a
    misconfiguration degrades to "no rate limiting" rather than to "a
    reversible hash of everyone's IP sitting in the database".
    """
    import hashlib
    import hmac

    from django.conf import settings

    pepper = getattr(settings, "SALARY_IP_PEPPER", "")
    if not ip_address or not pepper:
        return ""

    return hmac.new(
        pepper.encode(),
        str(ip_address).encode(),
        hashlib.sha256,
    ).hexdigest()


def client_ip(request):
    """
    The submitter's address, as delivered by our own proxies; see
    apps/core/client_ip.py.

    This used to read the left-most X-Forwarded-For entry, which the client
    types. A different made-up address per request walked straight past the
    per-IP submission limit, and with it the protection of the aggregates.
    """
    if request is None:
        return None

    from apps.core.client_ip import client_ip as trusted_client_ip

    return trusted_client_ip(request)


class SalaryService:
    """Salary submission and privacy-preserving aggregation."""

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def submit(cls, user, data: dict, ip_address=None) -> SalarySubmission:
        """
        Create a salary submission.

        Validates that:
          - the salary falls inside a sane range
          - the same user has not already submitted for this role + year
          - the submitting device is inside its rate limit

        `ip_address` is hashed before it is stored; the raw address never
        reaches the database.
        """
        # --- Validate the salary range ---
        salary = data.get("salary_inr") or 0

        if salary < settings.SALARY_MIN_INR:
            raise ValidationError(
                {
                    "salary_inr": (
                        f"Salary is too low (the minimum is "
                        f"₹{settings.SALARY_MIN_INR / 100000:.1f}L per year)."
                    ),
                }
            )

        if salary > settings.SALARY_MAX_INR:
            raise ValidationError(
                {
                    "salary_inr": (
                        f"Salary is too high (the maximum is "
                        f"₹{settings.SALARY_MAX_INR / 10000000:.1f}Cr per year)."
                    ),
                }
            )

        # --- Prevent a duplicate entry from the same user for the same year ---
        if user:
            existing = SalarySubmission.objects.filter(
                user=user,
                effective_year=data["effective_year"],
                role_title__iexact=data["role_title"],
            ).first()

            if existing:
                raise ValidationError(
                    {
                        "detail": (
                            "You have already submitted a salary for this role and year. "
                            "Delete the earlier submission if you want to replace it."
                        ),
                    }
                )

        # --- Per-device rate limit ---
        ip_hash = hash_ip(ip_address)
        if ip_hash:
            cls._check_device_limit(ip_hash)

        # --- Auto-link to a TargetRole when the title matches the taxonomy ---
        if not data.get("target_role") and data.get("role_title"):
            target_role = TargetRole.objects.filter(
                name__iexact=data["role_title"],
            ).first()
            if target_role:
                data["target_role"] = target_role

        submission = SalarySubmission.objects.create(
            user=user,
            submitter_ip_hash=ip_hash,
            **data,
        )

        logger.info(
            "Salary submission created: id=%s role=%s city=%s year=%s",
            submission.id,
            submission.role_title,
            submission.location_city,
            submission.effective_year,
        )
        return submission

    @staticmethod
    def _check_device_limit(ip_hash):
        """
        Refuse a device that has already submitted its share.

        Separate from the per-user check: one person with several accounts
        still only has one machine, and the blueprint asks for the limit to
        be per device rather than per login.
        """
        from datetime import timedelta

        from django.utils import timezone

        window = timezone.now() - timedelta(
            hours=settings.SALARY_IP_WINDOW_HOURS,
        )
        recent = SalarySubmission.objects.filter(
            submitter_ip_hash=ip_hash,
            submitted_at__gte=window,
        ).count()

        if recent >= settings.SALARY_MAX_SUBMISSIONS_PER_IP:
            raise ValidationError(
                {
                    "detail": (
                        f"This device has submitted "
                        f"{settings.SALARY_MAX_SUBMISSIONS_PER_IP} salaries in the "
                        f"last {settings.SALARY_IP_WINDOW_HOURS} hours. "
                        f"Try again later."
                    ),
                }
            )

    # ------------------------------------------------------------------
    # Aggregated insights
    # ------------------------------------------------------------------
    @classmethod
    def _apply_filters(cls, filters):
        """
        The filtered submission set.

        Extracted so the published aggregate and the server-side comparison
        cannot drift apart - two copies of a privacy filter is one copy too
        many.
        """
        # Flagged submissions never take part in any aggregate.
        qs = SalarySubmission.objects.filter(is_flagged=False)

        if filters.get("role_title"):
            qs = qs.filter(role_title__iexact=filters["role_title"])

        if filters.get("target_role_id"):
            qs = qs.filter(target_role_id=filters["target_role_id"])

        if filters.get("location_city"):
            qs = qs.filter(location_city__iexact=filters["location_city"])

        if filters.get("company_size_bucket"):
            qs = qs.filter(company_size_bucket=filters["company_size_bucket"])

        if filters.get("experience_years_bucket"):
            qs = qs.filter(
                experience_years_bucket=filters["experience_years_bucket"],
            )

        if filters.get("industry_id"):
            qs = qs.filter(industry_id=filters["industry_id"])

        # Default to the last 2 years so inflation and market shifts do not
        # distort the picture.
        if filters.get("effective_year"):
            qs = qs.filter(effective_year=filters["effective_year"])
        else:
            current_year = datetime.now().year
            qs = qs.filter(effective_year__gte=current_year - 2)

        return qs

    @staticmethod
    def _not_enough_data(k):
        """
        The only answer given below the K threshold.

        One shape for every suppressed query, carrying no count: two queries
        that both fall short must be indistinguishable, or the difference
        between them leaks the very thing the threshold protects.
        """
        return {
            "has_data": False,
            "k_threshold": k,
            "message": (
                f"Not enough data to publish a figure. At least {k} submissions are "
                "needed to protect privacy. Try broadening your filters."
            ),
        }

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
        qs = cls._apply_filters(filters)

        # --- K-anonymity check ---
        k = settings.SALARY_K_ANONYMITY
        count = qs.count()

        if count < k:
            # Deliberately no count. Below the threshold the exact size of the
            # group is the most identifying thing left: 1 rather than 0 says a
            # specific person submitted, and narrowing the filters repeatedly
            # maps the population one query at a time. k_threshold is fine to
            # publish - the rule is public and says nothing about who is in it.
            return cls._not_enough_data(k)

        # --- Compute the aggregates ---
        salaries = list(qs.values_list("salary_inr", flat=True))

        # Remove values outside the sane market range before computing statistics.
        salaries = salary_algorithm.trim_outliers_simple(
            salaries,
            min_inr=settings.SALARY_MIN_INR,
            max_inr=settings.SALARY_MAX_INR,
        )

        # Re-check K: trimming may have pushed the sample below the threshold.
        # Same response as above, for the same reason - and deliberately
        # indistinguishable from it, so the reply does not reveal that a
        # different number of rows matched before trimming.
        if len(salaries) < k:
            return cls._not_enough_data(k)

        aggregates = salary_algorithm.calculate_aggregates(salaries)

        # Published percentiles are computed separately from the internal
        # ones. Standard rank interpolation lands exactly on a person
        # whenever the index is whole - at n=5 that is p25, the median and
        # p75 - so the published set uses a method that always sits between
        # two submissions. See publication_percentile.
        published = {
            name: salary_algorithm.publication_percentile(salaries, p)
            for name, p in (("p25", 25), ("median", 50), ("p75", 75))
        }
        published["mean"] = aggregates["mean"]

        # One band for the whole response, derived from the median. Rounding
        # each figure to its own band would put p25 on a finer grid than the
        # median, which leaks the shape of the distribution back out.
        band = salary_algorithm.choose_band(published["median"])

        # --- Build the response: summary numbers only, no raw rows ---
        return {
            "has_data": True,
            "filters_applied": {key: value for key, value in filters.items() if value},
            "sample_size": aggregates["count"],
            "k_threshold": k,
            # min and max are gone, and the rest are rounded.
            #
            # A published min or max is one person's exact salary - not an
            # aggregate in any protective sense. Two queries differing by a
            # single filter recover that person's figure directly.
            #
            # The percentiles that remain are rounded because at these
            # sample sizes they also land on individuals: with five
            # submissions, p25 is values[1] and the median is values[2].
            # See round_for_publication.
            "salary_range_inr": {
                "p25": _publish(published["p25"], band),
                "median": _publish(published["median"], band),
                "p75": _publish(published["p75"], band),
                "mean": _publish(published["mean"], band),
            },
            "salary_range_lpa": {
                "p25": salary_algorithm.format_inr_lpa(_publish(published["p25"], band)),
                "median": salary_algorithm.format_inr_lpa(_publish(published["median"], band)),
                "p75": salary_algorithm.format_inr_lpa(_publish(published["p75"], band)),
            },
            "verified_share": cls._compute_verified_share(qs),
            "message": (
                f"Based on {aggregates['count']} submissions. "
                f"Median: ₹{_publish(published['median'], band) / 100000:.1f} LPA."
            ),
        }

    @classmethod
    def _raw_percentiles(cls, filters):
        """
        Unrounded percentiles, for server-side comparison only.

        Never returned to a client. The published figures are rounded and
        drop min and max; these are the full set, used where the output is
        a category rather than a number.
        """
        qs = cls._apply_filters(filters)
        salaries = list(qs.values_list("salary_inr", flat=True))
        trimmed = salary_algorithm.trim_outliers_simple(salaries)

        return salary_algorithm.calculate_aggregates(trimmed) or {}

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
            SalarySubmission.objects.filter(user=user, is_flagged=False)
            .order_by("-effective_year", "-submitted_at")
            .first()
        )

        if not submission:
            return {
                "has_submission": False,
                "message": "Submit your own salary first at /salary/submit/.",
            }

        # First attempt: role + city + experience bucket.
        filters = {
            "role_title": submission.role_title,
            "location_city": submission.location_city,
            "experience_years_bucket": submission.experience_years_bucket,
        }
        insights = cls.get_insights(filters)

        # Graceful degradation: retry with role + city only.
        if not insights["has_data"]:
            filters.pop("experience_years_bucket", None)
            insights = cls.get_insights(filters)

        if not insights["has_data"]:
            return {
                "has_submission": True,
                "has_market_data": False,
                "message": (
                    "There is not enough market data for your role yet. "
                    "Invite others to contribute so these insights improve."
                ),
                "your_submission": {
                    "salary_lpa": salary_algorithm.format_inr_lpa(float(submission.salary_inr)),
                },
            }

        # --- Work out where this salary sits in the market ---
        #
        # Computed against the unrounded percentiles rather than the
        # published ones. The comparison happens here and only a category
        # comes back, so it can use the full distribution without any of it
        # reaching the response - and a band-rounded p75 would misplace
        # anyone sitting close to it.
        raw = cls._raw_percentiles(filters)

        position = salary_algorithm.determine_market_position(
            submission.salary_inr,
            raw,
        )
        message = salary_algorithm.market_position_message(
            position,
            submission.salary_inr,
            raw,
        )

        return {
            "has_submission": True,
            "has_market_data": True,
            "your_submission": {
                "role_title": submission.role_title,
                "location_city": submission.location_city,
                "salary_lpa": salary_algorithm.format_inr_lpa(float(submission.salary_inr)),
                "experience": submission.experience_years_bucket,
                "effective_year": submission.effective_year,
            },
            "market_position": position,
            "market_insights": insights,
            "message": message,
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

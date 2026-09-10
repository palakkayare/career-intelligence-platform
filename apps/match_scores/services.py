"""
MatchScoreService — orchestrates computation + persistence.
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from . import algorithm
from .models import MatchScore

logger = logging.getLogger(__name__)


class MatchScoreService:
    """Compute and store match scores."""

    @classmethod
    @transaction.atomic
    def compute_and_save(cls, seeker, job):
        """Compute a fresh match score and save it to the DB."""
        # Gather seeker data
        seeker_skill_ids = set(seeker.skills.values_list("id", flat=True))
        seeker_years = seeker.years_of_experience or 0
        seeker_location = seeker.location or ""

        # Gather job data
        required_ids = set(job.required_skills.values_list("id", flat=True))
        nice_ids = set(job.nice_to_have_skills.values_list("id", flat=True))

        # Compute each component
        skills = algorithm.compute_skills_score(
            seeker_skill_ids,
            required_ids,
            nice_ids,
        )
        experience = algorithm.compute_experience_score(
            seeker_years,
            job.min_experience_years,
            job.max_experience_years,
        )
        location = algorithm.compute_location_score(
            seeker_location,
            job.location,
            job.work_arrangement,
        )
        salary = algorithm.compute_salary_score(
            seeker_years,
            float(job.salary_min) if job.salary_min else 0,
            float(job.salary_max) if job.salary_max else 0,
        )

        overall = algorithm.compute_overall_score(
            skills["score"],
            experience["score"],
            location["score"],
            salary["score"],
        )

        # Persist (upsert — one row per seeker-job pair)
        match, _ = MatchScore.objects.update_or_create(
            seeker=seeker,
            job=job,
            defaults={
                "overall_score": round(overall, 2),
                "skills_score": skills["score"],
                "experience_score": experience["score"],
                "location_score": location["score"],
                "salary_score": salary["score"],
                "breakdown": {
                    "skills": skills,
                    "experience": experience,
                    "location": location,
                    "salary": salary,
                },
            },
        )

        return match

    @classmethod
    def get_or_compute(cls, seeker, job, max_age_hours=6):
        """
        Return cached score if fresh, else recompute.
        """
        existing = MatchScore.objects.filter(seeker=seeker, job=job).first()

        if existing:
            age = timezone.now() - existing.computed_at
            if age < timedelta(hours=max_age_hours):
                return existing

        # Stale or missing → recompute
        return cls.compute_and_save(seeker, job)


class RecommendationService:
    """Get top-N recommendations for seekers and recruiters."""

    @classmethod
    def top_jobs_for_seeker(cls, seeker, limit=10, min_score=50):
        """Return jobs with the highest match score for this seeker."""
        scores = (
            MatchScore.objects.filter(
                seeker=seeker,
                overall_score__gte=min_score,
                job__status="active",
                job__is_deleted=False,
            )
            .select_related("job", "job__company", "job__category")
            .prefetch_related("job__required_skills")
            .order_by("-overall_score")[:limit]
        )
        return list(scores)

    @classmethod
    def top_candidates_for_job(cls, job, limit=20, min_score=50):
        """Return seekers with the highest match score for this job."""
        scores = (
            MatchScore.objects.filter(
                job=job,
                overall_score__gte=min_score,
                seeker__is_deleted=False,
                seeker__user__is_active=True,
            )
            .select_related("seeker__user")
            .prefetch_related("seeker__seeker_skills__skill")
            .order_by("-overall_score")[:limit]
        )
        return list(scores)

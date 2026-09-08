"""
Redis caching for match scores.
"""
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_SCORE = 3600      # 1 hour
CACHE_TTL_TOP_LIST = 1800   # 30 min


class MatchCache:
    """Lightweight wrapper around Django cache for match data."""

    @staticmethod
    def _key_score(seeker_id, job_id):
        return f'match:s{seeker_id}:j{job_id}'

    @staticmethod
    def _key_top_jobs(seeker_id):
        return f'match:top_jobs:s{seeker_id}'

    @staticmethod
    def _key_top_candidates(job_id):
        return f'match:top_candidates:j{job_id}'

    @classmethod
    def get_score(cls, seeker_id, job_id):
        """Get cached score (returns dict or None)."""
        cached = cache.get(cls._key_score(seeker_id, job_id))
        if cached:
            try:
                return json.loads(cached)
            except json.JSONDecodeError:
                return None
        return None

    @classmethod
    def set_score(cls, seeker_id, job_id, data):
        """Cache a score for 1 hour."""
        cache.set(
            cls._key_score(seeker_id, job_id),
            json.dumps(data, default=str),
            CACHE_TTL_SCORE,
        )

    @classmethod
    def get_top_jobs(cls, seeker_id):
        cached = cache.get(cls._key_top_jobs(seeker_id))
        return json.loads(cached) if cached else None

    @classmethod
    def set_top_jobs(cls, seeker_id, jobs_list):
        cache.set(
            cls._key_top_jobs(seeker_id),
            json.dumps(jobs_list, default=str),
            CACHE_TTL_TOP_LIST,
        )

    @classmethod
    def get_top_candidates(cls, job_id):
        cached = cache.get(cls._key_top_candidates(job_id))
        return json.loads(cached) if cached else None

    @classmethod
    def set_top_candidates(cls, job_id, candidates_list):
        cache.set(
            cls._key_top_candidates(job_id),
            json.dumps(candidates_list, default=str),
            CACHE_TTL_TOP_LIST,
        )

    @classmethod
    def invalidate_seeker(cls, seeker_id):
        """When a seeker's profile changes, drop their cached top-jobs list."""
        cache.delete(cls._key_top_jobs(seeker_id))
        # Note: per-(seeker, job) keys auto-expire via TTL

    @classmethod
    def invalidate_job(cls, job_id):
        """When a job changes, drop its cached candidate list."""
        cache.delete(cls._key_top_candidates(job_id))
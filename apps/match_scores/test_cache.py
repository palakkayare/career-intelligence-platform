"""
Match score caching.

A thin wrapper over Django's cache, but worth testing: a silent failure here
means either stale match scores shown to users, or a cache that never hits
and quietly puts the full recomputation load back on the database.
"""

import pytest
from django.core.cache import cache

from apps.match_scores.cache import CACHE_TTL_SCORE, CACHE_TTL_TOP_LIST, MatchCache

pytestmark = pytest.mark.django_db

SCORE = {"overall_score": 87.5, "breakdown": {"skills": 90}}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------
# Round trips
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_a_score_survives_a_round_trip():
    """Regression: match_scores/cache.py was at 0% coverage."""
    MatchCache.set_score(1, 2, SCORE)

    assert MatchCache.get_score(1, 2) == SCORE


def test_a_missing_score_returns_none():
    assert MatchCache.get_score(999, 999) is None


def test_top_jobs_survive_a_round_trip():
    jobs = [{"job_id": 1, "score": 90}, {"job_id": 2, "score": 80}]
    MatchCache.set_top_jobs(7, jobs)

    assert MatchCache.get_top_jobs(7) == jobs


def test_top_candidates_survive_a_round_trip():
    candidates = [{"seeker_id": 3, "score": 75}]
    MatchCache.set_top_candidates(42, candidates)

    assert MatchCache.get_top_candidates(42) == candidates


def test_missing_lists_return_none():
    assert MatchCache.get_top_jobs(999) is None
    assert MatchCache.get_top_candidates(999) is None


# --------------------------------------------------------------------------
# Key isolation
# --------------------------------------------------------------------------


def test_scores_are_keyed_per_seeker_and_job():
    """One seeker's score must never be served to another."""
    MatchCache.set_score(1, 2, {"overall_score": 90})
    MatchCache.set_score(1, 3, {"overall_score": 40})
    MatchCache.set_score(2, 2, {"overall_score": 10})

    assert MatchCache.get_score(1, 2)["overall_score"] == 90
    assert MatchCache.get_score(1, 3)["overall_score"] == 40
    assert MatchCache.get_score(2, 2)["overall_score"] == 10


def test_seeker_and_job_ids_cannot_collide():
    """s1:j23 and s12:j3 must be different keys, not the same string."""
    assert MatchCache._key_score(1, 23) != MatchCache._key_score(12, 3)


def test_the_three_key_families_are_distinct():
    keys = {
        MatchCache._key_score(1, 1),
        MatchCache._key_top_jobs(1),
        MatchCache._key_top_candidates(1),
    }

    assert len(keys) == 3


# --------------------------------------------------------------------------
# Invalidation
# --------------------------------------------------------------------------


def test_invalidating_a_seeker_drops_their_job_list():
    MatchCache.set_top_jobs(5, [{"job_id": 1}])

    MatchCache.invalidate_seeker(5)

    assert MatchCache.get_top_jobs(5) is None


def test_invalidating_a_seeker_leaves_other_seekers_alone():
    MatchCache.set_top_jobs(5, [{"job_id": 1}])
    MatchCache.set_top_jobs(6, [{"job_id": 2}])

    MatchCache.invalidate_seeker(5)

    assert MatchCache.get_top_jobs(6) is not None


def test_invalidating_a_job_drops_its_candidate_list():
    MatchCache.set_top_candidates(9, [{"seeker_id": 1}])

    MatchCache.invalidate_job(9)

    assert MatchCache.get_top_candidates(9) is None


def test_invalidation_leaves_pair_scores_to_expire_on_their_own():
    """
    Deliberate: there is no way to enumerate per-pair keys, so they are left
    to their one-hour TTL rather than scanned for. The code comment says so;
    this pins the behaviour.
    """
    MatchCache.set_score(5, 1, SCORE)
    MatchCache.set_top_jobs(5, [{"job_id": 1}])

    MatchCache.invalidate_seeker(5)

    assert MatchCache.get_top_jobs(5) is None
    assert MatchCache.get_score(5, 1) == SCORE


# --------------------------------------------------------------------------
# Robustness
# --------------------------------------------------------------------------


def test_corrupt_cached_data_is_treated_as_a_miss():
    """A bad entry should cause a recompute, not a 500."""
    cache.set(MatchCache._key_score(1, 2), "not json at all", 60)

    assert MatchCache.get_score(1, 2) is None


def test_values_that_json_cannot_serialise_are_coerced():
    """Decimals and datetimes come straight off the model."""
    from datetime import datetime
    from decimal import Decimal

    MatchCache.set_score(
        1,
        2,
        {
            "score": Decimal("87.50"),
            "computed_at": datetime(2026, 1, 1, 12, 0),
        },
    )

    cached = MatchCache.get_score(1, 2)

    assert cached["score"] == "87.50"
    assert "2026-01-01" in cached["computed_at"]


def test_ttls_are_set_as_documented():
    assert CACHE_TTL_SCORE == 3600
    assert CACHE_TTL_TOP_LIST == 1800
    assert (
        CACHE_TTL_TOP_LIST < CACHE_TTL_SCORE
    ), "list views go stale faster than individual pair scores"

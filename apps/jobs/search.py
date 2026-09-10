"""
Job search query builder.
Combines full-text search with filters and sorting.
"""

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, OuterRef, Subquery

from .models import Job


class JobSearchService:
    """Encapsulates search query construction."""

    @classmethod
    def build_queryset(cls, query_text="", sort="relevance", seeker=None):
        """
        Returns base queryset with full-text search + ranking applied.
        Filtering is done separately by FilterSet.

        `seeker` is only needed for match_score sorting, which is per-person
        by definition. Everything else works the same for anyone.
        """
        qs = (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                is_deleted=False,
            )
            .select_related("company", "company__industry", "category")
            .prefetch_related("required_skills")
        )

        # Full-text search
        if query_text and query_text.strip():
            search_query = SearchQuery(
                query_text.strip(),
                search_type="websearch",  # Supports "exact", -exclude, OR
            )
            qs = qs.annotate(rank=SearchRank("search_vector", search_query)).filter(
                search_vector=search_query
            )

        # Match score lives on its own table and is per-seeker, so it has to
        # be pulled in as an annotation before sorting can use it.
        if sort == "match_score" and seeker is not None:
            from apps.match_scores.models import MatchScore

            qs = qs.annotate(
                seeker_match_score=Subquery(
                    MatchScore.objects.filter(seeker=seeker, job=OuterRef("pk")).values(
                        "overall_score"
                    )[:1]
                ),
            )

        # Apply sort
        qs = cls._apply_sort(qs, sort, has_query=bool(query_text))

        return qs

    @staticmethod
    def _apply_sort(qs, sort, has_query):
        """
        Sort options:
        - relevance:   rank desc (only meaningful with query)
        - date:        latest first
        - salary:      highest max first
        - match_score: best fit first (seekers only)
        - oldest:      oldest first
        """
        if sort == "relevance":
            if has_query:
                return qs.order_by("-rank", "-activated_at")
            return qs.order_by("-activated_at")  # No query → date sort

        if sort == "date":
            return qs.order_by("-activated_at")

        if sort == "salary":
            return qs.order_by(F("salary_max").desc(nulls_last=True), "-activated_at")

        if sort == "match_score":
            # The annotation is only added for a seeker, so a recruiter or an
            # unscored request falls back rather than ordering on a field
            # that is not there.
            if "seeker_match_score" not in qs.query.annotations:
                return qs.order_by("-activated_at")

            # Scores are precomputed every six hours, so a job posted since
            # the last run has none yet. Those belong at the end, which is
            # not where a NULL would put them by default.
            return qs.order_by(
                F("seeker_match_score").desc(nulls_last=True),
                "-activated_at",
            )

        if sort == "oldest":
            return qs.order_by("activated_at")

        return qs.order_by("-activated_at")  # Default

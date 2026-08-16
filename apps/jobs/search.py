"""
Job search query builder.
Combines full-text search with filters and sorting.
"""
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F

from .models import Job


class JobSearchService:
    """Encapsulates search query construction."""

    @classmethod
    def build_queryset(cls, query_text=None, sort='relevance'):
        """
        Returns base queryset with full-text search + ranking applied.
        Filtering is done separately by FilterSet.
        """
        qs = (
            Job.objects.filter(
                status=Job.Status.ACTIVE,
                is_deleted=False,
            )
            .select_related('company', 'company__industry', 'category')
            .prefetch_related('required_skills')
        )

        # Full-text search
        if query_text and query_text.strip():
            search_query = SearchQuery(
                query_text.strip(),
                search_type='websearch',  # Supports "exact", -exclude, OR
            )
            qs = (
                qs.annotate(rank=SearchRank('search_vector', search_query))
                .filter(search_vector=search_query)
            )

        # Apply sort
        qs = cls._apply_sort(qs, sort, has_query=bool(query_text))

        return qs

    @staticmethod
    def _apply_sort(qs, sort, has_query):
        """
        Sort options:
        - relevance: rank desc (only meaningful with query)
        - date: latest first
        - salary: highest max first
        - oldest: oldest first
        """
        if sort == 'relevance':
            if has_query:
                return qs.order_by('-rank', '-activated_at')
            return qs.order_by('-activated_at')  # No query → date sort

        if sort == 'date':
            return qs.order_by('-activated_at')

        if sort == 'salary':
            return qs.order_by(F('salary_max').desc(nulls_last=True), '-activated_at')

        if sort == 'oldest':
            return qs.order_by('activated_at')

        return qs.order_by('-activated_at')  # Default
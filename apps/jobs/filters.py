"""
django-filter FilterSet for job search.
"""
import django_filters

from .models import Job


class JobFilterSet(django_filters.FilterSet):
    # Location: case-insensitive contains
    location = django_filters.CharFilter(
        field_name='location',
        lookup_expr='icontains',
    )

    # Salary range (works with both salary_min and salary_max columns)
    salary_min = django_filters.NumberFilter(
        method='filter_salary_min',
        help_text='Show jobs with max salary >= this value',
    )
    salary_max = django_filters.NumberFilter(
        method='filter_salary_max',
        help_text='Show jobs with min salary <= this value',
    )

    # Multi-select: ?employment_type=full_time,contract
    employment_type = django_filters.BaseInFilter(field_name='employment_type')
    work_arrangement = django_filters.BaseInFilter(field_name='work_arrangement')

    # Experience: show jobs requiring <= this years of exp
    experience = django_filters.NumberFilter(method='filter_experience')

    # Skills (multi-select via comma): ?skills=1,5,12
   # Skills (multi-select via comma): ?skills=1,5,12
    skills = django_filters.BaseInFilter(method='filter_skills')

    # Industry (via company)
    industry = django_filters.NumberFilter(
        field_name='company__industry__id',
    )

    # Category
    category = django_filters.NumberFilter(field_name='category__id')

    # Verified company only
    verified_company = django_filters.BooleanFilter(
        field_name='company__is_verified',
    )

    # Posted within N days
    posted_within_days = django_filters.NumberFilter(method='filter_posted_within')

    class Meta:
        model = Job
        fields = []  # All filters defined explicitly above

    def filter_salary_min(self, queryset, name, value):
        """User wants salary at least X. Match jobs whose salary_max >= X."""
        return queryset.filter(salary_max__gte=value) | queryset.filter(salary_min__gte=value)

    def filter_salary_max(self, queryset, name, value):
        """User wants salary at most X. Match jobs whose salary_min <= X."""
        return queryset.filter(salary_min__lte=value)

    def filter_experience(self, queryset, name, value):
        """Show jobs that accept user's experience level."""
        return queryset.filter(min_experience_years__lte=value)
    
    def filter_skills(self, queryset, name, value):
        """Match jobs requiring any of the given skill IDs (dedup results)."""
        return queryset.filter(required_skills__id__in=value).distinct()

    def filter_posted_within(self, queryset, name, value):
        """Show jobs posted within last N days."""
        from django.utils import timezone
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=int(value))
        return queryset.filter(activated_at__gte=cutoff)
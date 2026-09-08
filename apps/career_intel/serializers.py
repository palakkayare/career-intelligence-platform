from rest_framework import serializers

from apps.skills.serializers import SkillSerializer

from .models import (
    LearningProvider,
    LearningResource,
    ResourceSkill,
    SkillGapSnapshot,
    TargetRole,
    TargetRoleSkill,
    UserLearning,
    SalarySubmission,
    CareerPathNode, 
    CareerPathEdge
    
)
from datetime import datetime


class TargetRoleSkillSerializer(serializers.ModelSerializer):
    """One required skill of a role, with its importance metadata."""

    skill = SkillSerializer(read_only=True)

    class Meta:
        model = TargetRoleSkill
        fields = ('skill', 'importance', 'difficulty', 'rationale')
        read_only_fields = fields


class TargetRoleListSerializer(serializers.ModelSerializer):
    """Lightweight role payload for the browse/list screen."""

    skill_count = serializers.SerializerMethodField()

    class Meta:
        model = TargetRole
        fields = (
            'id', 'name', 'slug', 'category',
            'min_experience_years', 'typical_experience_years',
            'avg_salary_inr', 'skill_count',
        )
        read_only_fields = fields

    def get_skill_count(self, obj) -> int:
        return obj.target_role_skills.count()


class TargetRoleDetailSerializer(serializers.ModelSerializer):
    """Full role payload including every required skill."""

    skills = TargetRoleSkillSerializer(
        source='target_role_skills',
        many=True,
        read_only=True,
    )

    class Meta:
        model = TargetRole
        fields = (
            'id', 'name', 'slug', 'description', 'category',
            'min_experience_years', 'typical_experience_years',
            'avg_salary_inr', 'skills',
        )
        read_only_fields = fields


class AnalyzeGapInputSerializer(serializers.Serializer):
    """Request body for POST /api/v1/skill-gap/analyze/"""

    target_role_slug = serializers.SlugField()
    save_snapshot = serializers.BooleanField(default=False, required=False)
    label = serializers.CharField(
        max_length=100, required=False, allow_blank=True,
    )


class SnapshotSerializer(serializers.ModelSerializer):
    """Snapshot payload used by the latest-analysis and history endpoints."""

    target_role_name = serializers.CharField(
        source='target_role.name', read_only=True,
    )
    target_role_slug = serializers.SlugField(
        source='target_role.slug', read_only=True,
    )

    class Meta:
        model = SkillGapSnapshot
        fields = (
            'public_id',
            'target_role_name', 'target_role_slug',
            'gap_score', 'label',
            'total_required_skills', 'matched_count',
            'missing_critical_count', 'missing_important_count',
            'created_at',
        )
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Feature 13 - Learning Recommendations
# ---------------------------------------------------------------------------


class LearningProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningProvider
        fields = ('id', 'name', 'slug', 'logo_url', 'website', 'trust_score')
        read_only_fields = fields


class ResourceSkillSerializer(serializers.ModelSerializer):
    """One skill taught by a resource, with coverage metadata."""

    skill = SkillSerializer(read_only=True)

    class Meta:
        model = ResourceSkill
        fields = ('skill', 'is_primary', 'coverage')
        read_only_fields = fields


class LearningResourceListSerializer(serializers.ModelSerializer):
    """Compact resource payload for lists and recommendation cards."""

    provider = LearningProviderSerializer(read_only=True)
    skills_summary = serializers.SerializerMethodField()

    class Meta:
        model = LearningResource
        fields = (
            'id', 'title', 'url', 'kind', 'difficulty',
            'duration_hours', 'is_free', 'price_inr',
            'external_rating', 'quality_score',
            'provider', 'is_endorsed', 'enrollment_count',
            'skills_summary',
        )
        read_only_fields = fields

    def get_skills_summary(self, obj):
        """Skill names only - the list view does not need full objects."""
        return [rs.skill.name for rs in obj.resource_skills.all()]


class LearningResourceDetailSerializer(serializers.ModelSerializer):
    """Full resource payload, including the current user's progress on it."""

    provider = LearningProviderSerializer(read_only=True)
    skills = ResourceSkillSerializer(
        source='resource_skills', many=True, read_only=True,
    )
    user_status = serializers.SerializerMethodField()

    class Meta:
        model = LearningResource
        fields = (
            'id', 'title', 'description', 'url',
            'kind', 'difficulty',
            'duration_hours', 'is_free', 'price_inr',
            'external_rating', 'quality_score',
            'provider', 'is_endorsed', 'enrollment_count',
            'skills', 'user_status',
        )
        read_only_fields = fields

    def get_user_status(self, obj):
        """Return the requesting user's progress, or None if not started."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None

        learning = UserLearning.objects.filter(
            user=request.user, resource=obj,
        ).first()
        if not learning:
            return None

        return {
            'id': learning.id,
            'status': learning.status,
            'progress_pct': learning.progress_pct,
            'started_at': learning.started_at,
            'completed_at': learning.completed_at,
            'user_rating': learning.user_rating,
        }


class UserLearningSerializer(serializers.ModelSerializer):
    resource = LearningResourceListSerializer(read_only=True)

    class Meta:
        model = UserLearning
        fields = (
            'id', 'resource',
            'status', 'progress_pct',
            'started_at', 'completed_at',
            'user_rating', 'notes',
            'updated_at',
        )
        read_only_fields = ('id', 'started_at', 'completed_at', 'updated_at')


class StartLearningInputSerializer(serializers.Serializer):
    """Request body for POST /learning/me/start/"""

    resource_id = serializers.IntegerField()


class UpdateProgressSerializer(serializers.Serializer):
    """Request body for PATCH /learning/me/<id>/progress/"""

    progress_pct = serializers.IntegerField(min_value=0, max_value=100)
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=1000,
    )


class CompleteLearningSerializer(serializers.Serializer):
    """Request body for POST /learning/me/<id>/complete/"""

    user_rating = serializers.IntegerField(
        min_value=1, max_value=5, required=False,
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, max_length=1000,
    )


class RecommendationsInputSerializer(serializers.Serializer):
    """Optional target_role_slug to override the default (latest snapshot)."""

    target_role_slug = serializers.SlugField(required=False)
    
# =============================================================================
# STEP 5 -- Append this to: apps/career_intel/serializers.py
#
# Required imports at the top of serializers.py (add only what is missing):
#     from datetime import datetime
#     from rest_framework import serializers
#     from .models import SalarySubmission
# =============================================================================


class SalarySubmitSerializer(serializers.ModelSerializer):
    """Input payload for a new salary submission."""

    class Meta:
        model = SalarySubmission
        fields = (
            'role_title',
            'industry',
            'location_city',
            'company_size_bucket',
            'experience_years_bucket',
            'employment_type',
            'work_arrangement',
            'salary_inr',
            'bonus_inr',
            'has_equity',
            'effective_year',
        )

    def validate_role_title(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Role title is too short.")
        return value

    def validate_location_city(self, value):
        # Normalise casing so 'bangalore' and 'Bangalore' land in the same bucket.
        return value.strip().title()

    def validate_effective_year(self, value):
        current = datetime.now().year
        if value < current - 5 or value > current:
            raise serializers.ValidationError(
                f"Year must be between {current - 5} and {current}."
            )
        return value


class SalaryInsightsInputSerializer(serializers.Serializer):
    """
    Filters accepted by POST /salary/insights/.

    Only privacy-safe dimensions are listed here. Company name, exact age,
    exact experience and department are intentionally absent.
    """

    role_title = serializers.CharField(required=False, allow_blank=True)
    target_role_id = serializers.IntegerField(required=False)
    location_city = serializers.CharField(required=False, allow_blank=True)
    company_size_bucket = serializers.ChoiceField(
        choices=SalarySubmission.CompanySizeBucket.choices,
        required=False,
        allow_blank=True,
    )
    experience_years_bucket = serializers.ChoiceField(
        choices=SalarySubmission.ExperienceBucket.choices,
        required=False,
        allow_blank=True,
    )
    industry_id = serializers.IntegerField(required=False)
    effective_year = serializers.IntegerField(required=False)

    def validate_location_city(self, value):
        # Match the normalisation applied on submission.
        return value.strip().title()


class SalarySubmissionDisplaySerializer(serializers.ModelSerializer):
    """
    Used only when a user views their OWN submissions.

    This is the one place where a single row is returned, and it is scoped to
    the requesting user's own data.
    """

    salary_lpa = serializers.SerializerMethodField()

    class Meta:
        model = SalarySubmission
        fields = (
            'id',
            'role_title',
            'location_city',
            'company_size_bucket',
            'experience_years_bucket',
            'salary_inr',
            'salary_lpa',
            'bonus_inr',
            'has_equity',
            'effective_year',
            'submitted_at',
            'is_verified',
        )
        read_only_fields = ('id', 'salary_lpa', 'submitted_at', 'is_verified')

    def get_salary_lpa(self, obj):
        from .salary_algorithm import format_inr_lpa
        return format_inr_lpa(float(obj.salary_inr))
    
# =============================================================================
# STEP 5 -- Append this to: apps/career_intel/serializers.py
#
# Required imports at the top of serializers.py (add only what is missing):
#     from rest_framework import serializers
#     from .models import CareerPathNode, CareerPathEdge
# =============================================================================


class CareerPathNodeListSerializer(serializers.ModelSerializer):
    """Compact node representation for the browsable node list."""

    class Meta:
        model = CareerPathNode
        fields = (
            'slug',
            'name',
            'description',
            'level',
            'category',
            'typical_experience_years',
            'avg_salary_inr',
        )
        read_only_fields = fields


class CareerPathNodeDetailSerializer(serializers.ModelSerializer):
    """
    Node detail, plus how many transitions lead in and out.

    The two counts give the frontend a cheap way to show whether a role is a
    dead end or a hub, without pulling the whole graph.
    """

    incoming_count = serializers.SerializerMethodField()
    outgoing_count = serializers.SerializerMethodField()

    class Meta:
        model = CareerPathNode
        fields = (
            'slug',
            'name',
            'description',
            'level',
            'category',
            'typical_experience_years',
            'avg_salary_inr',
            'incoming_count',
            'outgoing_count',
        )
        read_only_fields = fields

    def get_incoming_count(self, obj):
        return obj.incoming_edges.filter(is_active=True).count()

    def get_outgoing_count(self, obj):
        return obj.outgoing_edges.filter(is_active=True).count()


class FindPathInputSerializer(serializers.Serializer):
    """Input for POST /career-path/find/."""

    from_slug = serializers.SlugField()
    to_slug = serializers.SlugField()
    max_paths = serializers.IntegerField(
        min_value=1,
        max_value=5,
        default=3,
        required=False,
    )
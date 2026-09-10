from rest_framework import serializers
from django.db import models, transaction
from apps.skills.models import Skill
from apps.skills.serializers import SkillSerializer
from apps.recruiters.serializers import CompanyListSerializer

from .models import SavedJob, Job, JobCategory, Tag, SavedSearch, SearchHistory


class JobCategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = JobCategory
        fields = ('id', 'name', 'slug', 'description', 'icon', 'children')

    def get_children(self, obj):
        if not obj.children.exists():
            return []
        return JobCategorySerializer(obj.children.filter(is_active=True), many=True).data


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ('id', 'name', 'slug')


class JobListSerializer(serializers.ModelSerializer):
    """Compact for listings."""
    company = CompanyListSerializer(read_only=True)
    required_skills = SkillSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Job
        fields = (
            'public_id', 'title', 'company', 'category_name',
            'employment_type', 'work_arrangement', 'location',
            'salary_min', 'salary_max', 'salary_currency', 'salary_period',
            'is_salary_visible', 'is_salary_negotiable',
            'min_experience_years', 'max_experience_years',
            'required_skills',
            'status', 'application_deadline', 'activated_at','rejection_reason',
            'view_count', 'application_count',
        )
        
class JobDetailSerializer(serializers.ModelSerializer):
    """Full job detail."""
    company = CompanyListSerializer(read_only=True)
    category = JobCategorySerializer(read_only=True)
    required_skills = SkillSerializer(many=True, read_only=True)
    nice_to_have_skills = SkillSerializer(many=True, read_only=True)
    tags = TagSerializer(many=True, read_only=True)
    posted_by_name = serializers.CharField(source='posted_by.full_name', read_only=True)

    class Meta:
        model = Job
        fields = (
            'public_id', 'title', 'description',
            'company', 'category', 'tags',
            'required_skills', 'nice_to_have_skills',
            'min_experience_years', 'max_experience_years',
            'employment_type', 'work_arrangement', 'location',
            'salary_min', 'salary_max', 'salary_currency', 'salary_period',
            'is_salary_visible', 'is_salary_negotiable',
            'status', 'application_deadline',
            'view_count', 'application_count',
            'posted_by_name', 'rejection_reason',
            'activated_at', 'created_at',
        )
        
class PublicJobDetailSerializer(JobDetailSerializer):
    """
    Job detail for anonymous readers.

    Two fields come out. `posted_by_name` puts a recruiter's name in front
    of every scraper on the internet, and `rejection_reason` is internal
    moderation notes - a rejected job is not publicly visible today, but a
    field that leaks the moment a status check changes is worth removing
    rather than relying on.
    """

    class Meta(JobDetailSerializer.Meta):
        fields = tuple(
            field for field in JobDetailSerializer.Meta.fields
            if field not in ('posted_by_name', 'rejection_reason')
        )


class JobCreateUpdateSerializer(serializers.ModelSerializer):
    """For POST + PATCH from recruiter side."""

    required_skill_ids = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.filter(is_approved=True, is_deprecated=False),
        many=True,
        write_only=True,
        source='required_skills',
    )
    nice_to_have_skill_ids = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.filter(is_approved=True, is_deprecated=False),
        many=True,
        write_only=True,
        source='nice_to_have_skills',
        required=False,
    )
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=50),
        write_only=True,
        required=False,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=JobCategory.objects.filter(is_active=True),
        source='category',
        required=False,
        allow_null=True,
    )
    public_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    class Meta:
        model = Job
        fields = (
            'public_id', 'status',
            'title', 'description',
            'category_id', 'tag_names',
            'required_skill_ids', 'nice_to_have_skill_ids',
            'min_experience_years', 'max_experience_years',
            'employment_type', 'work_arrangement', 'location',
            'salary_min', 'salary_max', 'salary_currency', 'salary_period',
            'is_salary_negotiable', 'is_salary_visible',
            'application_deadline',
        )

    def validate(self, attrs):
        # Salary range
        smin = attrs.get('salary_min')
        smax = attrs.get('salary_max')
        if smin and smax and smin > smax:
            raise serializers.ValidationError({
                'salary_max': 'Cannot be less than salary_min.'
            })

        # Experience range
        emin = attrs.get('min_experience_years', 0)
        emax = attrs.get('max_experience_years')
        if emax is not None and emax < emin:
            raise serializers.ValidationError({
                'max_experience_years': 'Cannot be less than min_experience_years.'
            })

        return attrs
    
    @transaction.atomic
    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        skills = validated_data.pop('required_skills', [])
        nth_skills = validated_data.pop('nice_to_have_skills', [])

        recruiter = self.context['request'].user.recruiter_profile
        if not recruiter.company_id:
            raise serializers.ValidationError(
                "You must be part of a company to post jobs."
            )
                # Plan-based job posting quota. Draft and pending jobs count too,
        # so a Free recruiter cannot stockpile drafts past the limit.
        from apps.payments.services import FeatureGateService
        quota = FeatureGateService.can_post_job(recruiter)
        if not quota['can']:
            raise serializers.ValidationError({
                'detail': (
                    f"Job posting limit reached ({quota['active']}/{quota['limit']} "
                    f"active jobs). Current plan: {quota['plan']}. "
                    "Close existing jobs or upgrade for more."
                )
            })

        validated_data['company'] = recruiter.company
        validated_data['posted_by'] = recruiter

        job = Job.objects.create(**validated_data)

        if skills:
            job.required_skills.set(skills)
        if nth_skills:
            job.nice_to_have_skills.set(nth_skills)
        if tag_names:
            self._set_tags(job, tag_names)

        return job

    @transaction.atomic
    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        skills = validated_data.pop('required_skills', None)
        nth_skills = validated_data.pop('nice_to_have_skills', None)

        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if skills is not None:
            instance.required_skills.set(skills)
        if nth_skills is not None:
            instance.nice_to_have_skills.set(nth_skills)
        if tag_names is not None:
            self._set_tags(instance, tag_names)

        return instance

    @staticmethod
    def _set_tags(job, names):
        tags = []
        for raw in names:
            name = raw.lower().strip()
            if not name:
                continue
            tag, _ = Tag.objects.get_or_create(name=name)
            tags.append(tag)
        job.tags.set(tags)

        # Update use counts (simple approach)
        for tag in tags:
            Tag.objects.filter(pk=tag.pk).update(use_count=models.F('use_count') + 1)
            
class SavedSearchSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    class Meta:
        model = SavedSearch
        fields = (
            'id', 'user','name', 'query_text', 'filters',
            'notify_new_matches', 'last_executed_at', 'created_at',
        )
        read_only_fields = ('last_executed_at', 'created_at')
        validators = [
            serializers.UniqueTogetherValidator(
                queryset=SavedSearch.objects.all(),
                fields=('user', 'name'),
                message='You already have a saved search with this name.',
            )
        ]


class SearchHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchHistory
        fields = ('id', 'query_text', 'filters', 'result_count', 'created_at')
        read_only_fields = fields


class SavedJobSerializer(serializers.ModelSerializer):
    """A bookmark, with the job embedded for listing."""
    job = JobListSerializer(read_only=True)

    class Meta:
        model = SavedJob
        fields = ('id', 'job', 'note', 'created_at')
        read_only_fields = ('id', 'job', 'created_at')


class SaveJobSerializer(serializers.Serializer):
    """For POST /jobs/<uuid>/save/"""
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
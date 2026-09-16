from rest_framework import serializers

from apps.jobs.models import Job
from apps.skills.serializers import SkillSerializer


class DashboardCompanySerializer(serializers.Serializer):
    name = serializers.CharField()
    logo = serializers.ImageField(allow_null=True, use_url=True)


class DashboardJobSerializer(serializers.ModelSerializer):
    """
    The job fields a dashboard card draws. Deliberately narrower than
    JobListSerializer, which also carries recruiter-side counters.
    """

    company = DashboardCompanySerializer(read_only=True)
    required_skills = SkillSerializer(many=True, read_only=True)

    class Meta:
        model = Job
        fields = (
            "public_id",
            "title",
            "company",
            "employment_type",
            "work_arrangement",
            "location",
            "required_skills",
            "application_deadline",
        )
        read_only_fields = fields


# ── Response documentation ────────────────────────────────────────────
# The view returns data already shaped by services.py; these serializers
# describe that shape for the OpenAPI schema (and Swagger UI).


class _PlanSerializer(serializers.Serializer):
    tier = serializers.CharField()
    name = serializers.CharField()
    features = serializers.ListField(child=serializers.CharField())


class _NextActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    detail = serializers.CharField()
    cta = serializers.CharField()
    link = serializers.CharField(allow_null=True)
    action = serializers.ChoiceField(choices=["apply"], allow_null=True)
    job_id = serializers.CharField(allow_null=True)
    job_title = serializers.CharField(allow_null=True)
    progress = serializers.IntegerField(allow_null=True)


class _AttentionSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.ChoiceField(
        choices=["offer", "interview", "deadline", "status_change", "profile_views"]
    )
    tone = serializers.CharField()
    text = serializers.CharField()
    cta = serializers.CharField()
    link = serializers.CharField()


class _JobMatchesTileSerializer(serializers.Serializer):
    locked = serializers.BooleanField()
    count = serializers.IntegerField(allow_null=True)
    capped = serializers.BooleanField()


class _QuotaSerializer(serializers.Serializer):
    used = serializers.IntegerField()
    limit = serializers.IntegerField()
    remaining = serializers.IntegerField()
    window_days = serializers.IntegerField()


class _TilesSerializer(serializers.Serializer):
    profile_strength = serializers.IntegerField()
    job_matches = _JobMatchesTileSerializer()
    applications_this_month = serializers.IntegerField()
    quota = _QuotaSerializer(allow_null=True, help_text="null on unlimited plans")
    interviews = serializers.IntegerField()


class _TopJobSerializer(serializers.Serializer):
    job = DashboardJobSerializer()
    score = serializers.FloatField(allow_null=True)
    matched_skills = serializers.ListField(child=serializers.CharField())
    missing_skills = serializers.ListField(child=serializers.CharField())


class _TopJobsSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["matches", "latest"])
    items = _TopJobSerializer(many=True)
    all_applied = serializers.BooleanField()


class _ResumeHealthSerializer(serializers.Serializer):
    has_resume = serializers.BooleanField()
    primary_id = serializers.UUIDField(allow_null=True)
    ats_score = serializers.IntegerField(allow_null=True, help_text="Basic ATS score, every plan")
    ai_score = serializers.IntegerField(allow_null=True, help_text="Advanced AI score, Pro only")
    ats_pending = serializers.BooleanField()


class _ChecklistItemSerializer(serializers.Serializer):
    key = serializers.ChoiceField(
        choices=["profile_complete", "five_skills", "resume_uploaded", "target_role_set"]
    )
    done = serializers.BooleanField()


class _HealthSerializer(serializers.Serializer):
    profile_score = serializers.IntegerField()
    next_step = serializers.CharField(allow_blank=True)
    resume = _ResumeHealthSerializer()
    checklist = _ChecklistItemSerializer(many=True)


class _PipelineCardSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    job_title = serializers.CharField()
    company_name = serializers.CharField(allow_blank=True)
    submitted_at = serializers.DateTimeField()


class _PipelineColumnSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    items = _PipelineCardSerializer(many=True)


class _PipelineSerializer(serializers.Serializer):
    submitted = _PipelineColumnSerializer()
    reviewing = _PipelineColumnSerializer()
    shortlisted = _PipelineColumnSerializer()
    interview = _PipelineColumnSerializer()
    offered = _PipelineColumnSerializer()


class _CountsSerializer(serializers.Serializer):
    total_applications = serializers.IntegerField()
    by_status = serializers.DictField(child=serializers.IntegerField())
    is_new_user = serializers.BooleanField()


class _SkillSerializer(serializers.Serializer):
    name = serializers.CharField()
    importance = serializers.CharField(allow_null=True)
    rationale = serializers.CharField(allow_blank=True)


class _ResourceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    url = serializers.URLField()
    provider = serializers.CharField(allow_null=True)
    is_free = serializers.BooleanField()
    duration_hours = serializers.FloatField(allow_null=True)


class _SkillToLearnSerializer(serializers.Serializer):
    locked = serializers.BooleanField()
    state = serializers.ChoiceField(
        choices=["locked", "ready", "needs_skill_gap", "all_covered", "no_resources"]
    )
    skill = _SkillSerializer(allow_null=True)
    resource = _ResourceSerializer(allow_null=True)


class DashboardResponseSerializer(serializers.Serializer):
    """Any section may be null when it failed; its name is then in `errors`."""

    generated_at = serializers.DateTimeField()
    plan = _PlanSerializer(allow_null=True)
    greeting_name = serializers.CharField(allow_null=True)
    next_action = _NextActionSerializer(allow_null=True)
    attention = _AttentionSerializer(many=True, allow_null=True)
    tiles = _TilesSerializer(allow_null=True)
    top_jobs = _TopJobsSerializer(allow_null=True)
    health = _HealthSerializer(allow_null=True)
    pipeline = _PipelineSerializer(allow_null=True)
    counts = _CountsSerializer(allow_null=True)
    skill_to_learn = _SkillToLearnSerializer(allow_null=True)
    errors = serializers.ListField(child=serializers.CharField())


class DashboardSeenSerializer(serializers.Serializer):
    last_seen_at = serializers.DateTimeField()

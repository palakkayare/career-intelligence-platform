from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.skills.models import Skill
from apps.skills.serializers import SkillSerializer

from .analysis_state import FEATURE, analysis_state, can_reanalyse
from .models import Resume, ResumeSkill


class AnalysisStateMixin(serializers.Serializer):
    """
    Adds `analysis_state` and `can_reanalyse` (see analysis_state.py).

    The plan lookup is cached in the serializer context, which a list
    serializer shares with every row, so a list costs one lookup per user
    rather than one per resume.
    """

    analysis_state = serializers.SerializerMethodField()
    can_reanalyse = serializers.SerializerMethodField()

    def _has_analysis(self, obj):
        cache = self.context.setdefault("_resume_analysis_by_user", {})
        if obj.user_id not in cache:
            from apps.payments.services import FeatureGateService

            cache[obj.user_id] = FeatureGateService.has_feature(obj.user, FEATURE)
        return cache[obj.user_id]

    @extend_schema_field(
        serializers.ChoiceField(
            choices=["ready", "failed", "analysing", "queued", "stuck", "not_included"]
        )
    )
    def get_analysis_state(self, obj):
        return analysis_state(obj, has_analysis=self._has_analysis(obj))

    @extend_schema_field(OpenApiTypes.BOOL)
    def get_can_reanalyse(self, obj):
        has = self._has_analysis(obj)
        return can_reanalyse(analysis_state(obj, has_analysis=has), has_analysis=has)


class ResumeUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)
    set_as_primary = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = Resume
        fields = ("name", "file", "set_as_primary")


class ResumeDetailSerializer(AnalysisStateMixin, serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            "public_id",
            "name",
            "original_filename",
            "file_size_bytes",
            "is_primary",
            "status",
            "parsed_at",
            "extracted_text",
            "parsed_data",
            "failure_reason",
            "download_url",
            "created_at",
            "analysis_state",
            "can_reanalyse",
        )
        read_only_fields = fields

    def get_download_url(self, obj):
        from .services import ResumeService

        return ResumeService.get_download_url(obj)


class ResumeListSerializer(AnalysisStateMixin, serializers.ModelSerializer):
    """Compact for list view."""

    class Meta:
        model = Resume
        fields = (
            "public_id",
            "name",
            "original_filename",
            "is_primary",
            "status",
            "created_at",
            "analysis_state",
            "can_reanalyse",
            "failure_reason",
        )
        read_only_fields = fields


class ResumeSkillSerializer(serializers.ModelSerializer):
    skill = SkillSerializer(read_only=True)
    skill_id = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.none(),  # set dynamically in __init__ below
        source="skill",
        write_only=True,
    )

    class Meta:
        model = ResumeSkill
        fields = (
            "id",
            "skill",
            "skill_id",
            "confidence",
            "source",
            "mention_count",
            "is_confirmed",
            "is_user_added",
        )
        read_only_fields = (
            "confidence",
            "source",
            "mention_count",
            "is_user_added",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.skills.models import Skill

        # Only allow approved, non-deprecated skills to be assigned
        self.fields["skill_id"].queryset = Skill.objects.filter(
            is_approved=True,
            is_deprecated=False,
        )


class ResumeParsedSerializer(serializers.ModelSerializer):
    """Full parsed result, including extracted skills with confidence scores."""

    skills = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            "public_id",
            "name",
            "status",
            "parsed_data",
            "extracted_text",
            "ats_score",
            "ats_breakdown",
            "skills",
            "parsed_at",
        )
        read_only_fields = fields

    def get_skills(self, obj):
        skills = obj.resume_skills.select_related("skill").order_by("-confidence")
        return ResumeSkillSerializer(skills, many=True).data


class AddSkillSerializer(serializers.Serializer):
    """Used when a user manually adds a skill to their resume."""

    skill_id = serializers.IntegerField()

    def validate_skill_id(self, value):
        from apps.skills.models import Skill

        if not Skill.objects.filter(id=value, is_approved=True, is_deprecated=False).exists():
            raise serializers.ValidationError("Invalid skill ID.")
        return value


class AdvancedAtsResultSerializer(serializers.ModelSerializer):
    """Cached advanced ATS result for one resume."""

    class Meta:
        model = Resume
        fields = (
            "public_id",
            "advanced_ats_score",
            "advanced_ats_breakdown",
            "advanced_ats_analyzed_at",
        )
        read_only_fields = fields


class ResumeStatusSerializer(AnalysisStateMixin, serializers.ModelSerializer):
    """
    Just enough to answer "is it done yet?".

    The detail serializer carries `extracted_text` and `parsed_data` - tens of
    kilobytes. The upload screen polls while parsing runs, so it was pulling
    the whole resume down every few seconds to read one status field.
    """

    class Meta:
        model = Resume
        fields = (
            "public_id",
            "status",
            "analysis_state",
            "can_reanalyse",
            "ats_score",
            "failure_reason",
            "updated_at",
        )
        read_only_fields = fields

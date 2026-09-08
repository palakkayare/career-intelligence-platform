from rest_framework import serializers
from apps.skills.models import Skill
from .models import Resume
from apps.skills.serializers import SkillSerializer
from .models import Resume, ResumeSkill

class ResumeUploadSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, required=True)
    set_as_primary = serializers.BooleanField(required=False, default=False)

    class Meta:
        model = Resume
        fields = ('name', 'file', 'set_as_primary')


class ResumeDetailSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            'public_id', 'name',
            'original_filename', 'file_size_bytes',
            'is_primary',
            'status', 'parsed_at',
            'extracted_text',
            'parsed_data',
            'failure_reason',
            'download_url',
            'created_at',
        )
        read_only_fields = fields

    def get_download_url(self, obj):
        from .services import ResumeService
        return ResumeService.get_download_url(obj)


class ResumeListSerializer(serializers.ModelSerializer):
    """Compact for list view."""

    class Meta:
        model = Resume
        fields = (
            'public_id', 'name', 'original_filename',
            'is_primary', 'status', 'created_at',
        )
        read_only_fields = fields

class ResumeSkillSerializer(serializers.ModelSerializer):
    skill = SkillSerializer(read_only=True)
    skill_id = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.none(), # set dynamically in __init__ below
        source='skill',
        write_only=True,
    )

    class Meta:
        model = ResumeSkill
        fields = (
            'id', 'skill', 'skill_id',
            'confidence', 'source', 'mention_count',
            'is_confirmed', 'is_user_added',
        )
        read_only_fields = (
            'confidence', 'source', 'mention_count', 'is_user_added',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.skills.models import Skill
        # Only allow approved, non-deprecated skills to be assigned
        self.fields['skill_id'].queryset = Skill.objects.filter(
            is_approved=True, is_deprecated=False,
        )


class ResumeParsedSerializer(serializers.ModelSerializer):
    """Full parsed result, including extracted skills with confidence scores."""
    skills = serializers.SerializerMethodField()

    class Meta:
        model = Resume
        fields = (
            'public_id', 'name', 'status',
            'parsed_data', 'extracted_text',
            'ats_score', 'ats_breakdown',
            'skills',
            'parsed_at',
        )
        read_only_fields = fields

    def get_skills(self, obj):
        skills = obj.resume_skills.select_related('skill').order_by('-confidence')
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
            'public_id',
            'advanced_ats_score',
            'advanced_ats_breakdown',
            'advanced_ats_analyzed_at',
        )
        read_only_fields = fields
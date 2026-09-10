from rest_framework import serializers

from apps.skills.models import Skill
from apps.skills.serializers import SkillSerializer

from .models import Education, SeekerProfile, SeekerSkill, WorkExperience


class WorkExperienceSerializer(serializers.ModelSerializer):
    skills_used = SkillSerializer(many=True, read_only=True)
    skill_ids = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.all(),
        many=True,
        write_only=True,
        source="skills_used",
        required=False,
    )

    class Meta:
        model = WorkExperience
        fields = (
            "id",
            "company_name",
            "job_title",
            "employment_type",
            "location",
            "start_date",
            "end_date",
            "is_current",
            "description",
            "skills_used",
            "skill_ids",
        )

    def validate(self, attrs):
        if attrs.get("is_current") and attrs.get("end_date"):
            raise serializers.ValidationError({"end_date": "Current job cannot have an end date."})
        if not attrs.get("is_current") and not attrs.get("end_date"):
            raise serializers.ValidationError({"end_date": "Past jobs must have an end date."})
        if (
            attrs.get("end_date")
            and attrs.get("start_date")
            and attrs["end_date"] < attrs["start_date"]
        ):
            raise serializers.ValidationError({"end_date": "End date must be after start date."})
        return attrs


class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = (
            "id",
            "institution_name",
            "degree",
            "field_of_study",
            "start_year",
            "end_year",
            "grade",
            "description",
        )


class SeekerSkillSerializer(serializers.ModelSerializer):
    """For displaying user's skills with proficiency."""

    skill = SkillSerializer(read_only=True)
    skill_id = serializers.PrimaryKeyRelatedField(
        queryset=Skill.objects.filter(is_approved=True, is_deprecated=False),
        source="skill",
        write_only=True,
    )

    class Meta:
        model = SeekerSkill
        fields = ("id", "skill", "skill_id", "proficiency", "years_of_experience")

    def validate_skill_id(self, value):
        seeker = self.context["request"].user.seeker_profile
        qs = SeekerSkill.objects.filter(seeker=seeker, skill=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("You've already added this skill.")
        return value


class SeekerProfileSerializer(serializers.ModelSerializer):
    """Full nested profile for GET /seekers/me/."""

    experiences = WorkExperienceSerializer(many=True, read_only=True)
    educations = EducationSerializer(many=True, read_only=True)
    skills_detail = SeekerSkillSerializer(
        source="seeker_skills",
        many=True,
        read_only=True,
    )
    # The stored column is the score; the breakdown is derived on read
    # because only the number needs to be filterable.
    profile_strength_detail = serializers.SerializerMethodField()

    class Meta:
        model = SeekerProfile
        fields = (
            "id",
            "full_name",
            "bio",
            "location",
            "profile_photo",
            "current_title",
            "target_role",
            "years_of_experience",
            "availability_status",
            "visibility",
            "github_url",
            "linkedin_url",
            "behance_url",
            "portfolio_url",
            "experiences",
            "educations",
            "skills_detail",
            "profile_strength",
            # Feature 16 — recruiter search visibility controls
            "is_open_to_opportunities",
            "hide_current_company",
            "searchable_until_date",
        )
        read_only_fields = ("profile_strength", "profile_photo")

    def get_profile_strength_detail(self, obj):
        from .services import ProfileStrengthService

        return ProfileStrengthService.calculate(obj)


class PhotoUploadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SeekerProfile
        fields = ("profile_photo",)

    def validate_profile_photo(self, value):
        # Size check
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Image too large (max 5MB).")

        # Format check
        valid_formats = ["image/jpeg", "image/png", "image/webp"]
        if value.content_type not in valid_formats:
            raise serializers.ValidationError("Invalid format. Use JPG, PNG, or WebP.")
        return value

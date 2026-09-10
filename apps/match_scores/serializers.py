from rest_framework import serializers

from apps.jobs.serializers import JobListSerializer

from .models import MatchScore, SavedCandidate


class MatchScoreDetailSerializer(serializers.ModelSerializer):
    """For a seeker viewing their match score on a job."""

    job = JobListSerializer(read_only=True)

    class Meta:
        model = MatchScore
        fields = (
            "overall_score",
            "skills_score",
            "experience_score",
            "location_score",
            "salary_score",
            "breakdown",
            "job",
            "computed_at",
        )
        read_only_fields = fields


class CandidateMatchSerializer(serializers.ModelSerializer):
    """For a recruiter viewing top candidates."""

    seeker = serializers.SerializerMethodField()

    class Meta:
        model = MatchScore
        fields = (
            "overall_score",
            "skills_score",
            "experience_score",
            "location_score",
            "salary_score",
            "breakdown",
            "seeker",
            "computed_at",
        )
        read_only_fields = fields

    def get_seeker(self, obj):
        return {
            "public_id": str(obj.seeker.user.public_id),
            "full_name": obj.seeker.full_name,
            "current_title": obj.seeker.current_title,
            "years_of_experience": obj.seeker.years_of_experience,
            "location": obj.seeker.location,
            "top_skills": [rs.skill.name for rs in obj.seeker.seeker_skills.all()[:5]],
        }


class SavedCandidateSerializer(serializers.ModelSerializer):
    seeker_info = serializers.SerializerMethodField()

    class Meta:
        model = SavedCandidate
        fields = ("id", "seeker_info", "notes", "created_at")
        read_only_fields = ("id", "seeker_info", "created_at")

    def get_seeker_info(self, obj):
        return {
            "public_id": str(obj.seeker.user.public_id),
            "full_name": obj.seeker.full_name,
            "current_title": obj.seeker.current_title,
        }


class SaveCandidateInputSerializer(serializers.Serializer):
    seeker_public_id = serializers.UUIDField()
    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)

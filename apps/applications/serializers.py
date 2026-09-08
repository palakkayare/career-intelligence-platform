from rest_framework import serializers

from apps.jobs.serializers import JobListSerializer
from .models import Application, ApplicationStatusHistory


class ApplicationResumeSerializer(serializers.Serializer):
    """Minimal resume info embedded in an application."""
    public_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    original_filename = serializers.CharField(read_only=True)
    ats_score = serializers.IntegerField(read_only=True)


class ApplyJobSerializer(serializers.Serializer):
    """For POST /jobs/<uuid>/apply/"""
    cover_letter = serializers.CharField(
        required=False, allow_blank=True, max_length=2000,
    )
    # Omit to use the primary resume - that is the one-click apply path.
    resume_public_id = serializers.UUIDField(required=False, allow_null=True)
    resume_url = serializers.URLField(required=False, allow_blank=True)


class ApplicationSeekerSerializer(serializers.ModelSerializer):
    """View for seeker - their own application."""
    job = JobListSerializer(read_only=True)
    resume = ApplicationResumeSerializer(read_only=True)

    class Meta:
        model = Application
        fields = (
            'id', 'job',
            'cover_letter', 'resume', 'resume_url',
            'status', 'submitted_at', 'last_status_change_at',
            'is_deleted',
        )
        read_only_fields = fields


class ApplicationStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = (
            'id', 'from_status', 'to_status',
            'changed_by_email', 'notes', 'created_at',
        )

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None


class ApplicationRecruiterSerializer(serializers.ModelSerializer):
    """View for recruiter - application to their job, with seeker info + private notes."""
    seeker = serializers.SerializerMethodField()
    job_title = serializers.CharField(source='job.title', read_only=True)
    resume = ApplicationResumeSerializer(read_only=True)

    class Meta:
        model = Application
        fields = (
            'id', 'job_title',
            'seeker',
            'cover_letter', 'resume', 'resume_url',
            'status', 'recruiter_notes',
            'submitted_at', 'last_status_change_at',
            'is_deleted',
        )
        read_only_fields = (
            'id', 'job_title', 'seeker',
            'cover_letter', 'resume', 'resume_url',
            'submitted_at', 'last_status_change_at', 'is_deleted',
        )

    def get_seeker(self, obj):
        """Embed seeker public info - recruiters see full profile."""
        return {
            'public_id': str(obj.seeker.user.public_id),
            'full_name': obj.seeker.full_name,
            'current_title': obj.seeker.current_title,
            'years_of_experience': obj.seeker.years_of_experience,
            'location': obj.seeker.location,
        }


class StatusUpdateSerializer(serializers.Serializer):
    """For POST /applications/<id>/status/"""
    status = serializers.ChoiceField(choices=Application.Status.choices)
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
    )


class RecruiterNotesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = ('recruiter_notes',)
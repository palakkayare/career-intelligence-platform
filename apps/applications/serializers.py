from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.jobs.serializers import PublicJobListSerializer

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
        required=False,
        allow_blank=True,
        max_length=2000,
    )
    # Omit to use the primary resume - that is the one-click apply path.
    resume_public_id = serializers.UUIDField(required=False, allow_null=True)
    resume_url = serializers.URLField(required=False, allow_blank=True)


class ApplicationSeekerSerializer(serializers.ModelSerializer):
    """View for seeker - their own application."""

    # Not JobListSerializer: that one carries the recruiter's view and
    # application counters and the moderation note.
    job = PublicJobListSerializer(read_only=True)
    resume = ApplicationResumeSerializer(read_only=True)

    class Meta:
        model = Application
        fields = (
            "id",
            "job",
            "cover_letter",
            "resume",
            "resume_url",
            "status",
            "submitted_at",
            "last_status_change_at",
            "is_deleted",
        )
        read_only_fields = fields


class ApplicationStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_email = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = (
            "id",
            "from_status",
            "to_status",
            "changed_by_email",
            "actor",
            "notes",
            "created_at",
        )

    def get_changed_by_email(self, obj):
        return obj.changed_by.email if obj.changed_by else None

    @extend_schema_field(serializers.ChoiceField(choices=["candidate", "employer", "system"]))
    def get_actor(self, obj):
        """
        Who made the change, in plain words. The recruiter's own timeline
        showed the raw email of whoever acted, so a candidate's address
        appeared on the employer's screen for no reason.
        """
        if obj.changed_by_id is None:
            return "system"
        return "candidate" if obj.changed_by_id == obj.application.seeker.user_id else "employer"


class SeekerStatusHistorySerializer(serializers.ModelSerializer):
    """
    The candidate's view of their application's timeline.

    The recruiter-side serializer above carries the recruiter's email and the
    note they typed when changing a status ("weak communication skills").
    Neither is the candidate's to read. The candidate sees who acted in
    general terms, and only their own notes.
    """

    actor = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()

    class Meta:
        model = ApplicationStatusHistory
        fields = ("id", "from_status", "to_status", "actor", "notes", "created_at")

    def _actor(self, obj):
        if obj.changed_by_id is None:
            return "system"
        if obj.changed_by_id == obj.application.seeker.user_id:
            return "you"
        return "employer"

    @extend_schema_field(serializers.ChoiceField(choices=["you", "employer", "system"]))
    def get_actor(self, obj):
        return self._actor(obj)

    @extend_schema_field(serializers.CharField(allow_blank=True))
    def get_notes(self, obj):
        return obj.notes if self._actor(obj) == "you" else ""


class ApplicationRecruiterSerializer(serializers.ModelSerializer):
    """View for recruiter - application to their job, with seeker info + private notes."""

    seeker = serializers.SerializerMethodField()
    job_title = serializers.CharField(source="job.title", read_only=True)
    resume = ApplicationResumeSerializer(read_only=True)

    class Meta:
        model = Application
        fields = (
            "id",
            "job_title",
            "seeker",
            "cover_letter",
            "resume",
            "resume_url",
            "status",
            "recruiter_notes",
            "submitted_at",
            "last_status_change_at",
            "is_deleted",
        )
        read_only_fields = (
            "id",
            "job_title",
            "seeker",
            "cover_letter",
            "resume",
            "resume_url",
            "submitted_at",
            "last_status_change_at",
            "is_deleted",
        )

    def get_seeker(self, obj):
        """
        Seeker info for the recruiter whose job this is.

        `profile_public_id` is the id the candidate endpoints use
        (SeekerProfile.public_id); `public_id` is the account's and stays for
        older callers. Sending only the account id made "Full profile" link
        to something the candidate API could never find.
        """
        return {
            "public_id": str(obj.seeker.user.public_id),
            "profile_public_id": str(obj.seeker.public_id),
            "full_name": obj.seeker.full_name,
            "current_title": obj.seeker.current_title,
            "years_of_experience": obj.seeker.years_of_experience,
            "location": obj.seeker.location,
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
        fields = ("recruiter_notes",)


class OfferAnswerResultSerializer(serializers.Serializer):
    message = serializers.CharField()
    status = serializers.CharField()

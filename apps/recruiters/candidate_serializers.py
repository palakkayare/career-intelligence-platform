from rest_framework import serializers

from apps.seekers.models import SeekerProfile
from apps.skills.serializers import SkillSerializer

from .models import CandidateView, RecruiterCredits


def _current_company(obj):
    """Company name from the seeker's ongoing work experience, if any."""
    experience = obj.experiences.filter(is_current=True).first()
    return experience.company_name if experience else None


def _initials(full_name):
    """
    Turn 'Priya Verma' into 'P**** V*****' for privacy-safe display.

    The mask length follows the real name length so the display stays
    natural, and initials are upper-cased so a lower-case profile entry
    does not leak how the seeker typed their name.
    """
    return ' '.join(
        f"{part[0].upper()}{'*' * (len(part) - 1)}"
        for part in full_name.split()
        if part
    )


class CandidateSearchInputSerializer(serializers.Serializer):
    """Validates the recruiter's search payload."""

    skill_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False, default=list,
    )
    experience_years_min = serializers.IntegerField(required=False, min_value=0)
    experience_years_max = serializers.IntegerField(required=False, min_value=0)
    location_city = serializers.CharField(required=False, allow_blank=True)
    q = serializers.CharField(required=False, allow_blank=True)
    target_job_uuid = serializers.UUIDField(required=False)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(
        required=False, default=20, min_value=5, max_value=50,
    )
    min_profile_strength = serializers.IntegerField(
        required=False, min_value=0, max_value=100,
    )

    def validate(self, attrs):
        low = attrs.get('experience_years_min')
        high = attrs.get('experience_years_max')
        if low is not None and high is not None and low > high:
            raise serializers.ValidationError({
                'experience_years_max':
                    'Maximum experience must be greater than or equal to minimum.',
            })
        return attrs


class CandidatePreviewSerializer(serializers.ModelSerializer):
    """Search result item: enough to judge fit, no contact details."""

    skills = SkillSerializer(many=True, read_only=True)
    matched_skills_count = serializers.IntegerField(read_only=True, default=0)
    full_name_initials = serializers.SerializerMethodField()
    match_score = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()

    class Meta:
        model = SeekerProfile
        fields = (
            'public_id', 'full_name_initials',
            'current_title', 'target_role', 'company',
            'years_of_experience', 'location',
            'skills', 'bio',
            'matched_skills_count', 'match_score',
            'updated_at',
        )
        read_only_fields = fields

    def get_full_name_initials(self, obj):
        """
        Show initials only until the recruiter pays to reveal the contact.

        When no name is set we return a neutral placeholder instead of masking
        the email handle: the email is contact data and must stay behind the
        reveal paywall, even one character of it.
        """
        if not obj.full_name:
            return 'Candidate'
        return _initials(obj.full_name)

    def get_company(self, obj):
        """Respect the seeker's stealth-mode toggle."""
        if obj.hide_current_company:
            return 'Stealth'
        return _current_company(obj)

    def get_match_score(self, obj):
        match_scores_map = self.context.get('match_scores_map', {})
        score = match_scores_map.get(obj.id)
        if not score:
            return None
        return {
            'overall': score.overall_score,
            'skills': score.skills_score,
            'experience': score.experience_score,
        }


class CandidateDetailSerializer(serializers.ModelSerializer):
    """Detail view: full bio and skills, contact only after a reveal."""

    skills = SkillSerializer(many=True, read_only=True)
    full_name_masked = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()
    contact_revealed = serializers.SerializerMethodField()
    contact = serializers.SerializerMethodField()

    class Meta:
        model = SeekerProfile
        fields = (
            'public_id', 'full_name_masked',
            'current_title', 'target_role', 'company',
            'years_of_experience', 'location',
            'bio', 'skills',
            'contact_revealed',
            'contact',  # null until the recruiter spends a credit
            'updated_at',
        )
        read_only_fields = fields

    def _is_revealed(self):
        return self.context.get('contact_revealed', False)

    def get_full_name_masked(self, obj):
        if self._is_revealed() and obj.full_name:
            return obj.full_name
        if not obj.full_name:
            return 'Anonymous Seeker'
        return _initials(obj.full_name)

    def get_company(self, obj):
        if obj.hide_current_company and not self._is_revealed():
            return 'Stealth'
        return _current_company(obj)

    def get_contact_revealed(self, obj):
        return self._is_revealed()

    def get_contact(self, obj):
        if not self._is_revealed():
            return None
        return {
            'email': obj.user.email,
            'linkedin_url': obj.linkedin_url or None,
        }


class RecruiterCreditsSerializer(serializers.ModelSerializer):
    remaining = serializers.IntegerField(read_only=True)
    cycle_ends_on = serializers.DateField(read_only=True)

    class Meta:
        model = RecruiterCredits
        fields = (
            'monthly_reveal_limit',
            'reveals_used_this_month',
            'remaining',
            'cycle_starts_on',
            'cycle_ends_on',
        )
        read_only_fields = fields


class CandidateViewHistorySerializer(serializers.ModelSerializer):
    """Recruiter-facing history of the profiles they looked at."""

    seeker_name = serializers.SerializerMethodField()
    seeker_public_id = serializers.UUIDField(
        source='seeker.public_id', read_only=True,
    )

    class Meta:
        model = CandidateView
        fields = (
            'id', 'seeker_public_id', 'seeker_name',
            'view_kind', 'contact_revealed', 'revealed_at',
            'created_at',
        )
        read_only_fields = fields

    def get_seeker_name(self, obj):
        if obj.contact_revealed:
            return obj.seeker.full_name or obj.seeker.user.email
        # Still masked — the recruiter never paid for this one
        if not obj.seeker.full_name:
            return 'Anonymous Seeker'
        return obj.seeker.full_name.split()[0] + ' ***'


class WhoViewedMeSerializer(serializers.ModelSerializer):
    """Seeker-facing list of recruiters who opened their profile."""

    recruiter_name = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = CandidateView
        fields = (
            'id', 'recruiter_name', 'company_name',
            'view_kind', 'contact_revealed',
            'created_at',
        )
        read_only_fields = fields

    def get_recruiter_name(self, obj):
        return obj.recruiter.full_name

    def get_company_name(self, obj):
        if obj.recruiter.company_id:
            return obj.recruiter.company.name
        return None
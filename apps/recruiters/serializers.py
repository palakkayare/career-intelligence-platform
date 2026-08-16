from rest_framework import serializers

from apps.industries.models import Industry
from apps.industries.serializers import IndustrySerializer

from .models import Company, RecruiterProfile


class CompanyListSerializer(serializers.ModelSerializer):
    """Compact for list views."""
    industry = IndustrySerializer(read_only=True)

    class Meta:
        model = Company
        fields = (
            'id', 'name', 'slug', 'logo', 'industry',
            'size', 'is_verified', 'headquarters_location',
        )


class CompanyDetailSerializer(serializers.ModelSerializer):
    """Full company info."""
    industry = IndustrySerializer(read_only=True)
    industry_id = serializers.PrimaryKeyRelatedField(
        queryset=Industry.objects.filter(is_active=True),
        source='industry',
        write_only=True,
        required=False,
        allow_null=True,
    )
    team_size = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = (
            'id', 'name', 'slug', 'logo', 'description', 'culture_statement',
            'industry', 'industry_id', 'size', 'founded_year', 'website',
            'headquarters_location', 'is_verified', 'verified_at',
            'team_size', 'created_at',
        )
        read_only_fields = (
            'slug', 'is_verified', 'verified_at', 'team_size', 'created_at',
        )

    def get_team_size(self, obj):
        return obj.recruiters.filter(is_deleted=False).count()


class CompanyLogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ('logo',)

    def validate_logo(self, value):
        if value.size > 2 * 1024 * 1024:
            raise serializers.ValidationError("Logo too large (max 2MB).")
        if value.content_type not in ['image/jpeg', 'image/png', 'image/webp']:
            raise serializers.ValidationError("Use JPG, PNG, or WebP.")
        return value
    
class RecruiterProfileSerializer(serializers.ModelSerializer):
    """Full recruiter profile, with conditional contact reveal."""
    company = CompanyListSerializer(read_only=True)
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()

    class Meta:
        model = RecruiterProfile
        fields = (
            'id', 'full_name', 'position', 'bio', 'profile_photo',
            'company', 'is_company_admin',
            'email', 'phone', 'linkedin_url', 'contact_visibility',
            'created_at',
        )
        read_only_fields = (
            'is_company_admin', 'company', 'email', 'created_at',
        )

    def get_email(self, obj):
        if self._can_see_contact(obj):
            return obj.user.email
        return None

    def get_phone(self, obj):
        if self._can_see_contact(obj):
            return obj.phone
        return None

    def _can_see_contact(self, obj):
        """Apply contact_visibility rules."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False

        # Self always sees own contact
        if obj.user_id == request.user.id:
            return True

        if obj.contact_visibility == RecruiterProfile.ContactVisibility.PUBLIC:
            return True

        if obj.contact_visibility == RecruiterProfile.ContactVisibility.PRIVATE:
            return False

        # CONNECTED — only candidates who applied to recruiter's jobs
        # Phase 1: simplified — return False until Application model exists
        # Will be expanded in Step 11 (Job Application System)
        return False


class RecruiterProfileUpdateSerializer(serializers.ModelSerializer):
    """For PATCH /recruiters/me/."""

    class Meta:
        model = RecruiterProfile
        fields = (
            'full_name', 'position', 'bio',
            'phone', 'linkedin_url', 'contact_visibility',
        )
    

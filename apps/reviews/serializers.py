"""
Review serializers.

The one rule that matters here: `author` appears in no serializer, in no
field list, and in no ordering. It is stored for verification and abuse
handling, and it never leaves the API.
"""

from rest_framework import serializers

from .models import CompanyResponse, CompanyReview, InterviewExperience, ReviewReport


class CompanyResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyResponse
        fields = ("responder_name", "responder_title", "response", "created_at")


class CompanyReviewSerializer(serializers.ModelSerializer):
    """Public view. Deliberately has no author field."""

    overall_rating = serializers.ReadOnlyField()
    company_response = CompanyResponseSerializer(read_only=True)
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = CompanyReview
        fields = (
            "id",
            "job_title",
            "employment_status",
            "employment_years",
            "rating_culture",
            "rating_management",
            "rating_growth",
            "rating_salary",
            "overall_rating",
            "headline",
            "pros",
            "cons",
            "advice_to_management",
            "would_recommend",
            "is_verified_employee",
            "helpful_count",
            "company_response",
            "is_mine",
            "created_at",
        )
        read_only_fields = (
            "id",
            "is_verified_employee",
            "helpful_count",
            "company_response",
            "created_at",
        )

    def get_is_mine(self, obj):
        """
        Lets the frontend show edit and delete controls without ever
        learning who wrote anyone else's review.
        """
        request = self.context.get("request")
        return bool(request and obj.author_id == request.user.id)


class CompanyReviewWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyReview
        fields = (
            "job_title",
            "employment_status",
            "employment_years",
            "rating_culture",
            "rating_management",
            "rating_growth",
            "rating_salary",
            "headline",
            "pros",
            "cons",
            "advice_to_management",
            "would_recommend",
        )

    def validate(self, attrs):
        """
        Both sides required.

        A review that is only complaints or only praise is less useful than
        one that admits the other side exists, and asking for both is the
        cheapest way to get a considered answer.
        """
        for field in ("pros", "cons"):
            value = attrs.get(field, "").strip()
            if len(value) < 20:
                raise serializers.ValidationError(
                    {
                        field: "Please write at least a sentence. "
                        "Both sides make a review useful.",
                    }
                )
        return attrs


class InterviewExperienceSerializer(serializers.ModelSerializer):
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = InterviewExperience
        fields = (
            "id",
            "role_applied",
            "outcome",
            "difficulty",
            "rounds",
            "weeks_to_decision",
            "process",
            "questions_asked",
            "was_experience_positive",
            "is_mine",
            "created_at",
        )
        read_only_fields = ("id", "created_at")

    def get_is_mine(self, obj):
        request = self.context.get("request")
        return bool(request and obj.author_id == request.user.id)


class InterviewExperienceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterviewExperience
        fields = (
            "role_applied",
            "outcome",
            "difficulty",
            "rounds",
            "weeks_to_decision",
            "process",
            "questions_asked",
            "was_experience_positive",
        )

    def validate_questions_asked(self, value):
        if len(value) > 20:
            raise serializers.ValidationError(
                "Twenty questions is plenty - pick the ones that mattered.",
            )
        return value


class ReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReviewReport.Reason.choices)
    detail = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
    )


class CompanyResponseWriteSerializer(serializers.Serializer):
    response = serializers.CharField(max_length=2000)

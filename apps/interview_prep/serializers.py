from rest_framework import serializers

from .models import (
    CompanyInterviewTip,
    InterviewChecklistItem,
    InterviewQuestion,
    NegotiationScript,
    StarTemplate,
)


class InterviewQuestionSerializer(serializers.ModelSerializer):
    role_name = serializers.SerializerMethodField()

    class Meta:
        model = InterviewQuestion
        fields = (
            'id', 'question', 'guidance', 'category', 'difficulty',
            'role_name', 'asked_frequency',
        )

    def get_role_name(self, obj):
        return obj.target_role.name if obj.target_role_id else None


class StarTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StarTemplate
        fields = (
            'id', 'competency', 'description',
            'situation_prompt', 'task_prompt', 'action_prompt',
            'result_prompt', 'worked_example',
        )


class CompanyInterviewTipSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)

    class Meta:
        model = CompanyInterviewTip
        fields = ('id', 'company_name', 'category', 'tip', 'source')


class NegotiationScriptSerializer(serializers.ModelSerializer):
    class Meta:
        model = NegotiationScript
        fields = (
            'id', 'scenario', 'title', 'situation',
            'script', 'tactics', 'mistakes',
        )


class ChecklistTickSerializer(serializers.Serializer):
    """For POST/DELETE on a checklist item."""
    interview_label = serializers.CharField(max_length=150)

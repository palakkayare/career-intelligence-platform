"""
Interview preparation endpoints.

Content is readable by any authenticated user. It is reference material, not
a paid feature - the blueprint lists interview prep under retention, and
gating it would defeat that.
"""
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.career_intel.models import TargetRole
from apps.recruiters.models import Company

from .models import InterviewChecklistItem
from .serializers import (
    ChecklistTickSerializer,
    CompanyInterviewTipSerializer,
    InterviewQuestionSerializer,
    NegotiationScriptSerializer,
    StarTemplateSerializer,
)
from .services import InterviewPrepService


class InterviewQuestionListView(APIView):
    """
    GET /api/v1/interview-prep/questions/

    Query: ?role_id= &category= &difficulty= &limit=
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        target_role = None
        role_id = request.query_params.get('role_id')
        if role_id:
            target_role = get_object_or_404(TargetRole, pk=role_id)

        questions = InterviewPrepService.questions_for(
            target_role=target_role,
            category=request.query_params.get('category'),
            difficulty=request.query_params.get('difficulty'),
            limit=min(int(request.query_params.get('limit', 20)), 50),
        )

        return Response({
            'role': target_role.name if target_role else None,
            'count': len(questions),
            'questions': InterviewQuestionSerializer(questions, many=True).data,
        })


class StarTemplateListView(APIView):
    """GET /api/v1/interview-prep/star-templates/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        templates = InterviewPrepService.star_templates()
        return Response(StarTemplateSerializer(templates, many=True).data)


class CompanyTipsView(APIView):
    """GET /api/v1/interview-prep/companies/<uuid:public_id>/tips/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, public_id):
        company = get_object_or_404(
            Company, public_id=public_id, is_deleted=False,
        )
        tips = InterviewPrepService.tips_for_company(company)

        return Response({
            'company': company.name,
            'tips': CompanyInterviewTipSerializer(tips, many=True).data,
        })


class NegotiationScriptListView(APIView):
    """GET /api/v1/interview-prep/negotiation/  ?scenario="""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        scripts = InterviewPrepService.negotiation_scripts(
            scenario=request.query_params.get('scenario'),
        )
        return Response(NegotiationScriptSerializer(scripts, many=True).data)


class ChecklistView(APIView):
    """
    GET /api/v1/interview-prep/checklist/  ?interview=

    Without ?interview the checklist comes back unticked, which is the right
    view for someone browsing rather than preparing.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(InterviewPrepService.checklist(
            user=request.user,
            interview_label=request.query_params.get('interview'),
        ))


class ChecklistItemView(APIView):
    """
    POST   /api/v1/interview-prep/checklist/<int:pk>/  - tick
    DELETE /api/v1/interview-prep/checklist/<int:pk>/  - untick

    Both take an interview_label, because progress is per interview.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _label(self, request):
        serializer = ChecklistTickSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data['interview_label']

    def post(self, request, pk):
        item = get_object_or_404(InterviewChecklistItem, pk=pk, is_active=True)
        label = self._label(request)

        _, created = InterviewPrepService.tick(request.user, item, label)

        return Response(
            InterviewPrepService.checklist(request.user, label),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        item = get_object_or_404(InterviewChecklistItem, pk=pk)
        label = self._label(request)

        InterviewPrepService.untick(request.user, item, label)

        return Response(InterviewPrepService.checklist(request.user, label))


class MyInterviewsView(APIView):
    """GET /api/v1/interview-prep/my-interviews/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({
            'interviews': InterviewPrepService.my_interviews(request.user),
        })

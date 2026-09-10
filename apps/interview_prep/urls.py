from django.urls import path

from .views import (
    ChecklistItemView,
    ChecklistView,
    CompanyTipsView,
    InterviewQuestionListView,
    MyInterviewsView,
    NegotiationScriptListView,
    StarTemplateListView,
)

interview_prep_patterns = [
    path('questions/', InterviewQuestionListView.as_view(), name='questions'),
    path('star-templates/', StarTemplateListView.as_view(), name='star-templates'),
    path('companies/<uuid:public_id>/tips/', CompanyTipsView.as_view(), name='company-tips'),
    path('negotiation/', NegotiationScriptListView.as_view(), name='negotiation'),
    path('checklist/', ChecklistView.as_view(), name='checklist'),
    path('checklist/<int:pk>/', ChecklistItemView.as_view(), name='checklist-item'),
    path('my-interviews/', MyInterviewsView.as_view(), name='my-interviews'),
]

from django.urls import path

from .views import (
    ResumeListUploadView,
    ResumeDetailView,
    SetPrimaryResumeView,
    DownloadUrlView,
    ParsedResumeView,
    ReparseResumeView,
    AddResumeSkillView,
    RemoveResumeSkillView,
    ConfirmResumeSkillView,
    AtsScoreView,
    AdvancedAtsView,
    AtsBestPracticesView,
    ReAnalyzeAdvancedAtsView,
)

resumes_patterns = [
    path('', ResumeListUploadView.as_view(), name='list-upload'),
    path('<uuid:public_id>/', ResumeDetailView.as_view(), name='detail'),
    path('<uuid:public_id>/set-primary/', SetPrimaryResumeView.as_view(), name='set-primary'),
    path('<uuid:public_id>/download-url/', DownloadUrlView.as_view(), name='download-url'),
    
     # Parsing
    path('<uuid:public_id>/parsed/', ParsedResumeView.as_view(), name='parsed'),
    path('<uuid:public_id>/reparse/', ReparseResumeView.as_view(), name='reparse'),
    path('<uuid:public_id>/ats-score/', AtsScoreView.as_view(), name='ats-score'),

    # Skills (manual correction)
    path('<uuid:public_id>/skills/', AddResumeSkillView.as_view(), name='add-skill'),
    path('<uuid:public_id>/skills/<int:skill_id>/', RemoveResumeSkillView.as_view(), name='remove-skill'),
    path('<uuid:public_id>/skills/<int:skill_id>/confirm/', ConfirmResumeSkillView.as_view(), name='confirm-skill'),
    path('<uuid:public_id>/advanced-ats/',AdvancedAtsView.as_view(), name='advanced-ats'),
    path('<uuid:public_id>/re-analyze-ats/',ReAnalyzeAdvancedAtsView.as_view(), name='re-analyze-ats'),
]
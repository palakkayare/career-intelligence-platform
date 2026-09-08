from django.urls import path

from .views import (
    MyProfileView,
    PublicProfileView,
    PhotoUploadView,
    WorkExperienceListCreateView,
    WorkExperienceDetailView,
    EducationListCreateView,
    EducationDetailView,
    SkillListCreateView,
    SkillDetailView,
)
from apps.recruiters.candidate_views import WhoViewedMeView

app_name = 'seekers'

urlpatterns = [
    # Profile
    path('me/', MyProfileView.as_view(), name='my-profile'),
    path('me/photo/', PhotoUploadView.as_view(), name='photo-upload'),
    path('<uuid:public_id>/', PublicProfileView.as_view(), name='public-profile'),

    # Experiences
    path('me/experiences/', WorkExperienceListCreateView.as_view(), name='experiences'),
    path('me/experiences/<int:pk>/', WorkExperienceDetailView.as_view(), name='experience-detail'),

    # Educations
    path('me/educations/', EducationListCreateView.as_view(), name='educations'),
    path('me/educations/<int:pk>/', EducationDetailView.as_view(), name='education-detail'),

    # Skills (user's own with proficiency)
    path('me/skills/', SkillListCreateView.as_view(), name='skills'),
    path('me/skills/<int:pk>/', SkillDetailView.as_view(), name='skill-detail'),
    
    path('me/who-viewed/', WhoViewedMeView.as_view(), name='who-viewed-me'),
]
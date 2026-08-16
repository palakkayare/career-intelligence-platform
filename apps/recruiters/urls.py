from django.urls import path

from .views import (
    CompanyListCreateView,
    CompanyDetailView,
    CompanyLogoView,
    CompanyTeamView,
    CompanyJoinView,
    CompanyLeaveView,
    CompanyMemberPromoteView,
    CompanyMemberRemoveView,
    MyRecruiterProfileView,
    PublicRecruiterProfileView,
)

app_name = 'recruiters'

# Companies are conceptually shared; we put them under /companies/
companies_patterns = [
    path('', CompanyListCreateView.as_view(), name='company-list'),
    path('<int:pk>/', CompanyDetailView.as_view(), name='company-detail'),
    path('<int:pk>/logo/', CompanyLogoView.as_view(), name='company-logo'),
    path('<int:pk>/team/', CompanyTeamView.as_view(), name='company-team'),
    path('<int:pk>/join/', CompanyJoinView.as_view(), name='company-join'),
    path('<int:pk>/leave/', CompanyLeaveView.as_view(), name='company-leave'),
    path('<int:pk>/members/<int:recruiter_id>/promote/',
         CompanyMemberPromoteView.as_view(), name='member-promote'),
    path('<int:pk>/members/<int:recruiter_id>/remove/',
         CompanyMemberRemoveView.as_view(), name='member-remove'),
]

# Recruiter profile routes
recruiters_patterns = [
    path('me/', MyRecruiterProfileView.as_view(), name='my-profile'),
    path('<uuid:public_id>/', PublicRecruiterProfileView.as_view(), name='public-profile'),
]
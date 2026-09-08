from django.urls import path

from .views import (
    AnalyzeGapView,
    CompleteLearningView,
    DropLearningView,
    LearningResourceDetailView,
    LearningResourceListView,
    MyGapHistoryView,
    MyLatestGapView,
    MyLearningsView,
    MyRecommendationsView,
    SkillResourcesView,
    StartLearningView,
    TargetRoleDetailView,
    TargetRoleListView,
    UpdateProgressView,
    SubmitSalaryView,
    MySalarySubmissionsView,
    DeleteMySalarySubmissionView,
    SalaryInsightsView,
    MySalaryComparisonView,
    CareerPathNodeListView,
    CareerPathNodeDetailView,
    FindPathView,
    FromCurrentView,
    GraphDataView,
)

# Mounted at /api/v1/target-roles/
target_roles_patterns = [
    path('', TargetRoleListView.as_view(), name='target-role-list'),
    path(
        '<slug:slug>/',
        TargetRoleDetailView.as_view(),
        name='target-role-detail',
    ),
]

# Mounted at /api/v1/skill-gap/
skill_gap_patterns = [
    path('analyze/', AnalyzeGapView.as_view(), name='analyze'),
    path('me/', MyLatestGapView.as_view(), name='my-latest'),
    path('me/history/', MyGapHistoryView.as_view(), name='my-history'),
]

# Mounted at /api/v1/learning/
learning_patterns = [
    # Browsing
    path(
        'resources/',
        LearningResourceListView.as_view(),
        name='resource-list',
    ),
    path(
        'resources/<int:pk>/',
        LearningResourceDetailView.as_view(),
        name='resource-detail',
    ),
    path(
        'skills/<int:skill_id>/resources/',
        SkillResourcesView.as_view(),
        name='skill-resources',
    ),

    # Recommendations
    path(
        'recommendations/me/',
        MyRecommendationsView.as_view(),
        name='my-recommendations',
    ),

    # Progress tracking
    path('me/', MyLearningsView.as_view(), name='my-learnings'),
    path('me/start/', StartLearningView.as_view(), name='start-learning'),
    path(
        'me/<int:pk>/progress/',
        UpdateProgressView.as_view(),
        name='update-progress',
    ),
    path(
        'me/<int:pk>/complete/',
        CompleteLearningView.as_view(),
        name='complete-learning',
    ),
    path('me/<int:pk>/', DropLearningView.as_view(), name='drop-learning'),
]

salary_patterns = [
    path('submit/', SubmitSalaryView.as_view(), name='submit-salary'),
    path('me/', MySalarySubmissionsView.as_view(), name='my-submissions'),
    path('me/<int:pk>/', DeleteMySalarySubmissionView.as_view(), name='delete-submission'),
    path('insights/', SalaryInsightsView.as_view(), name='insights'),
    path('my-comparison/', MySalaryComparisonView.as_view(), name='my-comparison'),
]

career_path_patterns = [
    path('nodes/', CareerPathNodeListView.as_view(), name='node-list'),
    path('nodes/<slug:slug>/', CareerPathNodeDetailView.as_view(), name='node-detail'),
    path('find/', FindPathView.as_view(), name='find-path'),
    path('from-current/', FromCurrentView.as_view(), name='from-current'),
    path('graph-data/', GraphDataView.as_view(), name='graph-data'),
]

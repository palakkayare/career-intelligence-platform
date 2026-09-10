from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from apps.applications.urls import apply_patterns, applications_patterns
from apps.career_intel.urls import (
    career_path_patterns,
    learning_patterns,
    salary_patterns,
    skill_gap_patterns,
    target_roles_patterns,
)
from apps.jobs.urls import admin_jobs_patterns, jobs_patterns, taxonomy_patterns
from apps.match_scores.urls import job_match_patterns, match_patterns
from apps.notifications.urls import (
    notifications_patterns,
    preferences_patterns,
    unsubscribe_patterns,
)
from apps.payments.urls import (
    feature_gates_patterns,
    payments_patterns,
    plans_patterns,
    subscriptions_patterns,
    webhooks_patterns,
)
from apps.recruiters.urls import (
    candidates_patterns,
    companies_patterns,
    recruiters_patterns,
)
from apps.referrals.urls import referrals_patterns
from apps.resumes.urls import resumes_patterns
from apps.resumes.views import AtsBestPracticesView
from apps.core.urls import admin_dashboard_patterns
from apps.interview_prep.urls import interview_prep_patterns
from apps.core.urls import admin_dashboard_patterns, health_patterns
admin.site.site_header = 'Career Intelligence Platform — Admin'
admin.site.index_title = 'Operations Dashboard'
ats_patterns = [
    path('best-practices/', AtsBestPracticesView.as_view(),
         name='best-practices'),
]
urlpatterns = [
    path('admin/', admin.site.urls),
     # API v1
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/skills/', include('apps.skills.urls')),
    path('api/v1/seekers/', include('apps.seekers.urls')),
    path('api/v1/industries/', include('apps.industries.urls')),
    path('api/v1/companies/', include((companies_patterns, 'companies'))),
    path('api/v1/recruiters/', include((recruiters_patterns, 'recruiters'))),
    # Jobs
    path('api/v1/', include((taxonomy_patterns, 'jobs-taxonomy'))),
    path('api/v1/jobs/', include((jobs_patterns, 'jobs'))),
    path('api/v1/admin/jobs/', include((admin_jobs_patterns, 'admin-jobs'))),
     # Application — apply route under jobs/
    path('api/v1/jobs/', include((apply_patterns, 'jobs-apply'))),

    # Application management
    path('api/v1/applications/', include((applications_patterns, 'applications'))),
    
    
    path('api/v1/plans/', include((plans_patterns, 'plans'))),
    path('api/v1/subscriptions/', include((subscriptions_patterns, 'subscriptions'))),
    path('api/v1/feature-gates/', include((feature_gates_patterns, 'feature-gates'))),
    path('api/v1/payments/', include((payments_patterns, 'payments'))),
    path('api/v1/webhooks/', include((webhooks_patterns, 'webhooks'))),
    
    path('api/v1/resumes/', include((resumes_patterns, 'resumes'))),
    path('api/v1/ats/', include((ats_patterns, 'ats'))),
    
    path('api/v1/jobs/', include((job_match_patterns, 'match-jobs'))),
    path('api/v1/match/', include((match_patterns, 'match'))),
    
    path('api/v1/notifications/', include((notifications_patterns, 'notifications'))),
    path('api/v1/notification-preferences/', include((preferences_patterns, 'preferences'))),
    path('unsubscribe/', include((unsubscribe_patterns, 'unsubscribe'))),
    
    path('api/v1/target-roles/', include((target_roles_patterns, 'target-roles'))), 
    path('api/v1/skill-gap/', include((skill_gap_patterns, 'skill-gap'))),
    
    path('api/v1/learning/', include((learning_patterns, 'learning'))),
    path('api/v1/salary/', include((salary_patterns, 'salary'))),
    
    path('api/v1/career-path/', include((career_path_patterns, 'career-path'))),
    
    path('api/v1/candidates/', include((candidates_patterns, 'candidates'))),
    
    path('api/v1/referrals/', include((referrals_patterns, 'referrals'))),
    path('api/v1/admin/dashboard/', include((admin_dashboard_patterns, 'admin-dashboard'))),
    path('api/v1/health/', include((health_patterns, 'health'))),
    
    path('api/v1/interview-prep/', include((interview_prep_patterns, 'interview-prep'))),
    
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
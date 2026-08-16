"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from apps.recruiters.urls import companies_patterns, recruiters_patterns
from apps.jobs.urls import taxonomy_patterns, jobs_patterns, admin_jobs_patterns
from apps.applications.urls import apply_patterns, applications_patterns
from django.contrib import admin

admin.site.site_header = 'Career Intelligence Platform — Admin'
admin.site.index_title = 'Operations Dashboard'
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
]

# if settings.DEBUG:
#     urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path('__debug__/', include(debug_toolbar.urls))]
    
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
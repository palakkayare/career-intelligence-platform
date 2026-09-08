"""
Celery configuration for Career Intelligence Platform.
"""
import os
from celery import Celery
from celery.schedules import crontab

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

app = Celery('career_intelligence')

# Load Celery config from Django settings (CELERY_* prefix)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all installed apps
# Looks for tasks.py in each Django app
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    """Test task to verify Celery is working."""
    print(f'Request: {self.request!r}')
    
app.conf.beat_schedule = {
    # Recompute match scores every 6 hours
    'recompute-match-scores': {
        'task': 'apps.match_scores.tasks.recompute_all_match_scores',
        'schedule': crontab(minute=0, hour='*/6'),
    },
    # (Phase 1 ke management commands ko bhi future mein yahan migrate kar sakte ho)
    'expire-jobs-daily': {
        'task': 'apps.jobs.tasks.expire_jobs_task',
        'schedule': crontab(minute=0, hour=2),
    },
    # NEW: batch all pending digest notifications into one email per user
    'send-daily-digest': {
        'task': 'apps.notifications.tasks.send_daily_digest',
        'schedule': crontab(minute=0, hour=8),  # 8:00 AM daily
    },

    # NEW: warn users 3 days before their subscription ends
    'check-expiring-subscriptions': {
        'task': 'apps.notifications.tasks.check_expiring_subscriptions',
        'schedule': crontab(minute=30, hour=9),  # 9:30 AM daily
    },
    'reset-recruiter-credits': {
        'task': 'apps.recruiters.tasks.reset_expired_credit_cycles',
        'schedule': crontab(minute=30, hour=0),  # 00:30 every day
    },
}
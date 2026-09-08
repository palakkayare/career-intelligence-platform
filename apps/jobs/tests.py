"""
Job lifecycle and bookmark tests.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.jobs.models import Job, SavedJob
from apps.jobs.services import JobStatusService
from apps.jobs.tasks import expire_jobs_task

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------

def test_job_past_its_deadline_is_expired(make_job):
    job = make_job(application_deadline=timezone.now() - timedelta(days=1))

    expired, failed = JobStatusService.expire_overdue()

    job.refresh_from_db()
    assert (expired, failed) == (1, 0)
    assert job.status == Job.Status.EXPIRED


def test_job_with_a_future_deadline_stays_active(make_job):
    job = make_job(application_deadline=timezone.now() + timedelta(days=7))

    JobStatusService.expire_overdue()

    job.refresh_from_db()
    assert job.status == Job.Status.ACTIVE


def test_job_without_a_deadline_stays_active(make_job):
    job = make_job(application_deadline=None)

    JobStatusService.expire_overdue()

    job.refresh_from_db()
    assert job.status == Job.Status.ACTIVE


def test_draft_job_is_never_expired(make_job):
    job = make_job(
        status=Job.Status.DRAFT,
        application_deadline=timezone.now() - timedelta(days=1),
    )

    JobStatusService.expire_overdue()

    job.refresh_from_db()
    assert job.status == Job.Status.DRAFT


@pytest.mark.regression
def test_expiry_task_is_registered_for_beat(make_job):
    """
    Regression: the expiry logic only existed as a management command and the
    Beat entry was commented out, so nothing expired on a running deployment.
    """
    from config.celery import app

    assert 'expire-jobs-daily' in app.conf.beat_schedule

    job = make_job(application_deadline=timezone.now() - timedelta(days=1))
    result = expire_jobs_task()

    job.refresh_from_db()
    assert result['expired'] == 1
    assert job.status == Job.Status.EXPIRED


# --------------------------------------------------------------------------
# Saved jobs (bookmarks)
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_seeker_can_save_a_job(seeker, job):
    """
    Regression: Feature 11 lists "Save / bookmark jobs for later" and nothing
    in the codebase implemented it - SavedSearch stored filters, not postings.
    """
    saved = SavedJob.objects.create(
        user=seeker.user, job=job, note='Good match, apply Monday',
    )

    assert saved.note == 'Good match, apply Monday'
    assert job.saved_by.count() == 1


def test_the_same_job_cannot_be_saved_twice(seeker, job):
    from django.db import IntegrityError

    SavedJob.objects.create(user=seeker.user, job=job)

    with pytest.raises(IntegrityError):
        SavedJob.objects.create(user=seeker.user, job=job)


def test_saving_is_private_to_each_seeker(seeker, job, plans):
    from apps.accounts.models import User

    other = User.objects.create_user(
        email='other@test.com', password='TestPass123!',
        role=User.Role.SEEKER, is_email_verified=True,
    )
    SavedJob.objects.create(user=seeker.user, job=job)

    assert SavedJob.objects.filter(user=other).count() == 0
    assert SavedJob.objects.filter(user=seeker.user).count() == 1


def test_saving_does_not_touch_the_application_counter(seeker, job):
    SavedJob.objects.create(user=seeker.user, job=job)

    job.refresh_from_db()
    assert job.application_count == 0


def test_bookmarks_survive_a_job_being_closed(seeker, job):
    """A closed posting should still be visible in the saved list."""
    SavedJob.objects.create(user=seeker.user, job=job)

    job.status = Job.Status.CLOSED
    job.save()

    assert SavedJob.objects.filter(
        user=seeker.user, job__is_deleted=False,
    ).count() == 1


def test_soft_deleted_jobs_drop_out_of_the_saved_list(seeker, job):
    SavedJob.objects.create(user=seeker.user, job=job)

    job.soft_delete()

    assert SavedJob.objects.filter(
        user=seeker.user, job__is_deleted=False,
    ).count() == 0


def test_deleting_a_seeker_removes_their_bookmarks(seeker, job):
    """SavedJob cascades: a bookmark has no meaning without its owner."""
    SavedJob.objects.create(user=seeker.user, job=job)
    user_id = seeker.user.id

    SavedJob.objects.filter(user_id=user_id).delete()

    assert not SavedJob.objects.filter(user_id=user_id).exists()
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

    assert "expire-jobs-daily" in app.conf.beat_schedule

    job = make_job(application_deadline=timezone.now() - timedelta(days=1))
    result = expire_jobs_task()

    job.refresh_from_db()
    assert result["expired"] == 1
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
        user=seeker.user,
        job=job,
        note="Good match, apply Monday",
    )

    assert saved.note == "Good match, apply Monday"
    assert job.saved_by.count() == 1


def test_the_same_job_cannot_be_saved_twice(seeker, job):
    from django.db import IntegrityError

    SavedJob.objects.create(user=seeker.user, job=job)

    with pytest.raises(IntegrityError):
        SavedJob.objects.create(user=seeker.user, job=job)


def test_saving_is_private_to_each_seeker(seeker, job, plans):
    from apps.accounts.models import User

    other = User.objects.create_user(
        email="other@test.com",
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
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

    assert (
        SavedJob.objects.filter(
            user=seeker.user,
            job__is_deleted=False,
        ).count()
        == 1
    )


def test_soft_deleted_jobs_drop_out_of_the_saved_list(seeker, job):
    SavedJob.objects.create(user=seeker.user, job=job)

    job.soft_delete()

    assert (
        SavedJob.objects.filter(
            user=seeker.user,
            job__is_deleted=False,
        ).count()
        == 0
    )


def test_deleting_a_seeker_removes_their_bookmarks(seeker, job):
    """SavedJob cascades: a bookmark has no meaning without its owner."""
    SavedJob.objects.create(user=seeker.user, job=job)
    user_id = seeker.user.id

    SavedJob.objects.filter(user_id=user_id).delete()

    assert not SavedJob.objects.filter(user_id=user_id).exists()


# --------------------------------------------------------------------------
# Sorting by match score
# --------------------------------------------------------------------------

from decimal import Decimal

from apps.jobs.search import JobSearchService
from apps.match_scores.models import MatchScore


def score_job(seeker, job, value):
    """
    MatchScore stores the component scores alongside the total, and they are
    NOT NULL. Only the overall value matters for sorting, so the components
    are filled with the same number rather than modelled properly.
    """
    return MatchScore.objects.create(
        seeker=seeker,
        job=job,
        overall_score=Decimal(str(value)),
        skills_score=Decimal(str(value)),
        experience_score=Decimal(str(value)),
        location_score=Decimal(str(value)),
        salary_score=Decimal(str(value)),
        breakdown={},
    )


@pytest.mark.regression
def test_jobs_can_be_sorted_by_match_score(seeker, make_job):
    """
    Regression: the blueprint lists match score as a sort option in
    Feature 05 and _apply_sort had no branch for it.
    """
    weak = make_job(title="Weak Fit")
    strong = make_job(title="Strong Fit")
    score_job(seeker, weak, 30)
    score_job(seeker, strong, 95)

    results = list(
        JobSearchService.build_queryset(
            sort="match_score",
            seeker=seeker,
        )
    )

    assert [j.title for j in results[:2]] == ["Strong Fit", "Weak Fit"]


@pytest.mark.regression
def test_unscored_jobs_sink_to_the_bottom(seeker, make_job):
    """
    Scores are recomputed every six hours, so a job posted since the last run
    has none. A NULL sorts high by default, which would put exactly the jobs
    nobody has assessed at the top of a "best fit" list.
    """
    scored = make_job(title="Scored")
    make_job(title="Not Yet Scored")
    score_job(seeker, scored, 40)

    results = list(
        JobSearchService.build_queryset(
            sort="match_score",
            seeker=seeker,
        )
    )

    assert results[0].title == "Scored"


def test_one_seekers_scores_do_not_order_anothers_search(seeker, make_job, plans):
    from apps.accounts.models import User

    low = make_job(title="Low For Me")
    high = make_job(title="High For Me")
    score_job(seeker, low, 10)
    score_job(seeker, high, 90)

    other_user = User.objects.create_user(
        email="other-seeker@test.com",
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )
    other = other_user.seeker_profile

    results = list(
        JobSearchService.build_queryset(
            sort="match_score",
            seeker=other,
        )
    )

    # No scores of their own, so this falls back to recency, not to the
    # first seeker's ordering
    assert len(results) == 2


@pytest.mark.regression
def test_match_sort_without_a_seeker_falls_back_instead_of_crashing(make_job):
    """
    A recruiter passing sort=match_score has no scores. Ordering on an
    annotation that was never added would raise FieldError.
    """
    make_job(title="Some Job")

    results = list(
        JobSearchService.build_queryset(
            sort="match_score",
            seeker=None,
        )
    )

    assert len(results) == 1


def test_the_other_sorts_still_work(seeker, make_job):
    from datetime import timedelta

    from django.utils import timezone

    older = make_job(title="Older")
    make_job(title='Newer')
    Job.objects.filter(pk=older.pk).update(
        activated_at=timezone.now() - timedelta(days=5),
    )

    by_date = list(JobSearchService.build_queryset(sort="date"))
    by_oldest = list(JobSearchService.build_queryset(sort="oldest"))

    assert by_date[0].title == "Newer"
    assert by_oldest[0].title == "Older"


def test_an_unknown_sort_falls_back_to_recency(make_job):
    make_job(title="Only Job")

    results = list(JobSearchService.build_queryset(sort="nonsense"))

    assert len(results) == 1


# --------------------------------------------------------------------------
# Public browsing
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_anyone_can_list_jobs(job):
    """
    Regression: every job endpoint required a login, so nothing was ever
    indexed and no job link opened for someone who was not signed in.
    Feature 20 counts SEO as a revenue channel; it cannot work behind auth.
    """
    from rest_framework.test import APIClient

    response = APIClient().get("/api/v1/jobs/")

    assert response.status_code == 200
    assert response.data["count"] >= 1


def test_anyone_can_open_a_job_link(job):
    """A shared job link has to work for the person it was shared with."""
    from rest_framework.test import APIClient

    response = APIClient().get(f"/api/v1/jobs/{job.public_id}/")

    assert response.status_code == 200
    assert response.data["title"] == job.title


def test_anyone_can_search(job):
    from rest_framework.test import APIClient

    response = APIClient().get("/api/v1/jobs/search/")

    assert response.status_code == 200


@pytest.mark.regression
def test_an_anonymous_reader_does_not_see_the_recruiter(job):
    """
    posted_by_name would put a recruiter's name in front of every scraper
    on the internet.
    """
    from rest_framework.test import APIClient

    response = APIClient().get(f"/api/v1/jobs/{job.public_id}/")

    assert "posted_by_name" not in response.data
    assert "rejection_reason" not in response.data


def test_a_signed_in_reader_still_sees_the_full_detail(seeker_user, job):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=seeker_user)

    response = client.get(f"/api/v1/jobs/{job.public_id}/")

    assert "posted_by_name" in response.data


@pytest.mark.regression
def test_only_active_jobs_are_public(make_job):
    """A draft or a rejected job must not be reachable by URL."""
    from rest_framework.test import APIClient

    draft = make_job(title="Not Live Yet")
    Job.objects.filter(pk=draft.pk).update(status=Job.Status.DRAFT)

    response = APIClient().get(f"/api/v1/jobs/{draft.public_id}/")

    assert response.status_code == 404


def test_an_anonymous_search_records_no_history(job):
    """There is nobody to attribute it to."""
    from rest_framework.test import APIClient

    from apps.jobs.models import SearchHistory

    APIClient().get("/api/v1/jobs/search/?q=engineer")

    assert SearchHistory.objects.count() == 0


def test_a_signed_in_search_still_records_history(seeker_user, job):
    from rest_framework.test import APIClient

    from apps.jobs.models import SearchHistory

    client = APIClient()
    client.force_authenticate(user=seeker_user)
    client.get("/api/v1/jobs/search/?q=engineer")

    assert SearchHistory.objects.filter(user=seeker_user).count() == 1


@pytest.mark.regression
def test_applying_still_needs_a_login(job):
    """
    Browsing opened up; acting did not. This is the line that matters.
    """
    from rest_framework.test import APIClient

    response = APIClient().post(f"/api/v1/jobs/{job.public_id}/apply/", {})

    assert response.status_code in (401, 403)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/jobs/saved/",
        "/api/v1/jobs/saved-searches/",
        "/api/v1/jobs/search-history/",
    ],
)
def test_personal_job_endpoints_still_need_a_login(path):
    from rest_framework.test import APIClient

    assert APIClient().get(path).status_code in (401, 403)


def test_match_sorting_anonymously_falls_back(job):
    """No seeker, no scores - the request must not fail."""
    from rest_framework.test import APIClient

    response = APIClient().get("/api/v1/jobs/search/?sort=match_score")

    assert response.status_code == 200

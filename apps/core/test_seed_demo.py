"""
The demo seeder.

An empty platform demos badly, but a seeder that cannot be cleaned up safely
is worse: it has to be possible to run this on a database that already has
real people in it, and to remove it again without touching them.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.applications.models import Application, ApplicationStatusHistory
from apps.core.management.commands.seed_demo import CANDIDATES, DEMO_DOMAIN, JOBS
from apps.jobs.models import Job
from apps.recruiters.models import Company, RecruiterProfile
from apps.seekers.models import SeekerProfile

User = get_user_model()
pytestmark = pytest.mark.django_db


def seed(**kwargs):
    call_command("seed_skills")
    call_command("seed_demo", **kwargs)


def demo_users():
    return User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")


def test_it_creates_both_sides_of_the_market():
    seed()

    assert Company.objects.count() == 3
    assert Job.objects.filter(status=Job.Status.ACTIVE).count() == len(JOBS)
    demo_seekers = SeekerProfile.objects.filter(user__email__endswith=DEMO_DOMAIN)
    assert demo_seekers.count() == len(CANDIDATES)
    assert Application.objects.exists()


def test_jobs_arrive_live_and_complete():
    """A job with no skills cannot show a match score, which is the point of the demo."""
    seed()

    for job in Job.objects.all():
        assert job.status == Job.Status.ACTIVE
        assert job.activated_at is not None
        assert job.required_skills.exists(), f"{job.title} has no required skills"
        assert job.description


def test_the_pipeline_has_a_history_behind_it():
    seed()

    offered = Application.objects.filter(status="offered").first()
    assert offered is not None

    steps = list(
        ApplicationStatusHistory.objects.filter(application=offered)
        .order_by("created_at")
        .values_list("to_status", flat=True)
    )
    # Not just an offer sitting there with no story.
    assert steps == ["submitted", "reviewing", "shortlisted", "interview", "offered"]


def test_candidates_can_sign_in():
    seed()

    user = demo_users().filter(role="seeker").first()
    assert user.is_email_verified
    assert user.check_password("DemoPass!2026")


def test_running_it_twice_does_not_duplicate():
    seed()
    before = (Company.objects.count(), Job.objects.count(), Application.objects.count())

    call_command("seed_demo")

    assert (Company.objects.count(), Job.objects.count(), Application.objects.count()) == before


def test_wipe_removes_the_demo_and_nothing_else(django_user_model):
    """The one that matters: this will be run on a database with real users."""
    real = django_user_model.objects.create_user(
        email="real.person@example.com", password="pw-12345678", role="seeker"
    )
    real_company = Company.objects.create(name="A Real Company", created_by=real)

    seed()
    assert demo_users().exists()

    call_command("seed_demo", wipe=True)

    # Demo data is rebuilt, real data untouched.
    assert django_user_model.objects.filter(pk=real.pk).exists()
    assert Company.objects.filter(pk=real_company.pk).exists()
    assert demo_users().count() == len(CANDIDATES) + 3  # candidates + one recruiter per company


def test_every_recruiter_runs_their_company():
    seed()

    for profile in RecruiterProfile.objects.filter(user__email__endswith=DEMO_DOMAIN):
        assert profile.company is not None
        assert profile.is_company_admin, "someone has to be able to approve join requests"


def test_it_runs_with_no_message_broker(settings, monkeypatch):
    """
    Seeding is usually run from a laptop against a remote database, where the
    broker is not reachable at all. Saving a job normally queues a Celery
    task, so without care the command dies on the first job with a Redis
    connection error.
    """
    from apps.match_scores.tasks import recompute_match_scores_for_job

    def explode(*args, **kwargs):  # what an unreachable broker looks like
        raise AssertionError("seed_demo must not touch the queue")

    monkeypatch.setattr(recompute_match_scores_for_job, "delay", explode)

    seed()  # must not raise

    assert Job.objects.exists()


def test_match_scores_are_computed_anyway():
    """Removing the queue must not mean losing the scores it would have made."""
    from apps.match_scores.models import MatchScore

    seed()

    assert MatchScore.objects.exists()


def test_it_runs_with_no_cache_either(monkeypatch):
    """
    Seeding from a laptop cannot reach Redis at all, and Redis is both the
    broker and the cache. Saving a profile clears a cached dashboard; saving
    a skill takes a debounce lock. Neither may stop the seed.
    """

    class BrokenCache:
        def __getattr__(self, _name):
            def raiser(*args, **kwargs):
                raise ConnectionError("Redis is unreachable")

            return raiser

    monkeypatch.setattr("apps.dashboard.services.cache", BrokenCache())
    monkeypatch.setattr("django.core.cache.cache", BrokenCache())

    seed(wipe=True)  # must not raise

    assert Job.objects.exists()
    assert demo_users().exists()

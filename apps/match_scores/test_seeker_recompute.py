"""
Scores follow the seeker, not only the job.

Regression: a score was created when a job was saved (for seekers who had a
matching skill at that moment) or at the six-hourly batch. A seeker who
added skills afterwards saw a match % on some jobs and nothing on the rest.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command

from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.match_scores.tasks import (
    queue_seeker_recompute,
    recompute_match_scores_for_seeker,
    seeker_lock_key,
)
from apps.recruiters.models import Company, RecruiterProfile
from apps.seekers.models import SeekerSkill
from apps.skills.models import Skill

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def skills():
    return {n: Skill.objects.create(name=n) for n in ("Python", "Go", "Rust")}


@pytest.fixture
def seeker(django_user_model):
    user = django_user_model.objects.create_user(
        email="rescore@example.com", password="pw-12345678", role="seeker", is_email_verified=True
    )
    return user.seeker_profile


@pytest.fixture
def make_job(django_user_model, skills):
    owner = django_user_model.objects.create_user(
        email="rescore-hr@example.com", password="pw-12345678", role="recruiter"
    )
    company = Company.objects.create(name="Rescore Co", created_by=owner)
    recruiter, _ = RecruiterProfile.objects.get_or_create(user=owner, defaults={"company": company})

    def make(title, needs, **extra):
        # Saved as a draft first so the job-side signal does not score it.
        job = Job.objects.create(
            title=title,
            description="Role",
            company=company,
            posted_by=recruiter,
            status=Job.Status.DRAFT,
            **extra,
        )
        job.required_skills.set([skills[n] for n in needs])
        Job.objects.filter(pk=job.pk).update(status=Job.Status.ACTIVE)
        return job

    return make


def scored_titles(seeker):
    return set(MatchScore.objects.filter(seeker=seeker).values_list("job__title", flat=True))


def test_scores_every_active_job_sharing_a_skill(seeker, skills, make_job):
    make_job("Remote Python", ["Python"], work_arrangement="remote")
    make_job("Hybrid Python", ["Python", "Go"], work_arrangement="hybrid")
    make_job("Onsite Python", ["Python"], work_arrangement="on_site")
    make_job("Rust only", ["Rust"])
    SeekerSkill.objects.create(seeker=seeker, skill=skills["Python"])

    count = recompute_match_scores_for_seeker.run(seeker.pk)

    assert count == 3
    assert scored_titles(seeker) == {"Remote Python", "Hybrid Python", "Onsite Python"}


def test_removed_skill_drops_the_stale_score(seeker, skills, make_job):
    make_job("Go job", ["Go"])
    link = SeekerSkill.objects.create(seeker=seeker, skill=skills["Go"])
    recompute_match_scores_for_seeker.run(seeker.pk)
    assert scored_titles(seeker) == {"Go job"}

    link.delete()
    recompute_match_scores_for_seeker.run(seeker.pk)

    assert scored_titles(seeker) == set()


def test_inactive_jobs_are_left_alone(seeker, skills, make_job):
    job = make_job("Closed", ["Python"])
    SeekerSkill.objects.create(seeker=seeker, skill=skills["Python"])
    recompute_match_scores_for_seeker.run(seeker.pk)
    Job.objects.filter(pk=job.pk).update(status=Job.Status.CLOSED)

    SeekerSkill.objects.filter(seeker=seeker).delete()
    recompute_match_scores_for_seeker.run(seeker.pk)

    # history for a closed job is not ours to rewrite
    assert scored_titles(seeker) == {"Closed"}


def test_adding_a_skill_queues_one_recompute_after_commit(
    seeker, skills, django_capture_on_commit_callbacks
):
    with patch("apps.match_scores.tasks.recompute_match_scores_for_seeker.apply_async") as run:
        with django_capture_on_commit_callbacks(execute=True):
            SeekerSkill.objects.create(seeker=seeker, skill=skills["Python"])
            SeekerSkill.objects.create(seeker=seeker, skill=skills["Go"])
            SeekerSkill.objects.create(seeker=seeker, skill=skills["Rust"])

    run.assert_called_once()
    assert run.call_args.kwargs["args"] == [seeker.pk]
    assert run.call_args.kwargs["countdown"] == 30


def test_removing_a_skill_queues_a_recompute(seeker, skills, django_capture_on_commit_callbacks):
    link = SeekerSkill.objects.create(seeker=seeker, skill=skills["Python"])
    cache.clear()
    with patch("apps.match_scores.tasks.recompute_match_scores_for_seeker.apply_async") as run:
        with django_capture_on_commit_callbacks(execute=True):
            link.delete()
    run.assert_called_once()


def test_profile_edits_that_do_not_affect_scores_queue_nothing(
    seeker, django_capture_on_commit_callbacks
):
    with patch("apps.match_scores.tasks.recompute_match_scores_for_seeker.apply_async") as run:
        with django_capture_on_commit_callbacks(execute=True):
            seeker.bio = "New bio"
            seeker.save(update_fields=["bio"])
        run.assert_not_called()

        with django_capture_on_commit_callbacks(execute=True):
            seeker.location = "Pune"
            seeker.save(update_fields=["location"])
        run.assert_called_once()


def test_the_task_releases_the_lock_so_later_changes_queue_again(seeker):
    assert cache.add(seeker_lock_key(seeker.pk), 1)
    recompute_match_scores_for_seeker.run(seeker.pk)
    assert cache.get(seeker_lock_key(seeker.pk)) is None


def test_queue_ignores_a_missing_seeker_id():
    with patch("apps.match_scores.tasks.recompute_match_scores_for_seeker.apply_async") as run:
        queue_seeker_recompute(None)
    run.assert_not_called()


def test_management_command_scores_one_seeker(seeker, skills, make_job):
    make_job("Python role", ["Python"])
    SeekerSkill.objects.create(seeker=seeker, skill=skills["Python"])
    MatchScore.objects.filter(seeker=seeker).delete()

    out = StringIO()
    call_command("recompute_match_scores", "--email", "rescore@example.com", stdout=out)

    assert "Computed 1 match scores for 1 seeker(s)." in out.getvalue()
    assert scored_titles(seeker) == {"Python role"}


def test_management_command_rejects_an_unknown_email():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("recompute_match_scores", "--email", "nobody@example.com")

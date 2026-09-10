"""
Interview preparation.

Most of this app is curated content, so the tests are mainly about how it is
selected and how progress is tracked - the two places where behaviour lives
rather than data.
"""
import pytest
from rest_framework.test import APIClient

from apps.career_intel.models import TargetRole
from apps.interview_prep.models import (
    ChecklistProgress,
    CompanyInterviewTip,
    InterviewChecklistItem,
    InterviewQuestion,
    NegotiationScript,
    StarTemplate,
)
from apps.interview_prep.services import InterviewPrepService

pytestmark = pytest.mark.django_db

Q = InterviewQuestion
C = InterviewChecklistItem


def make_question(question='A question?', role=None, category=Q.Category.BEHAVIOURAL,
                  difficulty=Q.Difficulty.MID, frequency=50, active=True):
    return Q.objects.create(
        question=question, target_role=role, category=category,
        difficulty=difficulty, asked_frequency=frequency, is_active=active,
    )


def make_checklist_item(phase=C.Phase.PREPARATION, text='Do a thing', order=0):
    return C.objects.create(phase=phase, text=text, order=order)


@pytest.fixture
def backend_role(db):
    return TargetRole.objects.create(name='Senior Backend Developer')


@pytest.fixture
def auth(seeker_user):
    client = APIClient()
    client.force_authenticate(user=seeker_user)
    return client


# --------------------------------------------------------------------------
# Question selection
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_role_questions_come_with_the_general_ones(backend_role):
    """
    Regression: Feature 18 did not exist at all.

    General questions are mixed in rather than kept on a separate tab -
    "tell me about yourself" gets asked in a backend interview too, and
    splitting the list means people practise one half and skip the other.
    """
    make_question('Tell me about yourself.')
    make_question('Design a rate limiter.', role=backend_role)

    questions = InterviewPrepService.questions_for(target_role=backend_role)

    assert len(questions) == 2


def test_another_roles_questions_are_left_out(backend_role, db):
    frontend = TargetRole.objects.create(name='Senior Frontend Developer')
    make_question('Backend one', role=backend_role)
    make_question('Frontend one', role=frontend)

    questions = InterviewPrepService.questions_for(target_role=backend_role)

    assert [q.question for q in questions] == ['Backend one']


def test_without_a_role_only_general_questions_come_back(backend_role):
    make_question('General one')
    make_question('Backend one', role=backend_role)

    questions = InterviewPrepService.questions_for()

    assert [q.question for q in questions] == ['General one']


def test_common_questions_come_first():
    make_question('Rare', frequency=10)
    make_question('Common', frequency=95)

    questions = InterviewPrepService.questions_for()

    assert questions[0].question == 'Common'


def test_questions_can_be_filtered_by_category():
    make_question('Behavioural one', category=Q.Category.BEHAVIOURAL)
    make_question('Technical one', category=Q.Category.TECHNICAL)

    questions = InterviewPrepService.questions_for(
        category=Q.Category.TECHNICAL,
    )

    assert [q.question for q in questions] == ['Technical one']


def test_questions_can_be_filtered_by_difficulty():
    make_question('Entry one', difficulty=Q.Difficulty.ENTRY)
    make_question('Senior one', difficulty=Q.Difficulty.SENIOR)

    questions = InterviewPrepService.questions_for(
        difficulty=Q.Difficulty.SENIOR,
    )

    assert [q.question for q in questions] == ['Senior one']


def test_retired_questions_are_not_served():
    make_question('Still asked', active=True)
    make_question('No longer asked', active=False)

    questions = InterviewPrepService.questions_for()

    assert [q.question for q in questions] == ['Still asked']


def test_the_result_is_capped():
    for index in range(30):
        make_question(f'Question {index}')

    assert len(InterviewPrepService.questions_for(limit=5)) == 5


# --------------------------------------------------------------------------
# Other content
# --------------------------------------------------------------------------

def test_star_templates_are_listed():
    StarTemplate.objects.create(
        competency='Conflict', situation_prompt='S', task_prompt='T',
        action_prompt='A', result_prompt='R',
    )

    assert InterviewPrepService.star_templates().count() == 1


def test_company_tips_are_scoped_to_that_company(company, plans, industry,
                                                 recruiter_user):
    from apps.recruiters.models import Company

    other = Company.objects.create(
        name='Other Corp', industry=industry, created_by=recruiter_user,
    )
    CompanyInterviewTip.objects.create(
        company=company, category=CompanyInterviewTip.Category.PROCESS,
        tip='Three rounds.',
    )
    CompanyInterviewTip.objects.create(
        company=other, category=CompanyInterviewTip.Category.PROCESS,
        tip='Five rounds.',
    )

    tips = InterviewPrepService.tips_for_company(company)

    assert [t.tip for t in tips] == ['Three rounds.']


def test_negotiation_scripts_can_be_filtered_by_scenario():
    NegotiationScript.objects.create(
        scenario=NegotiationScript.Scenario.LOWBALL,
        title='Low offer', situation='...', script='...',
    )
    NegotiationScript.objects.create(
        scenario=NegotiationScript.Scenario.COUNTER,
        title='Counter', situation='...', script='...',
    )

    scripts = InterviewPrepService.negotiation_scripts(
        scenario=NegotiationScript.Scenario.LOWBALL,
    )

    assert [s.title for s in scripts] == ['Low offer']


# --------------------------------------------------------------------------
# Checklist
# --------------------------------------------------------------------------

def test_the_checklist_is_grouped_by_phase():
    make_checklist_item(C.Phase.PREPARATION, 'Read the JD')
    make_checklist_item(C.Phase.DAY_OF, 'Join early')
    make_checklist_item(C.Phase.FOLLOW_UP, 'Send a note')

    result = InterviewPrepService.checklist()

    assert [p['phase'] for p in result['phases']] == [
        'preparation', 'day_of', 'follow_up',
    ]
    assert result['total_items'] == 3


def test_an_untouched_checklist_shows_no_progress(seeker_user):
    make_checklist_item()

    result = InterviewPrepService.checklist(seeker_user, 'Test Corp')

    assert result['completed_items'] == 0
    assert result['progress_pct'] == 0.0


def test_ticking_an_item_shows_up(seeker_user):
    item = make_checklist_item()

    InterviewPrepService.tick(seeker_user, item, 'Test Corp')
    result = InterviewPrepService.checklist(seeker_user, 'Test Corp')

    assert result['completed_items'] == 1
    assert result['progress_pct'] == 100.0


@pytest.mark.regression
def test_progress_is_per_interview(seeker_user):
    """
    The same list gets used again for the next interview. Shared progress
    would show it already complete before you had started.
    """
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    other = InterviewPrepService.checklist(seeker_user, 'Other Corp')

    assert other['completed_items'] == 0


def test_progress_is_per_user(seeker_user, recruiter_user):
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    theirs = InterviewPrepService.checklist(recruiter_user, 'Test Corp')

    assert theirs['completed_items'] == 0


def test_ticking_twice_counts_once(seeker_user):
    item = make_checklist_item()

    InterviewPrepService.tick(seeker_user, item, 'Test Corp')
    _, created = InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    assert created is False
    assert ChecklistProgress.objects.count() == 1


def test_an_item_can_be_unticked(seeker_user):
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    removed = InterviewPrepService.untick(seeker_user, item, 'Test Corp')

    assert removed is True
    assert InterviewPrepService.checklist(
        seeker_user, 'Test Corp',
    )['completed_items'] == 0


def test_unticking_what_was_never_ticked_reports_so(seeker_user):
    item = make_checklist_item()

    assert InterviewPrepService.untick(seeker_user, item, 'Test Corp') is False


def test_browsing_without_naming_an_interview_shows_nothing_ticked(seeker_user):
    """The right view for someone reading the list rather than using it."""
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    result = InterviewPrepService.checklist(seeker_user)

    assert result['completed_items'] == 0


def test_an_empty_checklist_does_not_divide_by_zero():
    result = InterviewPrepService.checklist()

    assert result['total_items'] == 0
    assert result['progress_pct'] == 0.0


@pytest.mark.regression
def test_interviews_in_progress_can_be_listed(seeker_user):
    """
    Lets the frontend offer "continue where you left off" without a separate
    Interview model.
    """
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp - round 1')
    InterviewPrepService.tick(seeker_user, item, 'Other Corp - screen')

    labels = InterviewPrepService.my_interviews(seeker_user)

    assert set(labels) == {'Test Corp - round 1', 'Other Corp - screen'}


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def test_questions_endpoint(auth, backend_role):
    make_question('Design a rate limiter.', role=backend_role)

    response = auth.get(
        f'/api/v1/interview-prep/questions/?role_id={backend_role.pk}',
    )

    assert response.status_code == 200
    assert response.data['role'] == 'Senior Backend Developer'
    assert response.data['count'] == 1


def test_star_templates_endpoint(auth):
    StarTemplate.objects.create(
        competency='Conflict', situation_prompt='S', task_prompt='T',
        action_prompt='A', result_prompt='R',
    )

    response = auth.get('/api/v1/interview-prep/star-templates/')

    assert response.status_code == 200
    assert response.data[0]['competency'] == 'Conflict'


def test_negotiation_endpoint(auth):
    NegotiationScript.objects.create(
        scenario=NegotiationScript.Scenario.LOWBALL,
        title='Low offer', situation='...', script='...',
        tactics=['Say you want the job first'],
    )

    response = auth.get('/api/v1/interview-prep/negotiation/')

    assert response.status_code == 200
    assert response.data[0]['tactics'] == ['Say you want the job first']


def test_checklist_endpoint(auth):
    make_checklist_item()

    response = auth.get('/api/v1/interview-prep/checklist/?interview=Test Corp')

    assert response.status_code == 200
    assert response.data['total_items'] == 1


def test_ticking_through_the_endpoint(auth, seeker_user):
    item = make_checklist_item()

    response = auth.post(
        f'/api/v1/interview-prep/checklist/{item.pk}/',
        {'interview_label': 'Test Corp'}, format='json',
    )

    assert response.status_code == 201
    assert response.data['completed_items'] == 1


def test_unticking_through_the_endpoint(auth, seeker_user):
    item = make_checklist_item()
    InterviewPrepService.tick(seeker_user, item, 'Test Corp')

    response = auth.delete(
        f'/api/v1/interview-prep/checklist/{item.pk}/',
        {'interview_label': 'Test Corp'}, format='json',
    )

    assert response.status_code == 200
    assert response.data['completed_items'] == 0


def test_ticking_needs_an_interview_label(auth):
    item = make_checklist_item()

    response = auth.post(
        f'/api/v1/interview-prep/checklist/{item.pk}/', {}, format='json',
    )

    assert response.status_code == 400


@pytest.mark.regression
def test_interview_prep_is_not_behind_a_paywall(auth):
    """
    The blueprint files this under retention. Gating reference material
    behind Pro would defeat the point of having it.
    """
    make_question('Tell me about yourself.')

    assert auth.get('/api/v1/interview-prep/questions/').status_code == 200


def test_interview_prep_still_needs_a_login():
    assert APIClient().get(
        '/api/v1/interview-prep/questions/',
    ).status_code in (401, 403)


# --------------------------------------------------------------------------
# Seed command
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_the_seed_command_is_idempotent(db):
    """
    Re-running a seed is normal - after a deploy, after adding a role. It
    must not double the content each time.
    """
    from django.core.management import call_command

    call_command('seed_interview_prep', verbosity=0)
    first = Q.objects.count()

    call_command('seed_interview_prep', verbosity=0)

    assert Q.objects.count() == first
    assert first > 0


def test_the_seed_skips_roles_that_do_not_exist(db):
    """
    The role taxonomy is seeded separately. Inventing a role here would
    create a second, drifting set of them.
    """
    from django.core.management import call_command

    call_command('seed_interview_prep', verbosity=0)

    assert Q.objects.filter(target_role__isnull=True).exists()
    assert not TargetRole.objects.filter(name='Backend Developer').exists()
"""
Company reviews.

Most of these tests are about the two hard parts: keeping the author out of
every response, and making moderation resistant to both abuse and to being
used as a takedown tool by the company being reviewed.
"""
import pytest
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.reviews.models import (
    CompanyResponse,
    CompanyReview,
    InterviewExperience,
    ReviewHelpfulVote,
    ReviewReport,
)
from apps.reviews.services import (
    REPORT_HIDE_THRESHOLD,
    InterviewExperienceService,
    ModerationService,
    ResponseService,
    ReviewService,
)

pytestmark = pytest.mark.django_db

Status = CompanyReview.Status
Reason = ReviewReport.Reason


REVIEW_DATA = {
    'job_title': 'Backend Developer',
    'employment_status': CompanyReview.EmploymentStatus.FORMER,
    'employment_years': 2,
    'rating_culture': 4,
    'rating_management': 2,
    'rating_growth': 5,
    'rating_salary': 3,
    'headline': 'Great people, weak management',
    'pros': 'Strong engineers and a genuinely kind team culture.',
    'cons': 'Management changed direction every quarter without explaining why.',
    'would_recommend': True,
}


def make_seeker(email):
    return User.objects.create_user(
        email=email, password='TestPass123!',
        role=User.Role.SEEKER, is_email_verified=True,
    )


def post_review(author, company, **overrides):
    data = {**REVIEW_DATA, **overrides}
    return ReviewService.create(author, company, data)


@pytest.fixture
def author(plans):
    return make_seeker('reviewer@test.com')


@pytest.fixture
def review(author, company):
    return post_review(author, company)


@pytest.fixture
def auth(author):
    client = APIClient()
    client.force_authenticate(user=author)
    return client


# --------------------------------------------------------------------------
# Writing a review
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_review_can_be_posted(author, company):
    """Regression: Feature 20 did not exist at all."""
    review = post_review(author, company)

    assert review.pk
    assert review.status == Status.PUBLISHED
    assert review.overall_rating == 3.5  # (4+2+5+3)/4


@pytest.mark.regression
def test_one_review_per_person_per_company(author, company):
    """
    Without this a single bad experience can be posted twenty times and
    read as twenty people.
    """
    post_review(author, company)

    with pytest.raises(ValidationError):
        post_review(author, company)


def test_the_same_person_can_review_two_companies(author, company, industry,
                                                  recruiter_user):
    from apps.recruiters.models import Company

    other = Company.objects.create(
        name='Other Corp', industry=industry, created_by=recruiter_user,
    )

    post_review(author, company)
    second = post_review(author, other)

    assert second.pk


def test_reviews_publish_immediately(review):
    """
    Pre-moderation sounds safer, but review sections that queue for approval
    sit empty - nobody writes into a void for a week.
    """
    assert review.status == Status.PUBLISHED
    assert review in ReviewService.published_for(review.company)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def test_someone_who_never_applied_is_not_verified(author, company):
    review = post_review(author, company)

    assert review.is_verified_employee is False


@pytest.mark.regression
def test_applying_to_the_company_earns_the_verified_flag(seeker, job):
    """
    Weak evidence, and labelled as what it is. Claiming stronger
    verification than we have would be worse than claiming none.
    """
    from apps.applications.services import ApplicationCreationService

    ApplicationCreationService.create(seeker, job)

    review = post_review(seeker.user, job.company)

    assert review.is_verified_employee is True


def test_verification_cannot_be_set_by_the_submitter(auth, company):
    """A badge the client controls is worth nothing."""
    response = auth.post(
        f'/api/v1/reviews/companies/{company.pk}/',
        {**REVIEW_DATA, 'is_verified_employee': True}, format='json',
    )

    assert response.status_code == 201
    assert response.data['is_verified_employee'] is False


# --------------------------------------------------------------------------
# Anonymity
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_the_author_never_appears_in_a_response(auth, company, review):
    """
    The whole promise of the feature. The FK is stored for verification and
    abuse handling and must not leave the API.
    """
    response = auth.get(f'/api/v1/reviews/companies/{company.pk}/')

    row = response.data['results'][0]
    assert 'author' not in row
    assert 'user' not in row
    assert 'email' not in str(row)


def test_a_reader_sees_is_mine_as_false(company, review, plans):
    other = make_seeker('reader@test.com')
    client = APIClient()
    client.force_authenticate(user=other)

    response = client.get(f'/api/v1/reviews/companies/{company.pk}/')

    assert response.data['results'][0]['is_mine'] is False


def test_the_author_sees_is_mine_as_true(auth, company, review):
    """Lets the frontend show edit controls without revealing anyone else."""
    response = auth.get(f'/api/v1/reviews/companies/{company.pk}/')

    assert response.data['results'][0]['is_mine'] is True


# --------------------------------------------------------------------------
# Editing and withdrawing
# --------------------------------------------------------------------------

def test_the_author_can_edit_within_the_window(review, author):
    ReviewService.update(review, author, {'headline': 'Updated headline'})

    review.refresh_from_db()
    assert review.headline == 'Updated headline'


@pytest.mark.regression
def test_editing_closes_after_the_window(review, author):
    """
    Long enough to fix a typo, short enough that a review cannot be quietly
    rewritten after a company has responded to it.
    """
    from datetime import timedelta

    CompanyReview.objects.filter(pk=review.pk).update(
        created_at=timezone.now() - timedelta(days=2),
    )
    review.refresh_from_db()

    with pytest.raises(ValidationError):
        ReviewService.update(review, author, {'headline': 'Sneaky edit'})


def test_nobody_else_can_edit_a_review(review, plans):
    stranger = make_seeker('stranger@test.com')

    with pytest.raises(PermissionDenied):
        ReviewService.update(review, stranger, {'headline': 'Not mine'})


def test_withdrawing_is_a_soft_delete(review, author):
    """So a company response is not orphaned and moderation history survives."""
    ReviewService.delete(review, author)

    review.refresh_from_db()
    assert review.is_deleted is True
    assert CompanyReview.all_objects.filter(pk=review.pk).exists()


def test_a_withdrawn_review_leaves_the_public_list(review, author):
    ReviewService.delete(review, author)

    assert review not in ReviewService.published_for(review.company)


def test_withdrawing_frees_the_one_per_company_slot(review, author, company):
    """Having reviewed once and withdrawn should not lock someone out."""
    ReviewService.delete(review, author)

    assert post_review(author, company).pk


# --------------------------------------------------------------------------
# Aggregates
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_a_company_with_no_reviews_shows_no_rating(company):
    """
    Zero stars because nobody has reviewed it would be actively misleading.
    """
    summary = ReviewService.summary(company)

    assert summary['has_reviews'] is False
    assert 'overall' not in summary


def test_the_summary_averages_each_dimension(company, plans):
    post_review(make_seeker('a@test.com'), company,
                rating_culture=5, rating_management=5,
                rating_growth=5, rating_salary=5)
    post_review(make_seeker('b@test.com'), company,
                rating_culture=1, rating_management=1,
                rating_growth=1, rating_salary=1)

    summary = ReviewService.summary(company)

    assert summary['review_count'] == 2
    assert summary['ratings']['culture'] == 3.0
    assert summary['overall'] == 3.0


def test_the_summary_reports_recommendation_rate(company, plans):
    post_review(make_seeker('yes@test.com'), company, would_recommend=True)
    post_review(make_seeker('no@test.com'), company, would_recommend=False)

    assert ReviewService.summary(company)['recommend_pct'] == 50.0


def test_hidden_reviews_are_left_out_of_the_average(company, plans):
    post_review(make_seeker('visible@test.com'), company, rating_culture=5,
                rating_management=5, rating_growth=5, rating_salary=5)
    hidden = post_review(make_seeker('hidden@test.com'), company,
                         rating_culture=1, rating_management=1,
                         rating_growth=1, rating_salary=1)
    hidden.status = Status.UNDER_REVIEW
    hidden.save()

    assert ReviewService.summary(company)['overall'] == 5.0


# --------------------------------------------------------------------------
# Helpful votes
# --------------------------------------------------------------------------

def test_a_review_can_be_marked_helpful(review, plans):
    reader = make_seeker('reader@test.com')

    review, created = ReviewService.mark_helpful(review, reader)

    assert created is True
    assert review.helpful_count == 1


def test_marking_helpful_twice_counts_once(review, plans):
    reader = make_seeker('reader@test.com')

    ReviewService.mark_helpful(review, reader)
    review, created = ReviewService.mark_helpful(review, reader)

    assert created is False
    assert review.helpful_count == 1


@pytest.mark.regression
def test_nobody_can_upvote_their_own_review(review, author):
    """The cheapest way to game the ordering."""
    with pytest.raises(ValidationError):
        ReviewService.mark_helpful(review, author)


# --------------------------------------------------------------------------
# Moderation
# --------------------------------------------------------------------------

def report_from(review, email, plans_fixture=None):
    reporter = make_seeker(email)
    return ModerationService.report(review, reporter, Reason.FALSE)


@pytest.mark.regression
def test_one_report_does_not_hide_a_review(review, plans):
    """
    Otherwise a company could bury anything it disliked with a single
    click.
    """
    report_from(review, 'reporter1@test.com')

    review.refresh_from_db()
    assert review.status == Status.PUBLISHED


def test_reaching_the_threshold_hides_the_review(review, plans):
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'reporter{index}@test.com')

    review.refresh_from_db()
    assert review.status == Status.UNDER_REVIEW


def test_a_hidden_review_leaves_the_public_list(review, plans):
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'reporter{index}@test.com')

    assert review not in ReviewService.published_for(review.company)


def test_one_person_can_only_report_once(review, plans):
    reporter = make_seeker('serial@test.com')

    ModerationService.report(review, reporter, Reason.FALSE)
    _, created = ModerationService.report(review, reporter, Reason.SPAM)

    review.refresh_from_db()
    assert created is False
    assert review.report_count == 1


def test_nobody_can_report_their_own_review(review, author):
    with pytest.raises(ValidationError):
        ModerationService.report(review, author, Reason.FALSE)


def test_a_moderator_can_restore_a_review(review, plans):
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'reporter{index}@test.com')

    ModerationService.restore(review, 'Checked, review is fair')

    review.refresh_from_db()
    assert review.status == Status.PUBLISHED
    assert review.report_count == 0


@pytest.mark.regression
def test_restoring_resets_the_report_count(review, plans):
    """
    Otherwise one more report after a restore would hide it again
    immediately, and the moderator's decision would mean nothing.
    """
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'reporter{index}@test.com')
    ModerationService.restore(review)

    report_from(review, 'later@test.com')

    review.refresh_from_db()
    assert review.status == Status.PUBLISHED


def test_a_moderator_can_remove_a_review(review, plans):
    ModerationService.remove(review, 'Names an individual')

    review.refresh_from_db()
    assert review.status == Status.REMOVED
    assert review not in ReviewService.published_for(review.company)


def test_the_queue_holds_reviews_awaiting_a_decision(review, plans):
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'reporter{index}@test.com')

    assert review in ModerationService.queue()


def test_the_queue_leads_with_the_most_reported(company, plans):
    quiet = post_review(make_seeker('quiet-author@test.com'), company)
    loud = post_review(make_seeker('loud-author@test.com'), company,
                       headline='Second review')

    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(quiet, f'q{index}@test.com')
    for index in range(REPORT_HIDE_THRESHOLD + 2):
        report_from(loud, f'l{index}@test.com')

    assert ModerationService.queue().first() == loud


# --------------------------------------------------------------------------
# Company responses
# --------------------------------------------------------------------------

def test_a_recruiter_can_respond_to_a_review_of_their_company(review,
                                                              recruiter,
                                                              company):
    recruiter.company = company
    recruiter.save()

    response = ResponseService.respond(review, recruiter, 'Thanks for this.')

    assert response.review_id == review.pk
    assert response.responder_name == recruiter.full_name


@pytest.mark.regression
def test_a_recruiter_cannot_respond_to_another_companys_review(review,
                                                               recruiter):
    """Otherwise anyone with a recruiter account can speak for any company."""
    with pytest.raises(PermissionDenied):
        ResponseService.respond(review, recruiter, 'Not my company.')


@pytest.mark.regression
def test_a_company_can_only_respond_once(review, recruiter, company):
    """A second reply turns the page into an argument."""
    recruiter.company = company
    recruiter.save()
    ResponseService.respond(review, recruiter, 'First word.')

    with pytest.raises(ValidationError):
        ResponseService.respond(review, recruiter, 'Last word.')


def test_the_response_survives_the_responder_leaving(review, recruiter,
                                                     company):
    recruiter.company = company
    recruiter.save()
    response = ResponseService.respond(review, recruiter, 'Thanks for this.')
    name = response.responder_name

    recruiter.delete()
    response.refresh_from_db()

    assert response.responder is None
    assert response.responder_name == name


# --------------------------------------------------------------------------
# Interview experiences
# --------------------------------------------------------------------------

EXPERIENCE_DATA = {
    'role_applied': 'Backend Developer',
    'outcome': InterviewExperience.Outcome.OFFER,
    'difficulty': InterviewExperience.Difficulty.MODERATE,
    'rounds': 3,
    'weeks_to_decision': 2,
    'process': 'Screen, then a take-home, then two technical rounds.',
    'questions_asked': ['Design a rate limiter'],
    'was_experience_positive': True,
}


def test_an_interview_experience_can_be_shared(author, company):
    experience = InterviewExperienceService.create(
        author, company, EXPERIENCE_DATA,
    )

    assert experience.pk
    assert experience.status == Status.PUBLISHED


@pytest.mark.regression
def test_the_same_person_can_share_two_interviews_at_one_company(author,
                                                                 company):
    """
    Interviewing at the same company twice, years apart, is two genuinely
    different experiences - both worth reading.
    """
    InterviewExperienceService.create(author, company, EXPERIENCE_DATA)
    second = InterviewExperienceService.create(
        author, company, {**EXPERIENCE_DATA, 'role_applied': 'Senior Backend'},
    )

    assert second.pk
    assert InterviewExperienceService.published_for(company).count() == 2


def test_the_interview_summary_reports_the_shape_of_the_process(company, plans):
    InterviewExperienceService.create(
        make_seeker('i1@test.com'), company,
        {**EXPERIENCE_DATA, 'rounds': 3},
    )
    InterviewExperienceService.create(
        make_seeker('i2@test.com'), company,
        {**EXPERIENCE_DATA, 'rounds': 5,
         'outcome': InterviewExperience.Outcome.REJECTED},
    )

    summary = InterviewExperienceService.summary(company)

    assert summary['count'] == 2
    assert summary['avg_rounds'] == 4.0
    assert summary['offer_pct'] == 50.0


def test_a_company_with_no_interviews_says_so(company):
    assert InterviewExperienceService.summary(company)['has_experiences'] is False


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

def test_posting_a_review_through_the_api(auth, company):
    response = auth.post(
        f'/api/v1/reviews/companies/{company.pk}/',
        REVIEW_DATA, format='json',
    )

    assert response.status_code == 201
    assert response.data['overall_rating'] == 3.5


@pytest.mark.regression
def test_a_review_needs_both_pros_and_cons(auth, company):
    """
    A review that is only complaints or only praise is less useful than one
    that admits the other side exists.
    """
    response = auth.post(
        f'/api/v1/reviews/companies/{company.pk}/',
        {**REVIEW_DATA, 'cons': 'None'}, format='json',
    )

    assert response.status_code == 400
    assert 'cons' in response.data


def test_a_recruiter_cannot_review_a_company(recruiter_user, company):
    client = APIClient()
    client.force_authenticate(user=recruiter_user)

    response = client.post(
        f'/api/v1/reviews/companies/{company.pk}/',
        REVIEW_DATA, format='json',
    )

    assert response.status_code == 403


def test_the_summary_endpoint(auth, company, review):
    response = auth.get(
        f'/api/v1/reviews/companies/{company.pk}/summary/',
    )

    assert response.status_code == 200
    assert response.data['reviews']['review_count'] == 1
    assert 'interviews' in response.data


@pytest.mark.regression
def test_reporting_does_not_reveal_how_close_the_threshold_is(review, plans):
    """
    Telling a reporter the review is one report from hiding is an invitation
    to organise the rest.
    """
    reporter = make_seeker('reporter@test.com')
    client = APIClient()
    client.force_authenticate(user=reporter)

    response = client.post(
        f'/api/v1/reviews/{review.pk}/report/',
        {'reason': 'false'}, format='json',
    )

    assert response.status_code == 201
    body = str(response.data)
    assert 'report_count' not in body
    assert str(REPORT_HIDE_THRESHOLD) not in body


def test_marking_helpful_through_the_api(review, plans):
    reader = make_seeker('reader@test.com')
    client = APIClient()
    client.force_authenticate(user=reader)

    response = client.post(f'/api/v1/reviews/{review.pk}/helpful/')

    assert response.status_code == 201
    assert response.data['helpful_count'] == 1


def test_the_moderation_queue_is_admin_only(auth):
    assert auth.get('/api/v1/reviews/moderation/queue/').status_code == 403


def test_an_admin_can_see_the_moderation_queue(review, plans):
    admin = User.objects.create_superuser(
        email='mod@test.com', password='TestPass123!',
    )
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'r{index}@test.com')

    client = APIClient()
    client.force_authenticate(user=admin)
    response = client.get('/api/v1/reviews/moderation/queue/')

    assert response.status_code == 200
    assert response.data['count'] == 1


def test_an_admin_can_restore_through_the_api(review, plans):
    admin = User.objects.create_superuser(
        email='mod@test.com', password='TestPass123!',
    )
    for index in range(REPORT_HIDE_THRESHOLD):
        report_from(review, f'r{index}@test.com')

    client = APIClient()
    client.force_authenticate(user=admin)
    response = client.post(f'/api/v1/reviews/moderation/{review.pk}/restore/')

    review.refresh_from_db()
    assert response.status_code == 200
    assert review.status == Status.PUBLISHED


def test_an_unknown_moderation_decision_is_refused(review, plans):
    admin = User.objects.create_superuser(
        email='mod@test.com', password='TestPass123!',
    )
    client = APIClient()
    client.force_authenticate(user=admin)

    response = client.post(f'/api/v1/reviews/moderation/{review.pk}/burn/')

    assert response.status_code == 400


def test_reviews_need_a_login(company):
    assert APIClient().get(
        f'/api/v1/reviews/companies/{company.pk}/',
    ).status_code in (401, 403)
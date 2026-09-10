"""
Salary insights.

Two separate concerns, tested separately:

The statistics module is pure functions and gets exercised directly. The
service on top of it is where the privacy promise lives - people submit
salary data on the understanding that no aggregate can be traced back to
them, and K-anonymity is the mechanism that keeps that promise.
"""
from datetime import datetime
from decimal import Decimal

import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.career_intel import salary_algorithm as alg
from apps.career_intel.models import SalarySubmission
from apps.career_intel.salary_services import SalaryService

LAKH = 100_000


# --------------------------------------------------------------------------
# Percentiles and aggregates (no database)
# --------------------------------------------------------------------------

def test_an_empty_list_has_no_percentile():
    assert alg.calculate_percentile([], 50) is None
    assert alg.calculate_median([]) is None
    assert alg.calculate_aggregates([]) is None


def test_a_single_value_is_its_own_percentile():
    assert alg.calculate_percentile([42], 10) == 42
    assert alg.calculate_percentile([42], 90) == 42


def test_the_median_of_an_odd_list_is_the_middle_value():
    assert alg.calculate_median([1, 2, 3, 4, 5]) == 3


def test_the_median_of_an_even_list_is_interpolated():
    assert alg.calculate_median([1, 2, 3, 4]) == 2.5


@pytest.mark.regression
def test_percentiles_interpolate_between_ranks(): 
    """
    Regression: the salary modules sat at ~20% coverage. Linear interpolation
    is what makes p25 and p75 meaningful on small samples, which is all this
    dataset will have for a long time.
    """
    values = [10, 20, 30, 40, 50]

    assert alg.calculate_percentile(values, 0) == 10
    assert alg.calculate_percentile(values, 25) == 20
    assert alg.calculate_percentile(values, 50) == 30
    assert alg.calculate_percentile(values, 100) == 50


def test_percentiles_outside_the_range_clamp():
    values = [10, 20, 30]

    assert alg.calculate_percentile(values, -5) == 10
    assert alg.calculate_percentile(values, 150) == 30


def test_aggregates_cover_the_whole_distribution():
    salaries = [Decimal(str(n * LAKH)) for n in (5, 10, 15, 20, 25)]

    result = alg.calculate_aggregates(salaries)

    assert result['count'] == 5
    assert result['min'] == 5 * LAKH
    assert result['max'] == 25 * LAKH
    assert result['median'] == 15 * LAKH
    assert result['mean'] == 15 * LAKH
    assert result['p25'] < result['median'] < result['p75']


@pytest.mark.regression
def test_aggregates_expose_no_individual_row():
    """
    The whole point of aggregation here. Anything that reflected a single
    submission back would undo the anonymity people were promised.
    """
    result = alg.calculate_aggregates([Decimal(str(n * LAKH)) for n in range(1, 11)])

    assert set(result) == {
        'count', 'min', 'max', 'mean', 'median', 'p10', 'p25', 'p75', 'p90',
    }


# --------------------------------------------------------------------------
# Outlier trimming
# --------------------------------------------------------------------------

def test_impossible_salaries_are_dropped():
    """A typo of one zero either way would drag the median badly."""
    salaries = [Decimal('50000'), Decimal(str(10 * LAKH)), Decimal('999999999')]

    kept = alg.trim_outliers_simple(salaries)

    assert kept == [Decimal(str(10 * LAKH))]


def test_the_sane_bounds_are_configurable():
    salaries = [Decimal(str(n * LAKH)) for n in (5, 50)]

    kept = alg.trim_outliers_simple(salaries, min_inr=10 * LAKH, max_inr=100 * LAKH)

    assert kept == [Decimal(str(50 * LAKH))]


def test_iqr_trimming_removes_statistical_outliers():
    salaries = [Decimal(str(n * LAKH)) for n in (10, 11, 12, 13, 14, 200)]

    kept = alg.trim_outliers_iqr(salaries)

    assert Decimal(str(200 * LAKH)) not in kept
    assert len(kept) == 5


def test_iqr_trimming_leaves_tiny_samples_alone():
    """With three points the quartiles mean nothing, so trimming would be noise."""
    salaries = [Decimal(str(n * LAKH)) for n in (5, 10, 500)]

    assert alg.trim_outliers_iqr(salaries) == salaries


# --------------------------------------------------------------------------
# Display and positioning
# --------------------------------------------------------------------------

def test_rupees_render_as_lakhs():
    assert alg.format_inr_lpa(1_850_000) == '₹18.5 LPA'
    assert alg.format_inr_lpa(None) is None


@pytest.mark.parametrize('salary,expected', [
    (5 * LAKH, 'below_market'),
    (15 * LAKH, 'fair_market'),
    (28 * LAKH, 'above_market'),
    (40 * LAKH, 'top_of_market'),
])
def test_market_position_bands(salary, expected):
    percentiles = {
        'p25': 10 * LAKH, 'p75': 25 * LAKH, 'p90': 35 * LAKH,
    }

    assert alg.determine_market_position(salary, percentiles) == expected


# --------------------------------------------------------------------------
# Submission
# --------------------------------------------------------------------------

pytestmark_db = pytest.mark.django_db


def submission_data(**overrides):
    data = {
        'role_title': 'Backend Developer',
        'location_city': 'Bangalore',
        'experience_years_bucket': '2-5',
        'salary_inr': Decimal(str(15 * LAKH)),
        'effective_year': datetime.now().year,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_a_valid_submission_is_stored(seeker_user):
    submission = SalaryService.submit(seeker_user, submission_data())

    assert submission.pk
    assert submission.salary_inr == Decimal(str(15 * LAKH))


@pytest.mark.django_db
def test_an_absurdly_low_salary_is_rejected(seeker_user):
    with pytest.raises(ValidationError):
        SalaryService.submit(seeker_user, submission_data(salary_inr=Decimal('5000')))


@pytest.mark.django_db
def test_an_absurdly_high_salary_is_rejected(seeker_user):
    with pytest.raises(ValidationError):
        SalaryService.submit(
            seeker_user, submission_data(salary_inr=Decimal('999999999')),
        )


@pytest.mark.django_db
@pytest.mark.regression
def test_one_submission_per_role_and_year(seeker_user):
    """
    Without this, one person could submit the same salary repeatedly and
    move the median on their own.
    """
    SalaryService.submit(seeker_user, submission_data())

    with pytest.raises(ValidationError):
        SalaryService.submit(seeker_user, submission_data())


@pytest.mark.django_db
def test_the_same_role_in_a_different_year_is_allowed(seeker_user):
    year = datetime.now().year
    SalaryService.submit(seeker_user, submission_data(effective_year=year))

    second = SalaryService.submit(
        seeker_user, submission_data(effective_year=year - 1),
    )

    assert second.pk


@pytest.mark.django_db
def test_duplicate_detection_ignores_case(seeker_user):
    SalaryService.submit(seeker_user, submission_data(role_title='Backend Developer'))

    with pytest.raises(ValidationError):
        SalaryService.submit(
            seeker_user, submission_data(role_title='backend developer'),
        )


# --------------------------------------------------------------------------
# K-anonymity
# --------------------------------------------------------------------------

def seed_submissions(count, **overrides):
    """Raw rows, bypassing the service so per-user limits do not apply."""
    year = datetime.now().year
    for index in range(count):
        data = submission_data(**overrides)
        data['salary_inr'] = data['salary_inr'] + Decimal(str(index * 10_000))
        SalarySubmission.objects.create(effective_year=year, **{
            key: value for key, value in data.items() if key != 'effective_year'
        })


@pytest.mark.django_db
@pytest.mark.regression
def test_a_thin_sample_returns_no_numbers_at_all():
    """
    Four submissions plus a median is enough for someone who knows three of
    the four to derive the fourth. Below K, nothing is returned.
    """
    seed_submissions(4)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is False
    assert 'salary_range_inr' not in result
    assert result['k_threshold'] == 5


@pytest.mark.django_db
def test_reaching_the_threshold_unlocks_the_aggregate():
    seed_submissions(5)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is True
    assert result['sample_size'] == 5
    assert result['salary_range_inr']['median']
    assert 'LPA' in result['salary_range_lpa']['median']


@pytest.mark.django_db
@override_settings(SALARY_K_ANONYMITY=10)
def test_the_threshold_is_configurable():
    seed_submissions(6)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is False
    assert result['k_threshold'] == 10


@pytest.mark.django_db
@pytest.mark.regression
def test_trimming_can_push_a_sample_back_below_the_threshold():
    """
    Five submissions where two are junk leaves three real ones. The check has
    to run again after trimming, or the guarantee is only skin deep.
    """
    seed_submissions(3)
    for bad in ('1000', '999999999'):
        SalarySubmission.objects.create(
            **{**submission_data(), 'salary_inr': Decimal(bad)},
        )

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is False


@pytest.mark.django_db
def test_flagged_submissions_never_reach_an_aggregate():
    seed_submissions(5)
    SalarySubmission.objects.update(is_flagged=True)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is False


@pytest.mark.django_db
def test_filters_narrow_the_sample():
    seed_submissions(5, location_city='Bangalore')
    seed_submissions(5, location_city='Pune')

    blr = SalaryService.get_insights({'location_city': 'Bangalore'})
    both = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert blr['sample_size'] == 5
    assert both['sample_size'] == 10


@pytest.mark.django_db
def test_city_filtering_ignores_case():
    seed_submissions(5, location_city='Bangalore')

    result = SalaryService.get_insights({'location_city': 'bangalore'})

    assert result['has_data'] is True


@pytest.mark.django_db
def test_old_submissions_are_excluded_by_default():
    """Two-year window, so inflation does not distort the picture."""
    seed_submissions(5)
    SalarySubmission.objects.update(effective_year=datetime.now().year - 5)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert result['has_data'] is False


# --------------------------------------------------------------------------
# IP hashing
# --------------------------------------------------------------------------

from django.test import override_settings

from apps.career_intel.salary_services import client_ip, hash_ip

PEPPER = 'test-pepper-value'


@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_the_same_address_always_hashes_the_same():
    """Rate limiting depends on it being deterministic."""
    assert hash_ip('203.0.113.7') == hash_ip('203.0.113.7')


@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_different_addresses_hash_differently():
    assert hash_ip('203.0.113.7') != hash_ip('203.0.113.8')


@pytest.mark.regression
@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_the_hash_does_not_contain_the_address():
    """
    Regression: the blueprint asks for IP hashing on salary submissions and
    the raw address was simply not stored at all - meaning no rate limiting
    either. Storing it in the clear would have been worse.
    """
    hashed = hash_ip('203.0.113.7')

    assert '203.0.113.7' not in hashed
    assert len(hashed) == 64


@pytest.mark.regression
def test_a_different_pepper_gives_a_different_hash():
    """
    The point of the pepper. sha256 of an IPv4 address is reversible with a
    table anyone can build in an afternoon; without a secret in the mix,
    hashing the address would not be anonymising it.
    """
    with override_settings(SALARY_IP_PEPPER='pepper-one'):
        first = hash_ip('203.0.113.7')
    with override_settings(SALARY_IP_PEPPER='pepper-two'):
        second = hash_ip('203.0.113.7')

    assert first != second


@override_settings(SALARY_IP_PEPPER='')
def test_no_pepper_means_no_hash_rather_than_a_weak_one():
    """
    A misconfigured deployment should lose rate limiting, not gain a
    reversible hash of every submitter's address.
    """
    assert hash_ip('203.0.113.7') == ''


@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_a_missing_address_hashes_to_nothing():
    assert hash_ip(None) == ''
    assert hash_ip('') == ''


# --------------------------------------------------------------------------
# Reading the client address
# --------------------------------------------------------------------------

class FakeRequest:
    def __init__(self, **meta):
        self.META = meta


@pytest.mark.regression
def test_the_forwarded_address_wins_over_the_socket():
    """Behind Nginx, REMOTE_ADDR is the proxy - every submission would
    otherwise share one hash and hit the device limit immediately."""
    request = FakeRequest(
        HTTP_X_FORWARDED_FOR='203.0.113.7, 10.0.0.1',
        REMOTE_ADDR='10.0.0.1',
    )

    assert client_ip(request) == '203.0.113.7'


def test_the_socket_address_is_used_without_a_proxy():
    assert client_ip(FakeRequest(REMOTE_ADDR='203.0.113.7')) == '203.0.113.7'


def test_a_missing_request_is_handled():
    assert client_ip(None) is None


# --------------------------------------------------------------------------
# Per-device limit
# --------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_the_address_is_stored_hashed_not_raw(seeker_user):
    submission = SalaryService.submit(
        seeker_user, submission_data(), ip_address='203.0.113.7',
    )

    assert submission.submitter_ip_hash == hash_ip('203.0.113.7')
    assert '203.0.113.7' not in submission.submitter_ip_hash


@pytest.mark.django_db
@pytest.mark.regression
@override_settings(SALARY_IP_PEPPER=PEPPER, SALARY_MAX_SUBMISSIONS_PER_IP=2)
def test_one_device_cannot_submit_without_limit(seeker_user, plans):
    """
    Blueprint: "submission-rate limiting per device". Without it, one person
    could move the median for a whole role and city on their own.
    """
    from apps.accounts.models import User

    for index in range(2):
        user = User.objects.create_user(
            email=f'submitter{index}@test.com', password='TestPass123!',
        )
        SalaryService.submit(
            user, submission_data(), ip_address='203.0.113.7',
        )

    third = User.objects.create_user(
        email='third@test.com', password='TestPass123!',
    )

    with pytest.raises(ValidationError):
        SalaryService.submit(third, submission_data(), ip_address='203.0.113.7')


@pytest.mark.django_db
@override_settings(SALARY_IP_PEPPER=PEPPER, SALARY_MAX_SUBMISSIONS_PER_IP=1)
def test_a_different_device_is_unaffected(seeker_user, plans):
    from apps.accounts.models import User

    SalaryService.submit(seeker_user, submission_data(),
                         ip_address='203.0.113.7')

    other = User.objects.create_user(
        email='elsewhere@test.com', password='TestPass123!',
    )
    submission = SalaryService.submit(
        other, submission_data(), ip_address='198.51.100.4',
    )

    assert submission.pk


@pytest.mark.django_db
@override_settings(SALARY_IP_PEPPER=PEPPER, SALARY_MAX_SUBMISSIONS_PER_IP=1,
                   SALARY_IP_WINDOW_HOURS=24)
def test_the_limit_is_a_rolling_window(seeker_user, plans):
    """Yesterday's submission should not block today's."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.accounts.models import User

    old = SalaryService.submit(seeker_user, submission_data(),
                               ip_address='203.0.113.7')
    SalarySubmission.objects.filter(pk=old.pk).update(
        submitted_at=timezone.now() - timedelta(hours=25),
    )

    other = User.objects.create_user(
        email='today@test.com', password='TestPass123!',
    )
    submission = SalaryService.submit(
        other, submission_data(), ip_address='203.0.113.7',
    )

    assert submission.pk


@pytest.mark.django_db
@override_settings(SALARY_IP_PEPPER='')
def test_without_a_pepper_submissions_still_work(seeker_user):
    """Losing rate limiting is bad; refusing every submission is worse."""
    submission = SalaryService.submit(
        seeker_user, submission_data(), ip_address='203.0.113.7',
    )

    assert submission.pk
    assert submission.submitter_ip_hash == ''


@pytest.mark.django_db
@override_settings(SALARY_IP_PEPPER=PEPPER)
def test_a_submission_without_an_address_is_allowed(seeker_user):
    """Management commands and imports have no request behind them."""
    submission = SalaryService.submit(seeker_user, submission_data())

    assert submission.submitter_ip_hash == ''


# --------------------------------------------------------------------------
# Re-identification defences
# --------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.regression
def test_the_exact_minimum_and_maximum_are_not_published():
    """
    Regression: min and max were published. Neither is an aggregate - each
    is one person's exact salary, and two queries differing by one filter
    recover it directly.
    """
    seed_submissions(6)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert 'min' not in result['salary_range_inr']
    assert 'max' not in result['salary_range_inr']
    assert 'min' not in result['salary_range_lpa']
    assert 'max' not in result['salary_range_lpa']


@pytest.mark.django_db
@pytest.mark.regression
def test_published_figures_are_rounded_to_a_band():
    """
    At these sample sizes a percentile lands on a person: with five
    submissions p25 is values[1] and the median is values[2]. Rounding is
    what makes the published number describe a range instead.
    """
    from apps.career_intel.salary_algorithm import PUBLISH_ROUNDING_INR

    seed_submissions(6)

    figures = SalaryService.get_insights(
        {'role_title': 'Backend Developer'},
    )['salary_range_inr']

    for name, value in figures.items():
        assert value % PUBLISH_ROUNDING_INR == 0, f'{name} was not rounded'


@pytest.mark.django_db
@pytest.mark.regression
def test_a_published_figure_never_points_at_one_submission():
    """
    What rounding actually buys, stated precisely.

    It does not stop a published figure coinciding with somebody's salary -
    real salaries cluster on round numbers, so a banded median will
    sometimes land exactly on one. What it does is make that coincidence
    ambiguous: several submissions fall inside the band, so the figure
    identifies a group rather than a person.

    The limitation is real and worth stating: when a group's salaries are
    spread much wider than the band, the ambiguity thins out. That is
    recorded in the re-identification assessment rather than hidden here.
    """
    from apps.career_intel.salary_algorithm import PUBLISH_ROUNDING_INR

    seed_submissions(7)

    submitted = [
        float(value) for value in
        SalarySubmission.objects.values_list('salary_inr', flat=True)
    ]
    published = SalaryService.get_insights(
        {'role_title': 'Backend Developer'},
    )['salary_range_inr']

    half_band = PUBLISH_ROUNDING_INR / 2

    for name, figure in published.items():
        nearby = [
            salary for salary in submitted
            if abs(salary - figure) <= half_band
        ]
        assert len(nearby) != 1, (
            f'{name} = {figure} matches exactly one submission, '
            f'which makes it that person\'s salary'
        )


@pytest.mark.django_db
def test_the_rounded_median_still_describes_the_data():
    """
    Privacy that destroys the number is not a trade worth making - the
    figure has to stay useful for a negotiation.
    """
    from apps.career_intel.salary_algorithm import PUBLISH_ROUNDING_INR

    seed_submissions(6)

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})
    raw = SalaryService._raw_percentiles({'role_title': 'Backend Developer'})

    drift = abs(result['salary_range_inr']['median'] - raw['median'])
    assert drift <= PUBLISH_ROUNDING_INR / 2


@pytest.mark.django_db
@pytest.mark.regression
def test_a_differencing_attack_does_not_isolate_one_person():
    """
    The attack the K threshold exists to stop: query a group, query the
    group minus one attribute, compare. With min and max gone and the rest
    banded, the difference no longer resolves to an individual.
    """
    seed_submissions(6, experience_years_bucket='2-5')
    seed_submissions(5, experience_years_bucket='5-10')

    everyone = SalaryService.get_insights({'role_title': 'Backend Developer'})
    juniors = SalaryService.get_insights({
        'role_title': 'Backend Developer',
        'experience_years_bucket': '2-5',
    })

    # Both sets are large enough to publish, and neither exposes an endpoint
    # of its distribution for the other to be subtracted from.
    assert everyone['has_data'] and juniors['has_data']
    assert set(everyone['salary_range_inr']) == {'p25', 'median', 'p75', 'mean'}


@pytest.mark.django_db
@pytest.mark.regression
def test_the_comparison_path_uses_unrounded_figures(seeker_user):
    """
    Market position is decided server-side and only a category comes back,
    so it uses the full distribution. Banding it would misplace anyone
    sitting close to a boundary.
    """
    seed_submissions(6)

    raw = SalaryService._raw_percentiles({'role_title': 'Backend Developer'})

    assert 'min' in raw and 'max' in raw and 'p90' in raw


@pytest.mark.django_db
def test_the_raw_percentiles_never_reach_a_response(seeker_user):
    seed_submissions(6)
    SalaryService.submit(seeker_user, submission_data(role_title='Other Role'))

    result = SalaryService.get_insights({'role_title': 'Backend Developer'})

    assert 'p90' not in result['salary_range_inr']
    assert 'p10' not in result['salary_range_inr']
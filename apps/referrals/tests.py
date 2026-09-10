"""
Referral system.

This is the part of the product that hands out free Pro time, so the fraud
rules are the important half: self-referral, double-referral, farmed
accounts and the monthly cap. Those are what stop the reward budget from
being drained by someone with a spreadsheet.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.referrals.models import Referral, ReferralReward
from apps.referrals.services import (
    MAX_REWARDS_PER_REFERRER_PER_MONTH,
    REFERRER_PRO_DAYS,
    ReferralService,
)

pytestmark = pytest.mark.django_db


def make_user(email, plans=None):
    """
    Note the domains used below. The conftest `seeker_user` is on test.com,
    which is a private domain as far as the fraud rules are concerned, so
    every referee here gets its own domain - otherwise the shared-domain
    check fires and nothing reaches PENDING.
    """
    return User.objects.create_user(
        email=email,
        password="TestPass123!",
        role=User.Role.SEEKER,
        is_email_verified=True,
    )


@pytest.fixture
def referrer(seeker_user):
    return seeker_user


@pytest.fixture
def referee(plans):
    return make_user("referee@referee-domain.com")


@pytest.fixture
def code(referrer):
    return ReferralService.get_or_create_code(referrer)


def paid_transaction(user, plans, amount="499"):
    """A successful payment, which is what triggers a conversion."""
    from apps.payments.models import PaymentTransaction

    return PaymentTransaction.objects.create(
        user=user,
        plan=plans["pro"],
        amount_inr=Decimal(amount),
        status=PaymentTransaction.Status.SUCCESS,
        razorpay_order_id=f"order_{user.id}",
    )


# --------------------------------------------------------------------------
# Codes
# --------------------------------------------------------------------------


@pytest.mark.regression
def test_a_user_gets_one_stable_code(referrer):
    """Regression: referrals/services.py sat at 33% coverage."""
    first = ReferralService.get_or_create_code(referrer)
    second = ReferralService.get_or_create_code(referrer)

    assert first.pk == second.pk
    assert first.code


def test_codes_are_unique_per_user(referrer, plans):
    other = make_user("other@other-domain.com")

    assert (
        ReferralService.get_or_create_code(referrer).code
        != ReferralService.get_or_create_code(other).code
    )


def test_clicks_are_counted(code):
    ReferralService.track_click(code.code)
    ReferralService.track_click(code.code)

    code.refresh_from_db()
    assert code.click_count == 2


def test_click_tracking_is_case_and_whitespace_tolerant(code):
    """The code arrives from a URL a human may have retyped."""
    ReferralService.track_click(f"  {code.code.lower()}  ")

    code.refresh_from_db()
    assert code.click_count == 1


def test_clicking_an_unknown_code_is_harmless(code):
    ReferralService.track_click("NOPE123")
    ReferralService.track_click(None)

    code.refresh_from_db()
    assert code.click_count == 0


def test_an_inactive_code_stops_counting(code):
    code.is_active = False
    code.save(update_fields=["is_active"])

    ReferralService.track_click(code.code)

    code.refresh_from_db()
    assert code.click_count == 0


# --------------------------------------------------------------------------
# Signup linking
# --------------------------------------------------------------------------


def test_a_valid_code_links_the_signup(code, referee):
    referral = ReferralService.attach_referral_on_signup(referee, code.code)

    assert referral is not None
    assert referral.status == Referral.Status.PENDING
    assert referral.referrer == code.user
    assert referral.referee == referee

    code.refresh_from_db()
    assert code.signup_count == 1


def test_an_unknown_code_is_ignored_silently(referee):
    """Signup must never fail because of a bad referral code."""
    assert ReferralService.attach_referral_on_signup(referee, "NOPE123") is None


def test_no_code_is_ignored(referee):
    assert ReferralService.attach_referral_on_signup(referee, "") is None
    assert ReferralService.attach_referral_on_signup(referee, None) is None


@pytest.mark.regression
def test_nobody_can_refer_themselves(code, referrer):
    """The simplest way to farm rewards, so it is checked first."""
    assert ReferralService.attach_referral_on_signup(referrer, code.code) is None
    assert not Referral.objects.filter(referee=referrer).exists()


@pytest.mark.regression
def test_a_user_can_only_be_referred_once(code, referee, plans):
    """Otherwise one signup could pay out to several referrers."""
    ReferralService.attach_referral_on_signup(referee, code.code)

    second_referrer = make_user("second@second-domain.com")
    second_code = ReferralService.get_or_create_code(second_referrer)

    assert (
        ReferralService.attach_referral_on_signup(
            referee,
            second_code.code,
        )
        is None
    )
    assert Referral.objects.filter(referee=referee).count() == 1


@pytest.mark.regression
def test_a_shared_private_domain_is_flagged(plans):
    """
    Two accounts on the same company domain referring each other looks like
    farmed accounts. Flagged rather than blocked - it can be legitimate.
    """
    referrer = make_user("a@acmecorp.com")
    referee = make_user("b@acmecorp.com")
    code = ReferralService.get_or_create_code(referrer)

    referral = ReferralService.attach_referral_on_signup(referee, code.code)

    assert referral.is_flagged is True
    assert referral.status == Referral.Status.FLAGGED


def test_a_shared_public_domain_is_not_suspicious(plans):
    """Half the internet is on gmail; sharing it means nothing."""
    referrer = make_user("a@gmail.com")
    referee = make_user("b@gmail.com")
    code = ReferralService.get_or_create_code(referrer)

    referral = ReferralService.attach_referral_on_signup(referee, code.code)

    assert referral.is_flagged is False
    assert referral.status == Referral.Status.PENDING


def test_the_signup_ip_is_recorded(code, referee):
    referral = ReferralService.attach_referral_on_signup(
        referee,
        code.code,
        ip_address="203.0.113.7",
    )

    assert referral.referee_signup_ip == "203.0.113.7"


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


def test_a_first_payment_converts_the_referral(code, referee, plans):
    ReferralService.attach_referral_on_signup(referee, code.code)
    txn = paid_transaction(referee, plans)

    referral = ReferralService.trigger_conversion(referee, txn)

    assert referral.status == Referral.Status.CONVERTED
    assert referral.converted_amount_inr == Decimal("499")

    code.refresh_from_db()
    assert code.paid_count == 1


def test_conversion_rewards_both_sides(code, referee, plans):
    ReferralService.attach_referral_on_signup(referee, code.code)
    ReferralService.trigger_conversion(referee, paid_transaction(referee, plans))

    referrer_reward = ReferralReward.objects.get(user=code.user)
    referee_reward = ReferralReward.objects.get(user=referee)

    assert referrer_reward.kind == ReferralReward.Kind.PRO_EXTENSION
    assert referrer_reward.value["days"] == REFERRER_PRO_DAYS
    assert referee_reward.kind == ReferralReward.Kind.DISCOUNT
    assert referee_reward.value["code"].startswith("REF-")


@pytest.mark.regression
def test_only_the_first_payment_counts(code, referee, plans):
    """
    Otherwise a referrer would be paid again every month the referee renews.
    """
    ReferralService.attach_referral_on_signup(referee, code.code)
    first = paid_transaction(referee, plans)
    ReferralService.trigger_conversion(referee, first)

    from apps.payments.models import PaymentTransaction

    second = PaymentTransaction.objects.create(
        user=referee,
        plan=plans["pro"],
        amount_inr=Decimal("499"),
        status=PaymentTransaction.Status.SUCCESS,
        razorpay_order_id="order_second",
    )

    assert ReferralService.trigger_conversion(referee, second) is None
    assert ReferralReward.objects.filter(user=code.user).count() == 1


def test_a_payment_without_a_referral_converts_nothing(referee, plans):
    assert (
        ReferralService.trigger_conversion(
            referee,
            paid_transaction(referee, plans),
        )
        is None
    )


def test_a_flagged_referral_does_not_convert(plans):
    referrer = make_user("a@acmecorp.com")
    referee = make_user("b@acmecorp.com")
    code = ReferralService.get_or_create_code(referrer)
    ReferralService.attach_referral_on_signup(referee, code.code)

    result = ReferralService.trigger_conversion(
        referee,
        paid_transaction(referee, plans),
    )

    assert result is None
    assert not ReferralReward.objects.exists()


@pytest.mark.regression
def test_the_monthly_cap_stops_reward_farming(code, referrer, plans):
    """
    Without a cap, one person with a mailing list could mint unlimited free
    Pro time. The referral over the line is flagged, not silently dropped.
    """
    for index in range(MAX_REWARDS_PER_REFERRER_PER_MONTH):
        Referral.objects.create(
            referrer=referrer,
            referee=make_user(f"converted{index}@converted{index}.com"),
            code_used=code,
            status=Referral.Status.CONVERTED,
            converted_at=timezone.now(),
        )

    late = make_user("late@late-domain.com")
    ReferralService.attach_referral_on_signup(late, code.code)

    result = ReferralService.trigger_conversion(
        late,
        paid_transaction(late, plans),
    )

    assert result is None
    referral = Referral.objects.get(referee=late)
    assert referral.is_flagged is True
    assert "cap" in referral.flag_reason.lower()


def test_old_conversions_do_not_count_towards_the_cap(code, referrer, plans):
    """The cap is per rolling month, not per lifetime."""
    for index in range(MAX_REWARDS_PER_REFERRER_PER_MONTH):
        referral = Referral.objects.create(
            referrer=referrer,
            referee=make_user(f"old{index}@old{index}.com"),
            code_used=code,
            status=Referral.Status.CONVERTED,
        )
        Referral.objects.filter(pk=referral.pk).update(
            converted_at=timezone.now() - timedelta(days=60),
        )

    fresh = make_user("fresh@fresh-domain.com")
    ReferralService.attach_referral_on_signup(fresh, code.code)

    result = ReferralService.trigger_conversion(
        fresh,
        paid_transaction(fresh, plans),
    )

    assert result is not None
    assert result.status == Referral.Status.CONVERTED


# --------------------------------------------------------------------------
# Redeeming a reward
# --------------------------------------------------------------------------


def grant_extension(user, code, plans):
    """A granted Pro-extension reward. ReferralReward.referral is NOT NULL."""
    referral = Referral.objects.create(
        referrer=user,
        referee=make_user(f"rewarded-{user.id}@rewarded.com"),
        code_used=code,
        status=Referral.Status.CONVERTED,
        converted_at=timezone.now(),
    )
    return ReferralReward.objects.create(
        referral=referral,
        user=user,
        kind=ReferralReward.Kind.PRO_EXTENSION,
        value={"days": REFERRER_PRO_DAYS},
        status=ReferralReward.Status.GRANTED,
        granted_at=timezone.now(),
        expires_at=timezone.now() + timedelta(days=90),
    )


@pytest.fixture
def granted_extension(referrer, code, plans):
    from apps.payments.models import Subscription

    sub = referrer.subscriptions.order_by("-created_at").first()
    sub.status = Subscription.Status.ACTIVE
    sub.trial_ends_at = None
    sub.current_period_end = timezone.now() + timedelta(days=10)
    sub.save()

    return referrer, sub, grant_extension(referrer, code, plans)


def test_applying_a_reward_extends_the_subscription(granted_extension):
    user, sub, reward = granted_extension
    original_end = sub.current_period_end

    ReferralService.apply_pro_extension_reward(user, reward.id)

    sub.refresh_from_db()
    reward.refresh_from_db()
    assert sub.current_period_end == original_end + timedelta(days=REFERRER_PRO_DAYS)
    assert reward.status == ReferralReward.Status.USED


@pytest.mark.regression
def test_a_reward_can_only_be_redeemed_once(granted_extension):
    user, _, reward = granted_extension
    ReferralService.apply_pro_extension_reward(user, reward.id)

    with pytest.raises(ValidationError):
        ReferralService.apply_pro_extension_reward(user, reward.id)


def test_an_expired_reward_is_refused(granted_extension):
    user, _, reward = granted_extension
    ReferralReward.objects.filter(pk=reward.pk).update(
        expires_at=timezone.now() - timedelta(days=1),
    )

    with pytest.raises(ValidationError):
        ReferralService.apply_pro_extension_reward(user, reward.id)


def test_a_reward_cannot_be_redeemed_by_someone_else(granted_extension, plans):
    _, _, reward = granted_extension
    stranger = make_user("stranger@stranger-domain.com")

    with pytest.raises(ValidationError):
        ReferralService.apply_pro_extension_reward(stranger, reward.id)


def test_extending_without_an_active_subscription_is_refused(referrer, code, plans):
    """The signup trial is TRIALING, not ACTIVE, so there is nothing to extend."""
    reward = grant_extension(referrer, code, plans)

    with pytest.raises(ValidationError):
        ReferralService.apply_pro_extension_reward(referrer, reward.id)


# --------------------------------------------------------------------------
# Read APIs
# --------------------------------------------------------------------------


def test_stats_report_the_funnel(code, referee, plans):
    ReferralService.track_click(code.code)
    ReferralService.attach_referral_on_signup(referee, code.code)
    ReferralService.trigger_conversion(referee, paid_transaction(referee, plans))

    stats = ReferralService.get_my_stats(code.user)

    assert stats["click_count"] == 1
    assert stats["signup_count"] == 1
    assert stats["paid_count"] == 1
    assert stats["conversion_rate"] == 100.0
    assert code.code in stats["share_url"]


def test_conversion_rate_is_zero_with_no_signups(referrer):
    """Dividing by zero signups would be an unhandled crash on a new account."""
    assert ReferralService.get_my_stats(referrer)["conversion_rate"] == 0.0


def test_the_leaderboard_ranks_by_conversions(code, referrer, plans):
    for index in range(3):
        Referral.objects.create(
            referrer=referrer,
            referee=make_user(f"lb{index}@lb{index}.com"),
            code_used=code,
            status=Referral.Status.CONVERTED,
            converted_at=timezone.now(),
        )

    board = ReferralService.get_leaderboard()

    assert board[0]["referrer__email"] == referrer.email
    assert board[0]["conversion_count"] == 3


def test_the_leaderboard_only_covers_the_last_30_days(code, referrer, plans):
    referral = Referral.objects.create(
        referrer=referrer,
        referee=make_user("stale@stale-domain.com"),
        code_used=code,
        status=Referral.Status.CONVERTED,
    )
    Referral.objects.filter(pk=referral.pk).update(
        converted_at=timezone.now() - timedelta(days=60),
    )

    assert ReferralService.get_leaderboard() == []

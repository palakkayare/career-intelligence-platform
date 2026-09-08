"""
Platform metrics for the admin dashboard.

Every figure here is computed live from the operational tables. That is the
right trade-off at this scale - the numbers are always current and there is
no aggregation pipeline to keep correct - but it will not hold forever. Once
the tables get large these become nightly rollups into a summary table.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

# A yearly plan is worth a twelfth of its price each month. Without this,
# annual subscribers would spike MRR in the month they pay and vanish from it
# for the next eleven.
MONTHS_PER_YEAR = Decimal('12')


class RevenueMetrics:
    """Subscription and revenue figures."""

    @staticmethod
    def _monthly_value(subscription):
        plan = subscription.plan
        if plan.billing_period == plan.BillingPeriod.YEARLY:
            return plan.price_inr / MONTHS_PER_YEAR
        return plan.price_inr

    @classmethod
    def active_paid_subscriptions(cls):
        """
        Paying subscribers only.

        Trials are excluded on purpose: they contribute nothing yet, and
        counting them would make MRR jump on signup and fall on conversion
        failure, which reads exactly backwards.
        """
        from apps.payments.models import Plan, Subscription

        now = timezone.now()
        return (
            Subscription.objects
            .filter(
                status__in=[
                    Subscription.Status.ACTIVE,
                    Subscription.Status.CANCELLED,  # paid through period end
                ],
                current_period_end__gt=now,
            )
            .exclude(plan__tier=Plan.Tier.FREE)
            .select_related('plan')
        )

    @classmethod
    def mrr(cls):
        """Monthly recurring revenue, in rupees."""
        total = sum(
            (cls._monthly_value(s) for s in cls.active_paid_subscriptions()),
            Decimal('0'),
        )
        return total.quantize(Decimal('0.01'))

    @classmethod
    def arr(cls):
        return (cls.mrr() * MONTHS_PER_YEAR).quantize(Decimal('0.01'))

    @classmethod
    def churn_rate(cls, days=30):
        """
        Share of subscribers who cancelled during the window, as a percent.

        Denominator is everyone who was subscribed at the start of the window,
        which is the cancellers plus those still active. Measuring against
        only the survivors would understate it.
        """
        from apps.payments.models import Subscription

        cutoff = timezone.now() - timedelta(days=days)

        cancelled = Subscription.objects.filter(
            cancelled_at__gte=cutoff,
        ).count()
        surviving = cls.active_paid_subscriptions().filter(
            cancelled_at__isnull=True,
        ).count()

        base = cancelled + surviving
        if base == 0:
            return Decimal('0.00')

        return (Decimal(cancelled) / Decimal(base) * 100).quantize(Decimal('0.01'))

    @classmethod
    def subscribers_by_plan(cls):
        counts = {}
        for subscription in cls.active_paid_subscriptions():
            counts[subscription.plan.name] = counts.get(subscription.plan.name, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    @classmethod
    def trial_conversion_rate(cls):
        """
        Percent of finished trials that turned into a paid subscription.

        Trials still running are excluded - they have not had their chance yet
        and would drag the rate down for no reason.
        """
        from apps.payments.models import Subscription

        now = timezone.now()
        finished = Subscription.objects.filter(
            trial_ends_at__isnull=False, trial_ends_at__lt=now,
        )
        total = finished.count()
        if total == 0:
            return Decimal('0.00')

        converted = finished.filter(
            transactions__status='success',
        ).distinct().count()

        return (Decimal(converted) / Decimal(total) * 100).quantize(Decimal('0.01'))

    @classmethod
    def revenue_in_period(cls, days=30):
        from apps.payments.models import PaymentTransaction, Refund

        cutoff = timezone.now() - timedelta(days=days)

        collected = PaymentTransaction.objects.filter(
            status=PaymentTransaction.Status.SUCCESS, created_at__gte=cutoff,
        ).aggregate(total=Sum('amount_inr'))['total'] or Decimal('0')

        refunded = Refund.objects.filter(
            created_at__gte=cutoff,
        ).exclude(status=Refund.Status.FAILED).aggregate(
            total=Sum('amount_inr'),
        )['total'] or Decimal('0')

        return {
            'collected': collected,
            'refunded': refunded,
            'net': collected - refunded,
        }

    @classmethod
    def summary(cls):
        return {
            'mrr': cls.mrr(),
            'arr': cls.arr(),
            'active_paid_subscribers': cls.active_paid_subscriptions().count(),
            'churn_rate_30d': cls.churn_rate(30),
            'trial_conversion_rate': cls.trial_conversion_rate(),
            'subscribers_by_plan': cls.subscribers_by_plan(),
            'revenue_30d': cls.revenue_in_period(30),
        }


class ActivityMetrics:
    """Platform health: who is here and what they are doing."""

    @staticmethod
    def _active_users_since(cutoff):
        from apps.accounts.models import LoginHistory

        return LoginHistory.objects.filter(
            status=LoginHistory.Status.SUCCESS,
            created_at__gte=cutoff,
            user__isnull=False,
        ).values('user').distinct().count()

    @classmethod
    def dau(cls):
        return cls._active_users_since(timezone.now() - timedelta(days=1))

    @classmethod
    def mau(cls):
        return cls._active_users_since(timezone.now() - timedelta(days=30))

    @classmethod
    def stickiness(cls):
        """
        DAU/MAU as a percent - roughly, how many days a month a user shows up.
        Above ~20% is considered healthy for a non-social product.
        """
        mau = cls.mau()
        if mau == 0:
            return Decimal('0.00')
        return (Decimal(cls.dau()) / Decimal(mau) * 100).quantize(Decimal('0.01'))

    @staticmethod
    def daily_series(queryset, date_field, days=30):
        """Counts per day, oldest first, with empty days filled in as zero."""
        cutoff = timezone.now() - timedelta(days=days)

        rows = (
            queryset
            .filter(**{f'{date_field}__gte': cutoff})
            .annotate(day=TruncDate(date_field))
            .values('day')
            .annotate(count=Count('id'))
        )
        counts = {row['day']: row['count'] for row in rows}

        today = timezone.now().date()
        return [
            {
                'date': (today - timedelta(days=offset)).isoformat(),
                'count': counts.get(today - timedelta(days=offset), 0),
            }
            for offset in reversed(range(days))
        ]

    @classmethod
    def applications_per_day(cls, days=30):
        from apps.applications.models import Application

        # all_objects: a withdrawn application still happened, and removing it
        # from history would silently rewrite past days.
        return cls.daily_series(Application.all_objects, 'submitted_at', days)

    @classmethod
    def signups_per_day(cls, days=30):
        from apps.accounts.models import User

        return cls.daily_series(User.objects, 'date_joined', days)

    @classmethod
    def totals(cls):
        from apps.accounts.models import User
        from apps.applications.models import Application
        from apps.jobs.models import Job

        users = User.objects.aggregate(
            total=Count('id'),
            seekers=Count('id', filter=Q(role=User.Role.SEEKER)),
            recruiters=Count('id', filter=Q(role=User.Role.RECRUITER)),
        )
        return {
            'users': users,
            'active_jobs': Job.objects.filter(status=Job.Status.ACTIVE).count(),
            'total_applications': Application.all_objects.count(),
        }

    @classmethod
    def summary(cls):
        return {
            'dau': cls.dau(),
            'mau': cls.mau(),
            'stickiness': cls.stickiness(),
            'totals': cls.totals(),
            'applications_per_day': cls.applications_per_day(),
            'signups_per_day': cls.signups_per_day(),
        }


def dashboard_snapshot():
    """Everything the admin dashboard needs, in one call."""
    return {
        'generated_at': timezone.now().isoformat(),
        'revenue': RevenueMetrics.summary(),
        'activity': ActivityMetrics.summary(),
    }
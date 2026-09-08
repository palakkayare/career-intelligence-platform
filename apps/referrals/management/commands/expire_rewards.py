"""
Management command: flip granted-but-expired referral rewards to `expired`.

Place at: apps/referrals/management/commands/expire_rewards.py
(create the `management/` and `management/commands/` folders with empty
__init__.py files if they don't exist yet)

Run manually:   python manage.py expire_rewards
Dry run:        python manage.py expire_rewards --dry-run

Why this exists
---------------
ReferralReward.is_usable() already checks expires_at, so the API never lets an
expired reward be redeemed. But the `status` column stays at 'granted' forever,
and that column is what the UI renders as its badge — so a dead reward shows a
green "Available" chip. The read-path fix in the my-rewards view keeps a user's
own list honest; this command keeps every other consumer (admin, leaderboard,
analytics, exports) honest too.

Schedule it daily once Celery beat is up.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.referrals.models import ReferralReward


class Command(BaseCommand):
    help = "Mark granted referral rewards whose expires_at has passed as expired."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        stale = ReferralReward.objects.filter(
            status=ReferralReward.Status.GRANTED,
            expires_at__lt=now,
        )

        count = stale.count()

        if count == 0:
            self.stdout.write("Nothing to expire.")
            return

        if options["dry_run"]:
            self.stdout.write(f"Would expire {count} reward(s):")
            # Small result set by nature — one row per reward that outlived its
            # window since the last run. Listing them is cheap and makes the
            # dry run actually useful.
            for r in stale.select_related("user")[:50]:
                self.stdout.write(
                    f"  id={r.id} user={r.user} kind={r.kind} expired={r.expires_at:%Y-%m-%d}"
                )
            if count > 50:
                self.stdout.write(f"  ... and {count - 50} more")
            return

        updated = stale.update(status=ReferralReward.Status.EXPIRED)
        self.stdout.write(self.style.SUCCESS(f"Expired {updated} reward(s)."))
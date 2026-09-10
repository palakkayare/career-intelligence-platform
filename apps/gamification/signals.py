"""
Gamification signals.

Only one hook: a submitted application feeds the streak and re-checks
goals. Badges are checked on demand instead, because running six criteria
on every profile save would put six queries on a hot path for something
that changes once.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="applications.Application")
def record_application_activity(sender, instance, created, **kwargs):
    if not created:
        return

    from .services import GoalService, StreakService

    user = instance.seeker.user

    try:
        StreakService.record_application(user)
        GoalService.check_achieved(user)
    except Exception:
        # Gamification must never break an application. The points are a
        # nice-to-have; the application is the product.
        import logging

        logging.getLogger(__name__).exception(
            "Gamification hook failed for user %s",
            user.pk,
        )

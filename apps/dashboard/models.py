from django.db import models

from apps.core.models import TimestampedModel


class SeekerDashboardState(TimestampedModel):
    """
    Per-seeker memory the dashboard needs between visits.

    Lives in this app rather than on SeekerProfile so the dashboard owns its
    own data: nothing in the profile, search or recruiter code needs to know
    when someone last opened their home screen.
    """

    seeker = models.OneToOneField(
        "seekers.SeekerProfile",
        on_delete=models.CASCADE,
        related_name="dashboard_state",
    )
    last_seen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the seeker last left the dashboard. Drives the "
        "'new since your last visit' items.",
    )

    class Meta:
        db_table = "seeker_dashboard_state"

    def __str__(self):
        return f"dashboard state for seeker {self.seeker_id}"

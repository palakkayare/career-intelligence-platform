"""
Application lifecycle services.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError, PermissionDenied

from apps.jobs.models import Job
from .models import Application, ApplicationStatusHistory


class ApplicationStatusService:
    """State machine — different transitions allowed per actor type."""

    # Recruiter-allowed transitions
    RECRUITER_TRANSITIONS = {
        Application.Status.SUBMITTED: [Application.Status.REVIEWING, Application.Status.REJECTED],
        Application.Status.REVIEWING: [Application.Status.SHORTLISTED, Application.Status.REJECTED],
        Application.Status.SHORTLISTED: [Application.Status.INTERVIEW, Application.Status.REJECTED],
        Application.Status.INTERVIEW: [Application.Status.OFFERED, Application.Status.REJECTED],
        Application.Status.OFFERED: [],    # Terminal
        Application.Status.REJECTED: [],   # Terminal
        Application.Status.WITHDRAWN: [],  # Terminal
    }

    # Seeker-allowed transitions (only WITHDRAWN, from non-terminal)
    NON_TERMINAL = {
        Application.Status.SUBMITTED,
        Application.Status.REVIEWING,
        Application.Status.SHORTLISTED,
        Application.Status.INTERVIEW,
    }

    @classmethod
    @transaction.atomic
    def update_status(cls, application, new_status, actor, notes=''):
        """
        Update application status.
        Validates based on actor type (recruiter vs seeker).
        """
        old_status = application.status

        # Determine actor type
        is_seeker = (
            actor.role == 'seeker'
            and application.seeker.user_id == actor.id
        )
        is_recruiter = (
            actor.role == 'recruiter'
            and hasattr(actor, 'recruiter_profile')
            and application.job.posted_by_id == actor.recruiter_profile.id
        )

        if not (is_seeker or is_recruiter):
            raise PermissionDenied("You can't update this application.")

        # Validate transition based on actor
        if is_seeker:
            if new_status != Application.Status.WITHDRAWN:
                raise ValidationError(
                    f"Seeker can only withdraw an application, not change to {new_status}."
                )
            if old_status not in cls.NON_TERMINAL:
                raise ValidationError(
                    f"Cannot withdraw from {old_status} state."
                )
        elif is_recruiter:
            allowed = cls.RECRUITER_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise ValidationError(
                    f"Cannot transition from {old_status} to {new_status}. "
                    f"Allowed: {allowed}"
                )

        # Apply
        application.status = new_status
        application.last_status_change_at = timezone.now()
        if new_status == Application.Status.WITHDRAWN:
            application.is_deleted = True
            application.deleted_at = timezone.now()

        application.save(update_fields=[
            'status', 'last_status_change_at', 'is_deleted', 'deleted_at',
        ])

        # Audit log
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status=old_status,
            to_status=new_status,
            changed_by=actor,
            notes=notes,
        )

        return application


class QuotaService:
    """Track and enforce free-tier application limit."""

    @classmethod
    def get_usage(cls, user):
        """Return usage dict for current 30-day window."""
        cutoff = timezone.now() - timedelta(days=30)
        used = Application.objects.filter(
            seeker__user=user,
            submitted_at__gte=cutoff,
        ).count()  # Includes withdrawn — fair pricing

        limit = settings.FREE_TIER_APPLICATION_LIMIT
        return {'used': used, 'limit': limit, 'remaining': max(0, limit - used)}

    @classmethod
    def can_apply(cls, user):
        """Check if user has quota remaining. Phase 2 mein subscription check."""
        # Phase 2 mein:
        # if user.has_pro_subscription():
        #     return True
        usage = cls.get_usage(user)
        return usage['remaining'] > 0


class ApplicationCreationService:
    """Encapsulates the apply-to-job flow."""

    @classmethod
    @transaction.atomic
    def create(cls, seeker_profile, job, cover_letter='', resume_url=''):
        """
        Validate and create an application.
        """
        # 1. Job must be active
        if job.status != Job.Status.ACTIVE or job.is_deleted:
            raise ValidationError("This job is no longer accepting applications.")

        # 2. Deadline check
        if job.application_deadline and job.application_deadline < timezone.now():
            raise ValidationError("Application deadline has passed.")

        # 3. Already applied?
        if Application.objects.filter(seeker=seeker_profile, job=job).exists():
            raise ValidationError("You have already applied to this job.")

        # 4. Quota check
        if not QuotaService.can_apply(seeker_profile.user):
            usage = QuotaService.get_usage(seeker_profile.user)
            raise ValidationError({
                'detail': (
                    f"Free tier limit reached ({usage['used']}/{usage['limit']} "
                    "applications in last 30 days). Upgrade to Pro for unlimited."
                )
            })

        # 5. Create
        application = Application.objects.create(
            seeker=seeker_profile,
            job=job,
            cover_letter=cover_letter,
            resume_url=resume_url,
            status=Application.Status.SUBMITTED,
            submitted_at=timezone.now(),
            last_status_change_at=timezone.now(),
        )

        # 6. Initial history entry
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status='',
            to_status=Application.Status.SUBMITTED,
            changed_by=seeker_profile.user,
            notes='Initial application',
        )

        return application
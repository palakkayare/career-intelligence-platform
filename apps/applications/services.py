"""
Application lifecycle services.
"""


from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.jobs.models import Job

from .models import Application, ApplicationStatusHistory


class ApplicationStatusService:
    """State machine — different transitions allowed per actor type."""

    # Recruiter-allowed transitions
    RECRUITER_TRANSITIONS = {
        Application.Status.SUBMITTED: [
            Application.Status.REVIEWING,
            Application.Status.REJECTED,
        ],
        Application.Status.REVIEWING: [
            Application.Status.SHORTLISTED,
            Application.Status.REJECTED,
        ],
        Application.Status.SHORTLISTED: [
            Application.Status.INTERVIEW,
            Application.Status.REJECTED,
        ],
        Application.Status.INTERVIEW: [
            Application.Status.OFFERED,
            Application.Status.REJECTED,
        ],
        Application.Status.OFFERED: [],  # Terminal
        Application.Status.REJECTED: [],  # Terminal
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
    def update_status(cls, application, new_status, actor, notes=""):
        """
        Update application status.
        Validates based on actor type (recruiter vs seeker).
        """
        old_status = application.status

        # Determine actor type
        is_seeker = actor.role == "seeker" and application.seeker.user_id == actor.id
        is_recruiter = (
            actor.role == "recruiter"
            and hasattr(actor, "recruiter_profile")
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
                raise ValidationError(f"Cannot withdraw from {old_status} state.")
        elif is_recruiter:
            allowed = cls.RECRUITER_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise ValidationError(
                    f"Cannot transition from {old_status} to {new_status}. " f"Allowed: {allowed}"
                )

        # Apply
        application.status = new_status
        application.last_status_change_at = timezone.now()
        if new_status == Application.Status.WITHDRAWN:
            application.is_deleted = True
            application.deleted_at = timezone.now()

        application.save(
            update_fields=[
                "status",
                "last_status_change_at",
                "is_deleted",
                "deleted_at",
            ]
        )

        # Audit log
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status=old_status,
            to_status=new_status,
            changed_by=actor,
            notes=notes,
        )
        # Notify the seeker that their application status changed
        if old_status != new_status:
            from apps.notifications.triggers import (
                notify_application_status_change,
                notify_application_withdrawn,
            )

            notify_application_status_change(application, old_status, new_status)

            # A withdrawal is the one transition the recruiter does not
            # initiate, so it is the one they would otherwise never hear
            # about - a candidate they were interviewing simply vanishes
            # from the list.
            if new_status == Application.Status.WITHDRAWN:
                notify_application_withdrawn(application)

        return application


class QuotaService:
    """
    Thin wrapper around FeatureGateService, kept for backward
    compatibility with existing imports (views, serializers).

    All quota logic now lives on the Plan model via FeatureGateService,
    so Pro/Business users get their plan's limits (including unlimited)
    instead of the old hardcoded free-tier number.
    """

    @classmethod
    def get_usage(cls, user):
        """
        Return the usage dict for the rolling 30-day window:
        {can, used, limit, remaining, plan} — limit None means unlimited.
        """
        from apps.payments.services import FeatureGateService

        return FeatureGateService.can_apply_to_job(user)

    @classmethod
    def can_apply(cls, user):
        """True when the user may submit another application."""
        from apps.payments.services import FeatureGateService

        result = FeatureGateService.can_apply_to_job(user)
        return result.get("can", False)


class ApplicationCreationService:
    """Encapsulates the apply-to-job flow."""

    @classmethod
    @transaction.atomic
    def create(cls, seeker_profile, job, cover_letter="", resume_url="", resume=None):
        """
        Validate and create an application.

        `resume` is optional: when omitted the seeker's primary resume is
        attached automatically, which is what makes one-click apply work.
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

        # 4. Quota check - plan-driven via FeatureGateService.
        # Pro/Business plans have limit=None (unlimited) and pass through.
        from apps.payments.services import FeatureGateService

        usage = FeatureGateService.can_apply_to_job(seeker_profile.user)
        if not usage["can"]:
            raise ValidationError(
                {
                    "detail": (
                        f"Application limit reached ({usage['used']}/{usage['limit']} "
                        "applications in the last 30 days). "
                        f"Current plan: {usage['plan']}. Upgrade for more."
                    )
                }
            )

        # 5. Resolve which resume travels with this application
        resume = cls._resolve_resume(seeker_profile, resume)

        # 6. Create
        application = Application.objects.create(
            seeker=seeker_profile,
            job=job,
            cover_letter=cover_letter,
            resume=resume,
            resume_url=resume_url,
            status=Application.Status.SUBMITTED,
            submitted_at=timezone.now(),
            last_status_change_at=timezone.now(),
        )

        # 7. Initial history entry
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status="",
            to_status=Application.Status.SUBMITTED,
            changed_by=seeker_profile.user,
            notes="Initial application",
        )

        # Notify the recruiter about the new application
        from apps.notifications.triggers import notify_application_received

        notify_application_received(application)

        return application

    @staticmethod
    def _resolve_resume(seeker_profile, resume):
        """
        Return the resume to attach.

        An explicit choice is verified to belong to this seeker; otherwise the
        primary resume is used. None is a valid outcome - seekers who have not
        uploaded a file can still apply with a link or nothing at all.
        """
        from apps.resumes.models import Resume

        if resume is not None:
            if resume.user_id != seeker_profile.user_id:
                raise ValidationError({"resume": "That resume is not yours."})
            return resume

        return Resume.objects.filter(
            user=seeker_profile.user,
            is_primary=True,
        ).first()

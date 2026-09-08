"""
Business logic for job lifecycle.
Encapsulates state machine + duplication.
"""
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Job
import logging
logger = logging.getLogger(__name__)

class InvalidTransition(ValidationError):
    pass


class JobStatusService:
    """State machine for Job lifecycle."""

    ALLOWED_TRANSITIONS = {
        Job.Status.DRAFT: [Job.Status.PENDING_APPROVAL, Job.Status.DRAFT],
        Job.Status.PENDING_APPROVAL: [Job.Status.ACTIVE, Job.Status.REJECTED],
        Job.Status.REJECTED: [Job.Status.DRAFT],
        Job.Status.ACTIVE: [Job.Status.CLOSED, Job.Status.EXPIRED],
        Job.Status.CLOSED: [],
        Job.Status.EXPIRED: [],
    }

    @classmethod
    def can_transition(cls, current_status, new_status):
        return new_status in cls.ALLOWED_TRANSITIONS.get(current_status, [])
    
    @classmethod
    @transaction.atomic
    def submit(cls, job):
        """Recruiter submits draft for approval."""
        cls._ensure_transition(job, Job.Status.PENDING_APPROVAL)
        cls._validate_required_fields(job)

        job.status = Job.Status.PENDING_APPROVAL
        job.submitted_at = timezone.now()
        job.save(update_fields=['status', 'submitted_at'])

        # Auto-approve in dev
        if getattr(settings, 'JOB_AUTO_APPROVE', False):
            cls.approve(job, actor=None, _auto=True)

        return job

    @classmethod
    @transaction.atomic
    def approve(cls, job, actor=None, _auto=False):
        """Admin approves the job → ACTIVE."""
        cls._ensure_transition(job, Job.Status.ACTIVE)

        job.status = Job.Status.ACTIVE
        job.activated_at = timezone.now()
        job.approved_by = actor if not _auto else None
        job.approved_at = timezone.now()
        job.rejection_reason = ''  # Clear any old reason
        job.save(update_fields=[
            'status', 'activated_at', 'approved_by',
            'approved_at', 'rejection_reason',
        ])
        # Only notify on a real admin approval, not on dev auto-approve
        if not _auto:
            from apps.notifications.triggers import notify_job_approved
            notify_job_approved(job)

        return job
    
    @classmethod
    @transaction.atomic
    def reject(cls, job, actor, reason):
        """Admin rejects the job with reason."""
        cls._ensure_transition(job, Job.Status.REJECTED)

        if not reason or len(reason.strip()) < 10:
            raise ValidationError({'reason': 'Provide a clear rejection reason (min 10 chars).'})

        job.status = Job.Status.REJECTED
        job.rejection_reason = reason.strip()
        job.approved_by = actor  # Track who rejected
        job.approved_at = timezone.now()
        job.save(update_fields=[
            'status', 'rejection_reason', 'approved_by', 'approved_at',
        ])
        # NEW: notify the recruiter that their job posting needs revision
        from apps.notifications.triggers import notify_job_rejected
        notify_job_rejected(job, reason)
        return job

    @classmethod
    @transaction.atomic
    def close(cls, job):
        """Recruiter manually closes an active job."""
        cls._ensure_transition(job, Job.Status.CLOSED)

        job.status = Job.Status.CLOSED
        job.closed_at = timezone.now()
        job.save(update_fields=['status', 'closed_at'])
        return job

    @classmethod
    @transaction.atomic
    def expire(cls, job):
        """Auto-called by Celery Beat when deadline passes."""
        cls._ensure_transition(job, Job.Status.EXPIRED)

        job.status = Job.Status.EXPIRED
        job.closed_at = timezone.now()
        job.save(update_fields=['status', 'closed_at'])
        return job

    @classmethod
    def back_to_draft(cls, job):
        """Move rejected job back to draft for editing."""
        cls._ensure_transition(job, Job.Status.DRAFT)

        job.status = Job.Status.DRAFT
        job.save(update_fields=['status'])
        return job
    
    # ─── Helpers ──────────────────────────────────────

    @classmethod
    def _ensure_transition(cls, job, new_status):
        if not cls.can_transition(job.status, new_status):
            raise InvalidTransition({
                'detail': (
                    f"Cannot transition from {job.status} to {new_status}. "
                    f"Allowed: {cls.ALLOWED_TRANSITIONS.get(job.status, [])}"
                )
            })

    @staticmethod
    def _validate_required_fields(job):
        """Before submission, ensure job is well-formed."""
        errors = {}

        if not job.title or len(job.title.strip()) < 5:
            errors['title'] = 'Title must be at least 5 characters.'

        if not job.description or len(job.description.strip()) < 50:
            errors['description'] = 'Description must be at least 50 characters.'

        if not job.required_skills.exists():
            errors['required_skills'] = 'At least one required skill needed.'

        if job.salary_min and job.salary_max and job.salary_min > job.salary_max:
            errors['salary'] = 'salary_min cannot exceed salary_max.'

        if job.application_deadline and job.application_deadline < timezone.now():
            errors['application_deadline'] = 'Deadline must be in the future.'

        if errors:
            raise ValidationError(errors)
        
    @classmethod
    def expire_overdue(cls):
        """
        Expire every ACTIVE job whose application deadline has passed.

        Shared by the management command and the Celery Beat task so the two
        entry points can never drift apart. Returns (expired, failed).
        """
        from django.utils import timezone

        now = timezone.now()
        expired = 0
        failed = 0

        candidates = Job.objects.filter(
            status=Job.Status.ACTIVE,
            application_deadline__lt=now,
            is_deleted=False,
        )

        for job in candidates:
            try:
                cls.expire(job)
                expired += 1
            except Exception:
                logger.exception('Failed to expire job %s', job.id)
                failed += 1

        return expired, failed
        
class JobDuplicationService:
    """Clone an existing job as a new draft."""

    @classmethod
    @transaction.atomic
    def duplicate(cls, original, recruiter):
        """Create a copy as a new DRAFT."""
        new_job = Job.objects.create(
            public_id=uuid.uuid4(),
            title=f"{original.title} (Copy)",
            description=original.description,
            company=original.company,
            posted_by=recruiter,
            category=original.category,
            min_experience_years=original.min_experience_years,
            max_experience_years=original.max_experience_years,
            employment_type=original.employment_type,
            work_arrangement=original.work_arrangement,
            location=original.location,
            salary_min=original.salary_min,
            salary_max=original.salary_max,
            salary_currency=original.salary_currency,
            salary_period=original.salary_period,
            is_salary_negotiable=original.is_salary_negotiable,
            is_salary_visible=original.is_salary_visible,
            status=Job.Status.DRAFT,
            application_deadline=None,  # User picks new
            view_count=0,
            application_count=0,
        )

        # Copy M2M
        new_job.required_skills.set(original.required_skills.all())
        new_job.nice_to_have_skills.set(original.nice_to_have_skills.all())
        new_job.tags.set(original.tags.all())

        return new_job
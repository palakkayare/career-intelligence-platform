"""
Business logic for resume management.
"""
import logging

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.payments.services import FeatureGateService
from .models import Resume

logger = logging.getLogger(__name__)


class ResumeService:
    """Manages resume lifecycle."""

    ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx'}
    MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

    @classmethod
    def validate_file(cls, file_obj):
        """Pre-upload validation."""
        # Size check
        if file_obj.size > cls.MAX_FILE_SIZE_BYTES:
            raise ValidationError({
                'file': f'File too large. Max {cls.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.'
            })

        # Extension check
        ext = file_obj.name.split('.')[-1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValidationError({
                'file': f'Allowed types: {", ".join(sorted(cls.ALLOWED_EXTENSIONS))}.'
            })

        # MIME type check (extra safety — browser-reported content-type)
        valid_mimes = {
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        }
        if hasattr(file_obj, 'content_type') and file_obj.content_type not in valid_mimes:
            raise ValidationError({'file': 'Invalid file type.'})

    @classmethod
    def check_quota(cls, user):
        """Verify user can upload another resume per their plan."""
        plan = FeatureGateService.get_user_plan(user)
        if plan and plan.max_resumes is not None:
            current_count = Resume.objects.filter(user=user, is_deleted=False).count()
            if current_count >= plan.max_resumes:
                raise ValidationError({
                    'detail': (
                        f'Resume limit reached ({current_count}/{plan.max_resumes}). '
                        f'Plan: {plan.name}. Upgrade for more.'
                    )
                })

    @classmethod
    @transaction.atomic
    def create_resume(cls, user, name, file_obj, set_as_primary=False):
        """
        Validate, save to S3, create record, queue parsing.

        Parsing is queued only for plans that include AI analysis. A free-tier
        resume is stored and stays usable for applying, but is left PENDING so
        no spaCy worker time is spent producing output the user cannot read.
        The reparse endpoint runs it on demand once the user upgrades.
        """
        cls.validate_file(file_obj)
        cls.check_quota(user)

        resume = Resume.objects.create(
            user=user,
            name=name,
            file=file_obj,  # S3 upload yahan hota hai
            original_filename=file_obj.name,
            file_size_bytes=file_obj.size,
            status=Resume.Status.PENDING,
        )

        # First resume OR explicitly requested → make primary
        is_first = not Resume.objects.filter(
            user=user, is_deleted=False
        ).exclude(pk=resume.pk).exists()

        if is_first or set_as_primary:
            cls.set_primary(resume)

        # Queue async parsing (plan-gated)
        if FeatureGateService.has_feature(user, 'resume_ai_analysis'):
            from .tasks import parse_resume_task
            parse_resume_task.delay(resume.id)
            logger.info(
                f"Resume {resume.id} uploaded for {user.email}, parsing queued"
            )
        else:
            logger.info(
                f"Resume {resume.id} uploaded for {user.email}, "
                "parsing skipped (plan has no AI analysis)"
            )

        return resume
    @classmethod
    @transaction.atomic
    def set_primary(cls, resume):
        """Mark this resume as primary; un-mark others."""
        Resume.objects.filter(
            user=resume.user,
            is_primary=True,
            is_deleted=False,
        ).exclude(pk=resume.pk).update(is_primary=False)

        resume.is_primary = True
        resume.save(update_fields=['is_primary'])

    @classmethod
    def get_download_url(cls, resume, expires_in=300):
        """
        Pre-signed S3 URL — `expires_in` seconds ke liye valid.
        Default 5 minutes.
        """
        if not resume.file:
            return None

        if settings.AWS_S3_USE_S3:
            from storages.backends.s3boto3 import S3Boto3Storage
            storage = S3Boto3Storage()
            return storage.connection.meta.client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.AWS_STORAGE_BUCKET_NAME,
                    'Key': resume.file.name,
                },
                ExpiresIn=expires_in,
            )
        else:
            # Local fallback
            return default_storage.url(resume.file.name)

    @classmethod
    def delete_resume(cls, resume):
        """Soft delete. S3 file jagah pe rahegi (cheap storage, Phase 4 undelete)."""
        resume.soft_delete()
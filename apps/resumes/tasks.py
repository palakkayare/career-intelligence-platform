"""
Celery tasks for resume processing.
Step 17 mein spaCy NLP add hogi.
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Resume

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def parse_resume_task(self, resume_id):
    """
    Async task to parse an uploaded resume.
    Full pipeline: text extraction -> spaCy parsing -> ATS scoring.
    """
    try:
        resume = Resume.objects.get(pk=resume_id)
    except Resume.DoesNotExist:
        logger.error(f"Resume {resume_id} not found")
        return

    resume.status = Resume.Status.PARSING
    resume.parse_attempts += 1
    resume.save(update_fields=["status", "parse_attempts"])

    try:
        # Step A: Extract text (already implemented in Step 16)
        text = _extract_text(resume)
        if not text or len(text.strip()) < 50:
            raise ValueError("Extracted text is too short — possibly an image-based PDF")

        resume.extracted_text = text[:50000]
        resume.save(update_fields=["extracted_text"])

        # Step B: Full parsing pipeline (NEW — added in this step)
        from .parser import ResumeParserService

        ResumeParserService.parse(resume)

        # Mark as success
        resume.status = Resume.Status.PARSED
        resume.parsed_at = timezone.now()
        resume.failure_reason = ""
        resume.save()

        logger.info(
            f"Resume {resume_id} fully parsed. "
            f"ATS={resume.ats_score}, Skills={resume.extracted_skills.count()}"
        )

        # Parsing is asynchronous and slow enough that the user has usually
        # navigated away by now, so the result has to find them.
        from apps.notifications.triggers import notify_resume_analysis_complete

        notify_resume_analysis_complete(resume)

    except Exception as e:
        logger.exception(f"Resume {resume_id} parsing failed: {e}")
        resume.failure_reason = str(e)[:1000]
        resume.status = Resume.Status.FAILED
        resume.save()

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)

    if resume.status == Resume.Status.PARSED:
        # on_commit, not a bare delay(): the worker could otherwise pick the
        # job up before this transaction commits and find a resume that is
        # not marked PARSED yet.
        transaction.on_commit(lambda: advanced_ats_task.delay(resume.id))


def _extract_text(resume):
    """Extract text from PDF/DOCX. Returns plain text."""
    file = resume.file
    file_extension = resume.original_filename.split(".")[-1].lower()

    if file_extension == "pdf":
        return _extract_pdf(file)
    elif file_extension in ("doc", "docx"):
        return _extract_docx(file)
    else:
        raise ValueError(f"Unsupported file type: {file_extension}")


def _extract_pdf(file):
    """Extract text from PDF using pdfplumber."""
    import pdfplumber

    text_parts = []
    # File S3-backed hai — stream ke roop mein kholo
    with file.open("rb") as f:
        with pdfplumber.open(f) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    return "\n\n".join(text_parts)


def _extract_docx(file):
    """Extract text from DOCX using python-docx."""
    from docx import Document

    with file.open("rb") as f:
        doc = Document(f)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])


@shared_task(bind=True, max_retries=2)
def advanced_ats_task(self, resume_id):
    """Run the advanced ATS analysis and cache the result on the resume."""
    try:
        resume = Resume.objects.get(pk=resume_id, status=Resume.Status.PARSED)
    except Resume.DoesNotExist:
        logger.error("Resume %s not found or not parsed yet", resume_id)
        return

    try:
        from .ats_advanced import run_full_analysis

        result = run_full_analysis(resume.extracted_text or "")

        resume.advanced_ats_score = int(result["advanced_score_pct"])
        resume.advanced_ats_breakdown = result
        resume.advanced_ats_analyzed_at = timezone.now()
        resume.save(
            update_fields=[
                "advanced_ats_score",
                "advanced_ats_breakdown",
                "advanced_ats_analyzed_at",
            ]
        )

        if result["analysable"]:
            logger.info(
                "Resume %s advanced ATS = %s/100 (%s)",
                resume_id,
                result["advanced_score_pct"],
                result["rating"],
            )
        else:
            logger.info("Resume %s skipped: %s", resume_id, result["message"])

    except Exception as exc:
        logger.exception("Advanced ATS failed for resume %s", resume_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)

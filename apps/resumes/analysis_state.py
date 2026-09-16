"""
What a resume's parsing status means to the person looking at it.

`Resume.status` alone cannot answer that: PENDING covers "queued a second
ago", "the worker never picked it up" and "your plan does not include
analysis, so nothing was ever queued" - three situations that need three
different messages and actions. This module derives the answer.

States
    ready         parsed
    failed        parsing failed (see failure_reason)
    analysing     a worker is on it right now
    queued        waiting for a worker, recently
    stuck         waiting or running for too long; a retry is offered
    not_included  the plan has no AI analysis, so parsing never runs
"""

from datetime import timedelta

from django.utils import timezone

QUEUED_GRACE = timedelta(minutes=2)
ANALYSING_GRACE = timedelta(minutes=10)

FEATURE = "resume_ai_analysis"


def analysis_state(resume, *, has_analysis, now=None):
    now = now or timezone.now()
    status = resume.status
    since = resume.updated_at or resume.created_at

    if status == "parsed":
        return "ready"
    if status == "failed":
        return "failed"
    if not has_analysis:
        # A resume that was being parsed when the plan lapsed still finishes;
        # anything that never started will not.
        return "analysing" if status == "parsing" else "not_included"
    if status == "parsing":
        return "analysing" if now - since < ANALYSING_GRACE else "stuck"
    # pending
    return "queued" if now - since < QUEUED_GRACE else "stuck"


def can_reanalyse(state, *, has_analysis):
    return has_analysis and state in ("stuck", "failed")

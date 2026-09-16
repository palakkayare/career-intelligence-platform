"""
What the seeker dashboard shows, as pure functions over plain data.

No ORM and no request in here: every function takes lists and dicts and
returns dicts, so each rule is testable in isolation and the same decisions
could feed an email digest or the mobile app.

The frontend used to carry these rules (src/features/dashboard/insights.js);
this module is now the single source of truth.
"""

import math
from datetime import timedelta

ACTIVE_PIPELINE = ("submitted", "reviewing", "shortlisted", "interview", "offered")
STATUS_CHANGE_WORDS = {
    "reviewing": "is reviewing your application",
    "shortlisted": "shortlisted you",
    "rejected": "closed your application",
}
DEADLINE_WINDOW = timedelta(hours=72)
ATTENTION_LIMIT = 5
NEW_USER_STRENGTH = 60
APPLY_NUDGE_SCORE = 70
PROFILE_COMPLETE = 100


def _company(app):
    return (app.get("company_name") or "").strip() or "a company"


def _title(app):
    return (app.get("job_title") or "").strip() or "a role"


def match_reasons(required_skills, profile_skills):
    """
    Split a job's required skills into the ones the seeker has and lacks.
    Case-insensitive; keeps the job's own spelling and order.
    """
    mine = {s.lower() for s in profile_skills}
    matched, missing = [], []
    for name in required_skills:
        (matched if name.lower() in mine else missing).append(name)
    return {"matched_skills": matched, "missing_skills": missing}


def build_attention(*, applications, saved_jobs, new_view_companies, last_seen, now):
    """
    Time-sensitive items, most urgent first, at most ATTENTION_LIMIT.

    applications: dicts with id, status, company_name, job_title, job_public_id,
                  last_status_change_at
    saved_jobs:   dicts with job_public_id, title, application_deadline
    new_view_companies: company names of recruiter views after last_seen
                  (already filtered by the caller; empty on a first visit)
    """
    items = []

    for app in applications:
        if app["status"] == "offered":
            items.append(
                {
                    "id": f"offer-{app['id']}",
                    "kind": "offer",
                    "tone": "green",
                    "text": f"Offer from {_company(app)} for {_title(app)}",
                    "cta": "Respond",
                    "link": f"/me/applications/{app['id']}",
                    "_rank": 0,
                }
            )
        elif app["status"] == "interview":
            items.append(
                {
                    "id": f"interview-{app['id']}",
                    "kind": "interview",
                    "tone": "violet",
                    "text": f"Interview stage at {_company(app)} — {_title(app)}",
                    "cta": "Prepare",
                    "link": "/interview-prep",
                    "_rank": 1,
                }
            )

    applied = {a["job_public_id"] for a in applications if a["status"] != "withdrawn"}
    for job in saved_jobs:
        deadline = job.get("application_deadline")
        if not deadline or job["job_public_id"] in applied:
            continue
        left = deadline - now
        if left.total_seconds() <= 0 or left > DEADLINE_WINDOW:
            continue
        days = max(1, math.ceil(left.total_seconds() / 86400))
        when = "within a day" if days <= 1 else f"in {days} days"
        items.append(
            {
                "id": f"deadline-{job['job_public_id']}",
                "kind": "deadline",
                "tone": "amber",
                "text": f"{job['title']} closes {when}",
                "cta": "Apply",
                "link": f"/jobs/{job['job_public_id']}",
                "_rank": 2,
            }
        )

    # "New since last time" only makes sense once there is a last time.
    if last_seen is not None:
        for app in applications:
            changed = app.get("last_status_change_at")
            if app["status"] in STATUS_CHANGE_WORDS and changed and changed > last_seen:
                items.append(
                    {
                        "id": f"status-{app['id']}",
                        "kind": "status_change",
                        "tone": "gray" if app["status"] == "rejected" else "blue",
                        "text": f"{_company(app)} {STATUS_CHANGE_WORDS[app['status']]}",
                        "cta": "View",
                        "link": f"/me/applications/{app['id']}",
                        "_rank": 3,
                    }
                )

        if new_view_companies:
            count = len(new_view_companies)
            if count == 1:
                company = new_view_companies[0]
                text = f"A recruiter{f' from {company}' if company else ''} viewed your profile"
            else:
                text = f"{count} recruiter views on your profile"
            items.append(
                {
                    "id": "views",
                    "kind": "profile_views",
                    "tone": "blue",
                    "text": text,
                    "cta": "See who",
                    "link": "/me/who-viewed",
                    "_rank": 4,
                }
            )

    items.sort(key=lambda i: i["_rank"])  # stable: keeps order within a rank
    for item in items:
        del item["_rank"]
    return items[:ATTENTION_LIMIT]


def build_next_action(
    *, applications, has_profile, resume_count, strength, matches, learning_skill
):
    """
    The single most useful next step. Never returns None.

    matches: dicts with job_public_id, title, company_name, score (score may be None)
    strength: {"score": int, "next_step": str}
    """
    score = strength.get("score", 0)
    next_step = strength.get("next_step") or ""
    live = [a for a in applications if a["status"] != "withdrawn"]
    applied = {a["job_public_id"] for a in live}

    def action(id_, title, detail, cta, link=None, **extra):
        return {
            "id": id_,
            "title": title,
            "detail": detail,
            "cta": cta,
            "link": link,
            "action": extra.get("action"),
            "job_id": extra.get("job_id"),
            "job_title": extra.get("job_title"),
            "progress": extra.get("progress"),
        }

    offer = next((a for a in live if a["status"] == "offered"), None)
    if offer:
        return action(
            "offer",
            f"You have an offer from {_company(offer)}",
            "Review the details and reply before it expires.",
            "Review offer",
            f"/me/applications/{offer['id']}",
        )

    if has_profile and resume_count == 0:
        return action(
            "resume",
            "Upload your resume",
            "Recruiters see it with every application, and it powers your ATS score.",
            "Upload resume",
            "/account/resumes",
        )

    if has_profile and score < NEW_USER_STRENGTH:
        return action(
            "profile",
            next_step or "Complete your profile",
            f"Your profile is {score}% complete. A fuller profile gets better job matches.",
            "Improve profile",
            "/seeker/profile",
            progress=score,
        )

    interview = next((a for a in live if a["status"] == "interview"), None)
    if interview:
        return action(
            "interview",
            f"Prepare for your {_company(interview)} interview",
            "Practise common questions and build STAR stories for this role.",
            "Start preparing",
            "/interview-prep",
        )

    best = next(
        (
            m
            for m in matches
            if m["job_public_id"] not in applied and (m.get("score") or 0) >= APPLY_NUDGE_SCORE
        ),
        None,
    )
    if best:
        return action(
            "apply",
            f"Apply to {best['title']} at {best.get('company_name') or 'this company'}",
            f"It is a {round(best['score'])}% match for your skills.",
            "Apply now",
            f"/jobs/{best['job_public_id']}",
            action="apply",
            job_id=best["job_public_id"],
            job_title=best["title"],
        )

    if not live:
        return action(
            "first_application",
            "Apply to your first job",
            "Find a role that fits and send your first application.",
            "Find jobs",
            "/jobs/search",
        )

    if has_profile and score < PROFILE_COMPLETE and next_step:
        return action(
            "profile_polish",
            next_step,
            f"Your profile is {score}% complete.",
            "Update profile",
            "/seeker/profile",
            progress=score,
        )

    if learning_skill:
        return action(
            "learn",
            f"Learn {learning_skill}",
            "It is the top missing skill for your target role.",
            "Start learning",
            "/learning",
        )

    return action(
        "browse",
        "See what is new",
        "Fresh jobs are posted every day.",
        "Browse jobs",
        "/jobs/search",
    )


def build_checklist(*, strength_score, skill_count, resume_count, target_role):
    return [
        {"key": "profile_complete", "done": strength_score >= PROFILE_COMPLETE},
        {"key": "five_skills", "done": skill_count >= 5},
        {"key": "resume_uploaded", "done": resume_count > 0},
        {"key": "target_role_set", "done": bool(target_role)},
    ]


def is_new_user(*, total_applications, strength_score):
    return total_applications == 0 and strength_score < NEW_USER_STRENGTH


def quota_from(plan_limit, used):
    """Mirror of FeatureGateService.can_apply_to_job's numbers. None = unlimited."""
    if plan_limit is None:
        return None
    return {
        "used": used,
        "limit": plan_limit,
        "remaining": max(0, plan_limit - used),
        "window_days": 30,
    }

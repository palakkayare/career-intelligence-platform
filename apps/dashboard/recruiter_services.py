"""
The recruiter home screen in one response.

Replaces the frontend's "list my jobs, then fetch applicants for each job"
pattern: that cost one request per job, and each list was paginated at 20,
so every total above 20 applicants per job came out wrong.

Two plan rules carry over from the existing endpoints:
  - a recruiter sees at most `max_applicants_view_per_job` applicants per
    job (JobApplicationsView), so named rows respect that cap;
  - match scores are part of candidate search (JobRecommendedCandidatesView).
Counts are not gated: the owner already sees `application_count` per job.
"""

from datetime import timedelta

from django.db.models import Count, F, Q, Window
from django.db.models.functions import RowNumber, TruncDate, TruncMonth
from django.utils import timezone

from apps.applications.models import Application
from apps.jobs.models import Job
from apps.match_scores.models import MatchScore
from apps.payments.services import FeatureGateService

RECENT_ROWS = 6
ATTENTION_JOBS = 5
IN_PROGRESS = ("shortlisted", "interview")
# An offer that was made, whatever the candidate then said.
OFFER_MADE = ("offered", "offer_accepted", "offer_declined")


def _window(qs, field, now, days):
    return qs.filter(**{f"{field}__gte": now - timedelta(days=days)}).count()


def _change(current, previous):
    if previous == 0:
        return 100 if current else 0
    return round((current - previous) / previous * 100)


def build_recruiter_dashboard(recruiter, now=None):
    now = now or timezone.now()
    user = recruiter.user
    plan = FeatureGateService.get_user_plan(user)
    view_cap = FeatureGateService.applicants_view_limit(recruiter)
    can_see_scores = bool(plan and plan.has_candidate_search)

    jobs = Job.objects.filter(posted_by=recruiter, is_deleted=False)
    apps = Application.objects.filter(job__posted_by=recruiter, job__is_deleted=False)

    # ── tiles ─────────────────────────────────────────────────────────
    last_30 = _window(apps, "submitted_at", now, 30)
    prev_30 = apps.filter(
        submitted_at__gte=now - timedelta(days=60), submitted_at__lt=now - timedelta(days=30)
    ).count()
    by_status = dict(apps.values_list("status").annotate(n=Count("id")).values_list("status", "n"))

    tiles = {
        "active_jobs": jobs.filter(status=Job.Status.ACTIVE).count(),
        "jobs_total": jobs.count(),
        "applicants_30d": last_30,
        "applicants_change_pct": _change(last_30, prev_30),
        "applicants_total": sum(by_status.values()),
        "in_progress": sum(by_status.get(s, 0) for s in IN_PROGRESS),
        "in_progress_this_week": apps.filter(
            status__in=IN_PROGRESS, last_status_change_at__gte=now - timedelta(days=7)
        ).count(),
        "offers": sum(by_status.get(s, 0) for s in OFFER_MADE),
        "offers_this_month": apps.filter(
            status__in=OFFER_MADE, last_status_change_at__gte=now - timedelta(days=30)
        ).count(),
        "offers_accepted": by_status.get("offer_accepted", 0),
        "offers_awaiting_answer": by_status.get("offered", 0),
    }

    # ── last 7 days, one bucket per calendar day ──────────────────────
    today = timezone.localdate(now)
    start = today - timedelta(days=6)
    per_day = dict(
        apps.filter(submitted_at__date__gte=start)
        .annotate(day=TruncDate("submitted_at"))
        .values("day")
        .annotate(n=Count("id"))
        .values_list("day", "n")
    )
    week = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "count": per_day.get(start + timedelta(days=i), 0),
        }
        for i in range(7)
    ]

    # ── newest applicants, inside the plan's per-job view cap ─────────
    ranked = apps.annotate(
        rank=Window(RowNumber(), partition_by=[F("job_id")], order_by=F("submitted_at").desc())
    )
    if view_cap is not None:
        ranked = ranked.filter(rank__lte=view_cap)
    recent = list(ranked.select_related("seeker", "job").order_by("-submitted_at")[:RECENT_ROWS])

    scores = {}
    if can_see_scores and recent:
        scores = {
            (m.seeker_id, m.job_id): float(m.overall_score)
            for m in MatchScore.objects.filter(
                seeker_id__in={a.seeker_id for a in recent}, job_id__in={a.job_id for a in recent}
            )
        }

    recent_rows = [
        {
            "id": a.id,
            "candidate_name": (a.seeker.full_name or "").strip() or "Candidate",
            "candidate_title": a.seeker.current_title,
            "job_title": a.job.title,
            "job_public_id": str(a.job.public_id),
            "status": a.status,
            "submitted_at": a.submitted_at,
            "match_score": (
                round(scores[(a.seeker_id, a.job_id)])
                if (a.seeker_id, a.job_id) in scores
                else None
            ),
        }
        for a in recent
    ]

    # ── jobs with applicants nobody has looked at yet ─────────────────
    attention = list(
        jobs.filter(status=Job.Status.ACTIVE)
        .annotate(
            new_count=Count(
                "applications",
                filter=Q(applications__status="submitted", applications__is_deleted=False),
            ),
            total=Count("applications", filter=Q(applications__is_deleted=False)),
        )
        .filter(new_count__gt=0)
        .order_by("-new_count", "-activated_at")[:ATTENTION_JOBS]
        .values("public_id", "title", "new_count", "total")
    )
    for row in attention:
        row["public_id"] = str(row["public_id"])

    return {
        "generated_at": now,
        "company_name": recruiter.company.name if recruiter.company_id else None,
        "recruiter_name": (recruiter.full_name or "").strip() or None,
        "tiles": tiles,
        "week": week,
        "pipeline": {
            s: by_status.get(s, 0)
            for s in (
                "submitted",
                "reviewing",
                "shortlisted",
                "interview",
                "offered",
                "offer_accepted",
                "offer_declined",
                "rejected",
            )
        },
        "recent_applicants": recent_rows,
        "jobs_needing_review": attention,
        "can_see_match_scores": can_see_scores,
        "applicants_view_limit": view_cap,
    }


# ── Hiring analytics ──────────────────────────────────────────────────

MONTHS_BACK = 8
# How many skills the chart names. Jobs list 4-8 required skills each, so a
# short list leaves most of the weight in an "Others" slice that says nothing:
# with four jobs it was two thirds of the chart.
TOP_SKILLS = 10
# Below this, "Others" is noise rather than information.
OTHERS_MIN_SHARE = 0.05
IN_PIPELINE = ("shortlisted", "interview", "offered")


def _avg_days_to_offer(qs):
    """
    Average days from applying to the moment the offer was made, or None.

    Measured from the history row that set "offered", not from the
    application's last status change: once a candidate answers, that last
    change is the answer, which made an accepted offer look slower than a
    pending one.
    """
    from apps.applications.models import ApplicationStatusHistory

    offered_at = dict(
        ApplicationStatusHistory.objects.filter(application__in=qs, to_status="offered")
        .order_by("application_id", "created_at")
        .values_list("application_id", "created_at")
    )
    spans = [
        (offered_at[app_id] - submitted).total_seconds() / 86400
        for app_id, submitted in qs.values_list("id", "submitted_at")
        if app_id in offered_at and submitted
    ]
    return round(sum(spans) / len(spans)) if spans else None


def build_recruiter_analytics(recruiter, now=None):
    """
    Everything the analytics screen draws.

    The page used to fetch each job's applicants and add them up in the
    browser. That cost one request per job and each list stopped at 20, so a
    busy job quietly under-reported. All of it is counted here instead.

    "Offers" means the offered status. The screen used to call the same
    number "Hired", which the product cannot know: nothing records an
    accepted offer.
    """
    now = now or timezone.now()
    jobs = Job.objects.filter(posted_by=recruiter, is_deleted=False)
    apps = Application.objects.filter(job__posted_by=recruiter, job__is_deleted=False)

    by_status = dict(apps.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    total = sum(by_status.values())
    offers = apps.filter(status__in=OFFER_MADE)

    last_30 = _window(apps, "submitted_at", now, 30)
    prev_30 = apps.filter(
        submitted_at__gte=now - timedelta(days=60), submitted_at__lt=now - timedelta(days=30)
    ).count()
    offers_30 = _window(offers, "last_status_change_at", now, 30)
    offers_prev_30 = offers.filter(
        last_status_change_at__gte=now - timedelta(days=60),
        last_status_change_at__lt=now - timedelta(days=30),
    ).count()

    # ── applications per month, oldest first ──────────────────────────
    first_of_month = timezone.localdate(now).replace(day=1)
    months = []
    cursor = first_of_month
    for _ in range(MONTHS_BACK - 1):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    per_month = dict(
        apps.filter(submitted_at__date__gte=cursor)
        .annotate(m=TruncMonth("submitted_at"))
        .values("m")
        .annotate(n=Count("id"))
        .values_list("m", "n")
    )
    per_month = {(m.year, m.month): n for m, n in per_month.items() if m}
    walk = cursor
    while walk <= first_of_month:
        months.append(
            {"month": walk.isoformat(), "count": per_month.get((walk.year, walk.month), 0)}
        )
        walk = (walk.replace(day=28) + timedelta(days=4)).replace(day=1)

    # ── per job ───────────────────────────────────────────────────────
    per_job = list(
        jobs.annotate(
            applicants=Count("applications", filter=Q(applications__is_deleted=False)),
            in_pipeline=Count(
                "applications",
                filter=Q(applications__status__in=IN_PIPELINE, applications__is_deleted=False),
            ),
            offered=Count(
                "applications",
                filter=Q(applications__status__in=OFFER_MADE, applications__is_deleted=False),
            ),
            accepted=Count(
                "applications",
                filter=Q(applications__status="offer_accepted", applications__is_deleted=False),
            ),
        )
        .order_by("-applicants", "-activated_at")
        .values("public_id", "title", "status", "applicants", "in_pipeline", "offered", "accepted")
    )
    for row in per_job:
        row["public_id"] = str(row["public_id"])

    # ── skills in demand, weighted by how many people applied ─────────
    weights = {row["public_id"]: max(1, row["applicants"]) for row in per_job}
    tally = {}
    for job_public_id, skill_name in jobs.values_list("public_id", "required_skills__name"):
        if not skill_name:
            continue
        tally[skill_name] = tally.get(skill_name, 0) + weights.get(str(job_public_id), 1)
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [{"name": n, "weight": w} for n, w in ranked[:TOP_SKILLS]]
    rest = sum(w for _, w in ranked[TOP_SKILLS:])
    total_weight = sum(w for _, w in ranked) or 1

    # An "Others" slice is only worth drawing when it is genuinely small; a
    # large one hides the answer the chart was asked for.
    if rest and rest / total_weight <= OTHERS_MIN_SHARE:
        top.append({"name": "Others", "weight": rest})

    weight_total = sum(row["weight"] for row in top) or 1
    for row in top:
        row["share_pct"] = round(row["weight"] / weight_total * 100)

    reviewed = total - by_status.get("submitted", 0) - by_status.get("withdrawn", 0)
    interviewed = by_status.get("interview", 0) + sum(by_status.get(s, 0) for s in OFFER_MADE)
    active_jobs = jobs.filter(status=Job.Status.ACTIVE).count()

    return {
        "generated_at": now,
        "totals": {
            "applicants": total,
            "applicants_30d": last_30,
            "applicants_change_pct": _change(last_30, prev_30),
            "offers": sum(by_status.get(s, 0) for s in OFFER_MADE),
            "offers_change_pct": _change(offers_30, offers_prev_30),
            "offers_accepted": by_status.get("offer_accepted", 0),
            "offers_declined": by_status.get("offer_declined", 0),
            "avg_days_to_offer": _avg_days_to_offer(offers),
        },
        "months": months,
        "per_job": per_job,
        "funnel": {
            s: by_status.get(s, 0)
            for s in (
                "submitted",
                "reviewing",
                "shortlisted",
                "interview",
                "offered",
                "offer_accepted",
                "offer_declined",
                "rejected",
                "withdrawn",
            )
        },
        "top_skills": top,
        "rates": {
            "review_pct": round(reviewed / total * 100) if total else 0,
            "interview_pct": round(interviewed / total * 100) if total else 0,
            "offer_pct": (
                round(sum(by_status.get(s, 0) for s in OFFER_MADE) / total * 100) if total else 0
            ),
            "accept_pct": (
                round(
                    by_status.get("offer_accepted", 0)
                    / sum(by_status.get(s, 0) for s in OFFER_MADE)
                    * 100
                )
                if sum(by_status.get(s, 0) for s in OFFER_MADE)
                else 0
            ),
            "applicants_per_job": round(total / active_jobs, 1) if active_jobs else 0.0,
        },
    }

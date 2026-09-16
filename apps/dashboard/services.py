"""
Loads everything the seeker dashboard needs, once, and hands plain data to
the rules in rules.py.

Query budget is constant in the number of applications: every list is
fetched in one query with its relations joined, and nothing loops over rows
issuing further queries.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.applications.models import Application
from apps.jobs.models import Job, SavedJob
from apps.match_scores.services import RecommendationService
from apps.payments.services import FeatureGateService
from apps.recruiters.models import CandidateView
from apps.resumes.models import Resume
from apps.seekers.services import ProfileStrengthService

from . import rules
from .models import SeekerDashboardState
from .serializers import DashboardJobSerializer

logger = logging.getLogger(__name__)

MATCH_FETCH = 20
TOP_JOBS = 3
PIPELINE_ITEMS = 3
CACHE_SECONDS = 60


def cache_key(user_id):
    return f"dashboard:seeker:{user_id}"


def invalidate(user_id):
    if user_id:
        cache.delete(cache_key(user_id))


@dataclass
class DashboardContext:
    user: object
    profile: object
    now: object
    plan: object = None
    features: dict = field(default_factory=dict)
    applications: list = field(default_factory=list)
    resumes: list = field(default_factory=list)
    last_seen: object = None
    request: object = None

    # ── loading ───────────────────────────────────────────────────────
    @classmethod
    def load(cls, user, profile, request=None):
        ctx = cls(user=user, profile=profile, now=timezone.now(), request=request)
        ctx.plan = FeatureGateService.get_user_plan(user)
        ctx.features = {
            name: bool(ctx.plan and getattr(ctx.plan, f"has_{name}", False))
            for name in ("match_score", "skill_gap", "resume_ai_analysis", "career_path")
        }
        # all_objects: withdrawn applications are soft-deleted but still count
        # toward the quota and belong in the history.
        ctx.applications = list(
            Application.all_objects.filter(seeker=profile)
            .select_related("job", "job__company")
            .order_by("-submitted_at")
        )
        ctx.resumes = list(
            Resume.objects.filter(user=user, is_deleted=False).order_by(
                "-is_primary", "-created_at"
            )
        )
        state = SeekerDashboardState.objects.filter(seeker=profile).only("last_seen_at").first()
        ctx.last_seen = state.last_seen_at if state else None
        return ctx

    # ── shared views of the data ──────────────────────────────────────
    def has(self, feature):
        return self.features.get(feature, False)

    def app_rows(self):
        return [
            {
                "id": a.id,
                "status": a.status,
                "company_name": a.job.company.name if a.job.company_id else "",
                "job_title": a.job.title,
                "job_public_id": str(a.job.public_id),
                "last_status_change_at": a.last_status_change_at,
                "submitted_at": a.submitted_at,
            }
            for a in self.applications
        ]

    def live_applications(self):
        return [a for a in self.applications if not a.is_deleted and a.status != "withdrawn"]

    def applied_job_ids(self):
        return {a.job_id for a in self.live_applications()}

    def strength(self):
        if not hasattr(self, "_strength"):
            self._strength = ProfileStrengthService.calculate(self.profile)
        return self._strength

    def profile_skill_names(self):
        if not hasattr(self, "_skills"):
            self._skills = [
                ss.skill.name for ss in self.profile.seeker_skills.select_related("skill").all()
            ]
        return self._skills

    def matches(self):
        """Pro: precomputed scores. Free: newest active jobs, no score."""
        if hasattr(self, "_matches"):
            return self._matches
        if self.has("match_score"):
            rows = RecommendationService.top_jobs_for_seeker(
                seeker=self.profile, limit=MATCH_FETCH, min_score=50
            )
            self._matches = [(m.job, float(m.overall_score)) for m in rows]
        else:
            jobs = (
                Job.objects.filter(status=Job.Status.ACTIVE, is_deleted=False)
                .exclude(pk__in=self.applied_job_ids())
                .select_related("company")
                .prefetch_related("required_skills")
                .order_by("-activated_at", "-created_at")[: TOP_JOBS + 2]
            )
            self._matches = [(job, None) for job in jobs]
        return self._matches

    def learning(self):
        """First missing skill and its first resource, or a reason there is none."""
        if hasattr(self, "_learning"):
            return self._learning
        if not self.has("skill_gap"):
            self._learning = {"locked": True, "state": "locked", "skill": None, "resource": None}
            return self._learning

        from apps.career_intel.learning_services import LearningService
        from apps.career_intel.serializers import LearningResourceListSerializer

        result = LearningService.get_recommendations(user=self.user, max_skills=1, max_per_skill=1)
        recs = result.get("recommendations") or []
        if not recs:
            if "target_role" not in result:
                state = "needs_skill_gap"
            elif result.get("message"):
                state = "all_covered"
            else:
                state = "no_resources"
            self._learning = {"locked": False, "state": state, "skill": None, "resource": None}
            return self._learning

        first = recs[0]
        resources = first.get("resources") or []
        resource = LearningResourceListSerializer(resources[0]).data if resources else None
        self._learning = {
            "locked": False,
            "state": "ready",
            "skill": {
                "name": first["skill"].get("name"),
                "importance": first["skill"].get("importance"),
                "rationale": first["skill"].get("rationale") or "",
            },
            "resource": (
                {
                    "id": resource["id"],
                    "title": resource["title"],
                    "url": resource["url"],
                    "provider": (resource.get("provider") or {}).get("name"),
                    "is_free": resource["is_free"],
                    "duration_hours": resource["duration_hours"],
                }
                if resource
                else None
            ),
        }
        return self._learning


# ── section builders ──────────────────────────────────────────────────
# Each takes the context and returns a JSON-ready value. The view runs them
# one by one so a failure in one leaves the others intact.


def _job_payload(ctx, job):
    return DashboardJobSerializer(job, context={"request": ctx.request}).data


def section_plan(ctx):
    return {
        "tier": getattr(ctx.plan, "tier", "free"),
        "name": getattr(ctx.plan, "name", "Free"),
        "features": sorted(name for name, on in ctx.features.items() if on),
    }


def section_greeting_name(ctx):
    name = (ctx.profile.full_name or ctx.user.full_name or "").strip()
    return name.split(" ")[0] if name else ctx.user.email.split("@")[0]


def section_tiles(ctx):
    cutoff = ctx.now - timedelta(days=30)
    used_30d = sum(1 for a in ctx.applications if a.submitted_at >= cutoff)
    month_start = ctx.now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = sum(1 for a in ctx.applications if a.submitted_at >= month_start)
    live = ctx.live_applications()
    matches = ctx.matches() if ctx.has("match_score") else []
    limit = getattr(ctx.plan, "max_applications_per_month", None) if ctx.plan else 0

    return {
        "profile_strength": ctx.strength()["score"],
        "job_matches": {
            "locked": not ctx.has("match_score"),
            "count": len(matches) if ctx.has("match_score") else None,
            "capped": len(matches) >= MATCH_FETCH,
        },
        "applications_this_month": this_month,
        "quota": rules.quota_from(limit, used_30d),
        "interviews": sum(1 for a in live if a.status == "interview"),
    }


def section_top_jobs(ctx):
    applied = ctx.applied_job_ids()
    mine = ctx.profile_skill_names()
    items = []
    for job, score in ctx.matches():
        if job.pk in applied:
            continue
        skills = [s.name for s in job.required_skills.all()]
        items.append(
            {
                "job": _job_payload(ctx, job),
                "score": round(score, 1) if score is not None else None,
                **rules.match_reasons(skills, mine),
            }
        )
        if len(items) == TOP_JOBS:
            break
    return {
        "mode": "matches" if ctx.has("match_score") else "latest",
        "items": items,
        "all_applied": not items and bool(ctx.matches()),
    }


def section_health(ctx):
    strength = ctx.strength()
    primary = ctx.resumes[0] if ctx.resumes else None
    resume = {
        "has_resume": primary is not None,
        "primary_id": None,
        "ats_score": None,
        "ai_score": None,
        "ats_pending": False,
    }
    if primary:
        resume["primary_id"] = str(primary.public_id)
        # The headline number is the ATS score every plan gets - the same one
        # the "analysis ready" email and the resume page show. The AI score
        # measures different things and is shown beside it, never in its place.
        resume["ats_score"] = primary.ats_score
        resume["ats_pending"] = primary.ats_score is None
        if ctx.has("resume_ai_analysis") and primary.advanced_ats_analyzed_at:
            resume["ai_score"] = primary.advanced_ats_score
    return {
        "profile_score": strength["score"],
        "next_step": strength["next_step"] if strength["score"] < rules.PROFILE_COMPLETE else "",
        "resume": resume,
        "checklist": rules.build_checklist(
            strength_score=strength["score"],
            skill_count=len(ctx.profile_skill_names()),
            resume_count=len(ctx.resumes),
            target_role=ctx.profile.target_role,
        ),
    }


def section_pipeline(ctx):
    board = {status: {"count": 0, "items": []} for status in rules.ACTIVE_PIPELINE}
    for a in ctx.live_applications():  # newest first already
        column = board.get(a.status)
        if column is None:
            continue
        column["count"] += 1
        if len(column["items"]) < PIPELINE_ITEMS:
            column["items"].append(
                {
                    "id": a.id,
                    "job_title": a.job.title,
                    "company_name": a.job.company.name if a.job.company_id else "",
                    "submitted_at": a.submitted_at,
                }
            )
    return board


def section_counts(ctx):
    live = ctx.live_applications()
    by_status = {}
    for a in ctx.applications:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    return {
        "total_applications": len(live),
        "by_status": by_status,
        "is_new_user": rules.is_new_user(
            total_applications=len(live), strength_score=ctx.strength()["score"]
        ),
    }


def section_attention(ctx):
    saved = [
        {
            "job_public_id": str(s.job.public_id),
            "title": s.job.title,
            "application_deadline": s.job.application_deadline,
        }
        for s in SavedJob.objects.filter(
            user=ctx.user,
            job__is_deleted=False,
            job__status=Job.Status.ACTIVE,
            job__application_deadline__gt=ctx.now,
            job__application_deadline__lte=ctx.now + rules.DEADLINE_WINDOW,
        ).select_related("job")
    ]
    new_views = []
    if ctx.last_seen is not None:
        new_views = [
            (v.recruiter.company.name if v.recruiter.company_id else "")
            for v in CandidateView.objects.filter(seeker=ctx.profile, created_at__gt=ctx.last_seen)
            .exclude(view_kind=CandidateView.ViewKind.SEARCH_RESULT)
            .select_related("recruiter__company")
            .order_by("-created_at")[:50]
        ]
    return rules.build_attention(
        applications=ctx.app_rows(),
        saved_jobs=saved,
        new_view_companies=new_views,
        last_seen=ctx.last_seen,
        now=ctx.now,
    )


def section_skill_to_learn(ctx):
    return ctx.learning()


def section_next_action(ctx):
    learning = ctx.learning() if ctx.has("skill_gap") else {}
    matches = [
        {
            "job_public_id": str(job.public_id),
            "title": job.title,
            "company_name": job.company.name if job.company_id else "",
            "score": score,
        }
        for job, score in ctx.matches()
    ]
    return rules.build_next_action(
        applications=ctx.app_rows(),
        has_profile=True,
        resume_count=len(ctx.resumes),
        strength=ctx.strength(),
        matches=matches,
        learning_skill=(learning.get("skill") or {}).get("name"),
    )


# Order matters only for readability of the response.
SECTIONS = (
    ("plan", section_plan),
    ("greeting_name", section_greeting_name),
    ("next_action", section_next_action),
    ("attention", section_attention),
    ("tiles", section_tiles),
    ("top_jobs", section_top_jobs),
    ("health", section_health),
    ("pipeline", section_pipeline),
    ("counts", section_counts),
    ("skill_to_learn", section_skill_to_learn),
)


def build_dashboard(user, profile, request=None):
    ctx = DashboardContext.load(user, profile, request=request)
    data, errors = {}, []
    for name, builder in SECTIONS:
        try:
            data[name] = builder(ctx)
        except Exception:  # noqa: BLE001 - one broken widget must not blank the page
            logger.exception(
                "dashboard section failed", extra={"section": name, "user_id": user.pk}
            )
            data[name] = None
            errors.append(name)
    data["generated_at"] = ctx.now
    data["errors"] = errors
    return data


def mark_seen(profile, when=None):
    when = when or timezone.now()
    SeekerDashboardState.objects.update_or_create(seeker=profile, defaults={"last_seen_at": when})
    invalidate(profile.user_id)
    return when

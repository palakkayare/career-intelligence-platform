"""
Interview preparation services.
"""

from django.db.models import Q

from .models import (
    ChecklistProgress,
    CompanyInterviewTip,
    InterviewChecklistItem,
    InterviewQuestion,
    NegotiationScript,
    StarTemplate,
)


class InterviewPrepService:
    """Assembling prep material for a seeker."""

    @classmethod
    def questions_for(cls, target_role=None, category=None, difficulty=None, limit=20):
        """
        Questions for a role, with general ones mixed in.

        General questions are included rather than shown separately because
        "tell me about yourself" gets asked in a backend interview too, and
        splitting the list into two tabs makes people practise one and skip
        the other.
        """
        qs = InterviewQuestion.objects.filter(is_active=True)

        if target_role is not None:
            qs = qs.filter(
                Q(target_role=target_role) | Q(target_role__isnull=True),
            )
        else:
            qs = qs.filter(target_role__isnull=True)

        if category:
            qs = qs.filter(category=category)
        if difficulty:
            qs = qs.filter(difficulty=difficulty)

        return qs.select_related("target_role")[:limit]

    @classmethod
    def star_templates(cls):
        return StarTemplate.objects.filter(is_active=True)

    @classmethod
    def tips_for_company(cls, company):
        return CompanyInterviewTip.objects.filter(company=company, is_active=True).order_by(
            "category"
        )

    @classmethod
    def negotiation_scripts(cls, scenario=None):
        qs = NegotiationScript.objects.filter(is_active=True)
        if scenario:
            qs = qs.filter(scenario=scenario)
        return qs

    @classmethod
    def checklist(cls, user=None, interview_label=None):
        """
        The checklist grouped by phase, with progress attached when a
        specific interview is named.

        Progress is per interview, so the same list can be ticked off again
        for the next one without wiping the record of the last.
        """
        items = InterviewChecklistItem.objects.filter(is_active=True)

        done_ids = set()
        if user is not None and interview_label:
            done_ids = set(
                ChecklistProgress.objects.filter(
                    user=user, interview_label=interview_label
                ).values_list("item_id", flat=True)
            )

        grouped = {}
        for item in items:
            grouped.setdefault(item.phase, []).append(
                {
                    "id": item.id,
                    "text": item.text,
                    "detail": item.detail,
                    "done": item.id in done_ids,
                }
            )

        phases = [
            {
                "phase": phase,
                "label": dict(InterviewChecklistItem.Phase.choices)[phase],
                "items": grouped.get(phase, []),
                "done_count": sum(1 for i in grouped.get(phase, []) if i["done"]),
                "total": len(grouped.get(phase, [])),
            }
            for phase, _ in InterviewChecklistItem.Phase.choices
        ]

        total = sum(p["total"] for p in phases)
        done = sum(p["done_count"] for p in phases)

        return {
            "interview_label": interview_label,
            "phases": phases,
            "total_items": total,
            "completed_items": done,
            "progress_pct": round(done / total * 100, 1) if total else 0.0,
        }

    @classmethod
    def tick(cls, user, item, interview_label):
        """Mark an item done. Idempotent."""
        progress, created = ChecklistProgress.objects.get_or_create(
            user=user,
            item=item,
            interview_label=interview_label,
        )
        return progress, created

    @classmethod
    def untick(cls, user, item, interview_label):
        deleted, _ = ChecklistProgress.objects.filter(
            user=user,
            item=item,
            interview_label=interview_label,
        ).delete()
        return bool(deleted)

    @classmethod
    def my_interviews(cls, user):
        """
        Distinct interview labels this user has started a checklist for.

        Lets the frontend offer "continue where you left off" without
        needing a separate Interview model.
        """
        return list(
            ChecklistProgress.objects.filter(user=user)
            .values_list("interview_label", flat=True)
            .distinct()
        )

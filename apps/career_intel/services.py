"""
Service layer for skill gap analysis.

Views stay thin: they validate input and delegate everything here.
"""

import logging
from typing import List

from django.db import transaction

from apps.seekers.models import SeekerProfile

from . import algorithm
from .models import (
    SkillGapSnapshot,
    TargetRole,
    TargetRoleSkill,
    UserLearning,
)

logger = logging.getLogger(__name__)


class SkillGapService:
    """Analyze the gap between a seeker's skills and a target role."""

    @classmethod
    def analyze(cls, seeker: SeekerProfile, target_role: TargetRole) -> dict:
        """
        Compute the gap analysis. Does NOT persist a snapshot.

        Returns the full analysis payload as a dict.
        """
        seeker_skill_ids = cls._collect_seeker_skill_ids(seeker)

        target_skills = list(
            TargetRoleSkill.objects
            .filter(target_role=target_role)
            .select_related('skill')
        )

        if not target_skills:
            logger.warning(
                'Target role %s has no skills configured', target_role.slug
            )
            return {
                'target_role': cls._serialize_role(target_role),
                'gap_score': 0.0,
                'category': 'perfect_fit',
                'message': 'No skills have been defined for this role yet.',
                'stats': {
                    'total_required': 0,
                    'matched': 0,
                    'missing_critical': 0,
                    'missing_important': 0,
                },
                'matched_skills': [],
                'missing_skills': {
                    'critical': [],
                    'important': [],
                    'preferred': [],
                    'optional': [],
                },
                'recommendations': [],
            }

        # Compute
        gap_score = algorithm.compute_gap_score(seeker_skill_ids, target_skills)
        category = algorithm.categorize_gap(gap_score)
        split = algorithm.split_skills(seeker_skill_ids, target_skills)
        recommendations = algorithm.prioritize_recommendations(split, max_count=5)

        return {
            'target_role': cls._serialize_role(target_role),
            'gap_score': gap_score,
            'category': category,
            'message': cls._build_message(gap_score, split),
            'stats': {
                'total_required': len(target_skills),
                'matched': len(split['matched']),
                'missing_critical': len(split['missing_critical']),
                'missing_important': len(split['missing_important']),
            },
            'matched_skills': split['matched'],
            'missing_skills': {
                'critical': split['missing_critical'],
                'important': split['missing_important'],
                'preferred': split['missing_preferred'],
                'optional': split['missing_optional'],
            },
            'recommendations': recommendations,
        }

    @classmethod
    @transaction.atomic
    def save_snapshot(
        cls,
        seeker: SeekerProfile,
        target_role: TargetRole,
        label: str = '',
    ) -> SkillGapSnapshot:
        """Run the analysis and persist it as a snapshot for history tracking."""
        analysis = cls.analyze(seeker, target_role)

        # Flatten missing skills so they are easier to query later
        missing_all = []
        for bucket in ('critical', 'important', 'preferred', 'optional'):
            missing_all.extend(analysis['missing_skills'][bucket])

        snapshot = SkillGapSnapshot.objects.create(
            seeker=seeker,
            target_role=target_role,
            gap_score=analysis['gap_score'],
            total_required_skills=analysis['stats']['total_required'],
            matched_count=analysis['stats']['matched'],
            missing_critical_count=analysis['stats']['missing_critical'],
            missing_important_count=analysis['stats']['missing_important'],
            matched_skills=analysis['matched_skills'],
            missing_skills=missing_all,
            label=label,
        )

        logger.info(
            'Saved skill gap snapshot %s (score=%s) for seeker %s',
            snapshot.public_id, snapshot.gap_score, seeker.id,
        )
        return snapshot

    @classmethod
    def get_progress(
        cls,
        seeker: SeekerProfile,
        target_role: TargetRole,
        limit: int = 12,
    ) -> List[SkillGapSnapshot]:
        """Return the last N snapshots, newest first, for the progress chart."""
        return list(
            SkillGapSnapshot.objects
            .filter(seeker=seeker, target_role=target_role)
            .order_by('-created_at')[:limit]
        )

    # --- Helpers ---

    @staticmethod
    def _collect_seeker_skill_ids(seeker: SeekerProfile) -> set:
        """
        Collect skill IDs from:
        1. Profile skills
        2. Confirmed skills from the primary resume
         3. Skills taught by completed learning resources
        """
        # 1. Profile skills
        skill_ids = set(
            seeker.skills.values_list('id', flat=True)
        )

        # 2. Confirmed skills from primary resume
        primary_resume = seeker.user.resumes.filter(
            is_primary=True,
            is_deleted=False,
            status='parsed',
        ).first()

        if primary_resume:
            resume_skill_ids = set(
                primary_resume.resume_skills
                .filter(is_confirmed=True)
                .values_list('skill_id', flat=True)
            )

            skill_ids |= resume_skill_ids

        # 3. Skills from completed learning resources
        completed_learning = UserLearning.objects.filter(
            user=seeker.user,
            status=UserLearning.Status.COMPLETED,
        ).prefetch_related('resource__resource_skills')

        for learning in completed_learning:
            completed_skill_ids = learning.resource.resource_skills.values_list(
                'skill_id',
                flat=True,
            )

            skill_ids.update(completed_skill_ids)

        return skill_ids

    @staticmethod
    def _serialize_role(target_role: TargetRole) -> dict:
        """Compact role payload embedded in the analysis response."""
        return {
            'id': target_role.id,
            'slug': target_role.slug,
            'name': target_role.name,
            'min_experience_years': target_role.min_experience_years,
            'avg_salary_inr': (
                str(target_role.avg_salary_inr)
                if target_role.avg_salary_inr is not None
                else None
            ),
        }

    @staticmethod
    def _build_message(gap_score: float, split: dict) -> str:
        """
        Build the human-readable summary message shown to the seeker.

        The headline reflects how large the gap is, while the advice reflects
        what is actually missing. Keeping the two separate avoids telling the
        seeker to start with "0 critical skill(s)" when every critical skill
        is already covered.
        """
        critical_missing = len(split['missing_critical'])
        important_missing = len(split['missing_important'])

        if gap_score == 0:
            return 'Perfect fit! You already have all the required skills.'

        if critical_missing:
            next_step = (
                f"Start with the {critical_missing} critical skill(s), "
                f"then work through the important ones."
            )
        elif important_missing:
            next_step = (
                f"Every critical skill is already covered. Next, focus on the "
                f"{important_missing} important skill(s) below."
            )
        else:
            next_step = (
                'You cover every critical and important skill. The rest are '
                'nice-to-haves that will strengthen your profile.'
            )

        if gap_score < 20:
            headline = 'You are nearly ready.'
        elif gap_score < 40:
            headline = 'Solid foundation.'
        elif gap_score < 60:
            headline = 'Notable gap.'
        else:
            headline = 'Significant gap. Plan a 6-12 month learning roadmap.'

        return f"{headline} {next_step}"
"""
Service layer for learning recommendations and progress tracking.
"""

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import learning_algorithm
from .models import LearningResource, SkillGapSnapshot, UserLearning
from apps.seekers.models import SeekerProfile

logger = logging.getLogger(__name__)


class LearningService:
    """Recommendation engine plus user progress tracking."""

    @classmethod
    def get_recommendations(
        cls,
        user,
        target_role=None,
        max_skills: int = 5,
        max_per_skill: int = 3,
    ) -> dict:
        """
        Build personalized learning recommendations.

        If target_role is given, the gap is computed fresh against that role.
        Otherwise the seeker's most recent snapshot is used.
        """
        seeker = user.seeker_profile

        # Step 1: identify the missing skills
        if target_role:
            from .services import SkillGapService

            analysis = SkillGapService.analyze(seeker, target_role)
            missing_critical = analysis['missing_skills']['critical']
            missing_important = analysis['missing_skills']['important']
            missing_preferred = analysis['missing_skills']['preferred']
        else:
            snapshot = (
                SkillGapSnapshot.objects
                .filter(seeker=seeker)
                .select_related('target_role')
                .order_by('-created_at')
                .first()
            )
            if not snapshot:
                return {
                    'message': (
                        'Run a skill gap analysis first via '
                        '/skill-gap/analyze/.'
                    ),
                    'recommendations': [],
                    'total_recommended': 0,
                }

            all_missing = snapshot.missing_skills
            missing_critical = [
                m for m in all_missing if m.get('importance') == 'critical'
            ]
            missing_important = [
                m for m in all_missing if m.get('importance') == 'important'
            ]
            missing_preferred = [
                m for m in all_missing if m.get('importance') == 'preferred'
            ]
            target_role = snapshot.target_role

        # Step 2: prioritize which skills to tackle first
        prioritized = learning_algorithm.prioritize_skills(
            missing_critical, missing_important, missing_preferred,
        )

        if not prioritized:
            return {
                'target_role': cls._serialize_role(target_role),
                'message': (
                    'Nothing to recommend - your skills already cover this '
                    'role.'
                ),
                'recommendations': [],
                'total_recommended': 0,
            }

        prioritized = prioritized[:max_skills]

        # Step 3: resources the user already finished are never re-recommended
        completed_resource_ids = set(
            UserLearning.objects
            .filter(user=user, status=UserLearning.Status.COMPLETED)
            .values_list('resource_id', flat=True)
        )

        # Step 4: find and rank resources for each prioritized skill
        recommendations = []

        for skill_data in prioritized:
            skill_id = skill_data.get('skill_id')
            if not skill_id:
                continue

            user_skill_level = cls._get_user_skill_level(seeker, skill_id)

            resources = list(
                LearningResource.objects
                .filter(resource_skills__skill_id=skill_id, is_active=True)
                .select_related('provider')
                .prefetch_related('resource_skills__skill')
                .distinct()
            )

            matched_level = learning_algorithm.filter_by_difficulty(
                resources, user_skill_level,
            )

            # Fallback: if nothing sits at the ideal level, show what exists
            # rather than returning no help at all for this skill.
            if not matched_level:
                matched_level = resources

            ranked = learning_algorithm.rank_resources(
                matched_level, completed_resource_ids,
            )
            if not ranked:
                continue

            recommendations.append({
                'skill': {
                    'id': skill_id,
                    'name': skill_data.get('skill_name'),
                    'importance': skill_data.get('importance'),
                    'difficulty': skill_data.get('difficulty'),
                    'rationale': skill_data.get('rationale', ''),
                },
                'resources': ranked,
            })

        # Step 5: cap the totals
        recommendations = learning_algorithm.cap_recommendations(
            recommendations,
            max_per_skill=max_per_skill,
            total_max=15,
        )

        return {
            'target_role': cls._serialize_role(target_role),
            'recommendations': recommendations,
            'total_recommended': sum(
                len(r['resources']) for r in recommendations
            ),
        }

    # --- User progress tracking ---

    @classmethod
    @transaction.atomic
    def start_learning(cls, user, resource) -> UserLearning:
        """Mark a resource as in progress for this user."""
        learning, created = UserLearning.objects.update_or_create(
            user=user,
            resource=resource,
            defaults={
                'status': UserLearning.Status.IN_PROGRESS,
                'started_at': timezone.now(),
                'progress_pct': 0,
            },
        )

        # Count each user only once, even if they restart later
        if created:
            LearningResource.objects.filter(pk=resource.id).update(
                enrollment_count=F('enrollment_count') + 1,
            )

        return learning

    @classmethod
    def update_progress(
        cls, learning: UserLearning, progress_pct: int, notes: str = '',
    ) -> UserLearning:
        """Update the completion percentage and derive the status from it."""
        learning.progress_pct = max(0, min(100, progress_pct))

        if notes:
            learning.notes = notes

        # Keep status and percentage consistent with each other
        if (
            learning.progress_pct == 100
            and learning.status != UserLearning.Status.COMPLETED
        ):
            learning.status = UserLearning.Status.COMPLETED
            learning.completed_at = timezone.now()
        elif (
            learning.progress_pct > 0
            and learning.status == UserLearning.Status.WANT_TO_LEARN
        ):
            learning.status = UserLearning.Status.IN_PROGRESS
            learning.started_at = learning.started_at or timezone.now()

        learning.save()
        return learning

    @classmethod
    @transaction.atomic
    def mark_completed(
        cls, learning: UserLearning, user_rating=None, notes: str = '',
    ) -> UserLearning:
        """Mark as completed, with an optional user rating."""
        learning.status = UserLearning.Status.COMPLETED
        learning.progress_pct = 100
        learning.completed_at = timezone.now()

        if user_rating:
            learning.user_rating = user_rating
        if notes:
            learning.notes = notes

        learning.save()
        return learning

    # --- Helpers ---

    @staticmethod
    def _serialize_role(target_role) -> dict:
        return {
            'id': target_role.id,
            'name': target_role.name,
            'slug': target_role.slug,
        }

    @staticmethod
    def _get_user_skill_level(seeker, skill_id):
        """
        Return the seeker's proficiency for a skill, or None if they have no
        recorded exposure to it.
        """
        from apps.seekers.models import SeekerSkill

        try:
            seeker_skill = SeekerSkill.objects.get(
                seeker=seeker, skill_id=skill_id,
            )
        except SeekerSkill.DoesNotExist:
            return None

        return seeker_skill.proficiency
"""
Skill taxonomy services.

The problem these solve: "React" and "ReactJS" arriving as two rows.

Matching by skill id is exact, so two rows for one skill means a seeker who
lists ReactJS scores zero against a job asking for React. Fixing that at
score time - fuzzy matching, TF-IDF, string similarity - hides the symptom
and leaves the taxonomy broken everywhere else: search, skill gaps, learning
recommendations, the admin list.

So the fix is at the taxonomy instead. Resolve names through aliases before
creating anything, and merge the duplicates that already exist.
"""
import logging

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .models import Skill

logger = logging.getLogger(__name__)


class SkillResolver:
    """Turning a name into the right Skill row."""

    @classmethod
    def resolve(cls, name):
        """
        Find the canonical skill for a name, or None.

        Tries exact name, then slug, then aliases - in that order, because
        an exact name match should never lose to someone else's alias.

        Alias lookup uses `icontains` on the JSON field and then filters in
        Python. Postgres can index that no better either way at this size,
        and an exact JSON containment lookup would miss on case.
        """
        if not name or not name.strip():
            return None

        cleaned = name.strip()

        exact = Skill.objects.filter(
            Q(name__iexact=cleaned) | Q(slug__iexact=cleaned),
            is_deprecated=False,
        ).first()
        if exact is not None:
            return exact

        lowered = cleaned.lower()
        candidates = Skill.objects.filter(
            aliases__icontains=cleaned, is_deprecated=False,
        )
        for skill in candidates:
            if any(str(alias).lower() == lowered for alias in skill.aliases):
                return skill

        return None

    @classmethod
    def resolve_or_create(cls, name, category=None):
        """
        Find or create. Returns (skill, created).

        New skills arrive unapproved: anyone typing into a skill box can
        create one, and an unmoderated taxonomy fills with typos within a
        week. They still work for matching - approval is about the admin
        list, not about blocking the user.
        """
        if not name or not name.strip():
            raise ValidationError({'name': 'Skill name cannot be empty.'})

        existing = cls.resolve(name)
        if existing is not None:
            return existing, False

        skill = Skill.objects.create(
            name=name.strip(),
            category=category or Skill.category.field.default,
            is_approved=False,
        )
        logger.info('New skill created pending approval: %s', skill.name)
        return skill, True

    @classmethod
    def resolve_many(cls, names):
        """
        Resolve a list of names, keeping the ones that matched.

        Used by the resume parser, where most extracted strings are not
        skills at all. Unmatched names are returned separately rather than
        created, because "Responsibilities" should not become a skill.
        """
        matched, unmatched = [], []

        for name in names:
            skill = cls.resolve(name)
            if skill is not None:
                matched.append(skill)
            else:
                unmatched.append(name)

        return matched, unmatched


class SkillMergeService:
    """
    Merging duplicate skills.

    Blueprint Feature 10 asks for add, merge and deprecate. Add and
    deprecate existed; merge did not, which is why duplicates accumulated
    with no way to clean them up.
    """

    @classmethod
    @transaction.atomic
    def merge(cls, source, target):
        """
        Fold `source` into `target`.

        Every reference moves, the source name becomes an alias of the
        target so the string still resolves, and the source row is
        deprecated rather than deleted - deleting it would break any
        historical record that points at it.

        Returns a summary of what moved, because a merge is destructive
        enough that the admin doing it should see the blast radius.
        """
        if source.pk == target.pk:
            raise ValidationError({'detail': 'Cannot merge a skill into itself.'})

        moved = {
            'seeker_skills': cls._move_seeker_skills(source, target),
            'jobs_required': cls._move_job_skills(source, target),
            'resume_skills': cls._move_resume_skills(source, target),
        }

        cls._absorb_aliases(source, target)

        source.is_deprecated = True
        source.save(update_fields=['is_deprecated'])

        logger.info('Merged skill %s into %s: %s', source.name, target.name, moved)
        return {'source': source.name, 'target': target.name, 'moved': moved}

    @staticmethod
    def _move_seeker_skills(source, target):
        """
        Repoint seeker skills, skipping anyone who already has both.

        A seeker listing React and ReactJS ends up with one row, not a
        unique-constraint error.
        """
        from apps.seekers.models import SeekerSkill

        already = set(
            SeekerSkill.objects
            .filter(skill=target)
            .values_list('seeker_id', flat=True)
        )

        duplicates = SeekerSkill.objects.filter(
            skill=source, seeker_id__in=already,
        )
        duplicate_count = duplicates.count()
        duplicates.delete()

        moved = SeekerSkill.objects.filter(skill=source).update(skill=target)
        return {'moved': moved, 'duplicates_removed': duplicate_count}

    @staticmethod
    def _move_job_skills(source, target):
        """
        Repoint job requirements.

        M2M, so `add` is naturally idempotent - a job asking for both ends
        up asking for one.
        """
        from apps.jobs.models import Job

        count = 0
        for job in Job.all_objects.filter(required_skills=source):
            job.required_skills.remove(source)
            job.required_skills.add(target)
            count += 1

        for job in Job.all_objects.filter(nice_to_have_skills=source):
            job.nice_to_have_skills.remove(source)
            job.nice_to_have_skills.add(target)

        return count

    @staticmethod
    def _move_resume_skills(source, target):
        from apps.resumes.models import ResumeSkill

        already = set(
            ResumeSkill.objects
            .filter(skill=target)
            .values_list('resume_id', flat=True)
        )
        ResumeSkill.objects.filter(
            skill=source, resume_id__in=already,
        ).delete()

        return ResumeSkill.objects.filter(skill=source).update(skill=target)

    @staticmethod
    def _absorb_aliases(source, target):
        """
        The target inherits the source's name and aliases, so every string
        that used to resolve to the source still resolves - to the target.
        """
        aliases = list(target.aliases or [])
        lowered = {str(alias).lower() for alias in aliases}

        for candidate in [source.name, *(source.aliases or [])]:
            if str(candidate).lower() not in lowered:
                aliases.append(candidate)
                lowered.add(str(candidate).lower())

        target.aliases = aliases
        target.save(update_fields=['aliases'])

    @classmethod
    def find_likely_duplicates(cls, limit=50):
        """
        Skills whose names collapse to the same thing once case, spaces,
        dots and hyphens are removed.

        A suggestion list for a human, not an auto-merger. "Node.js" and
        "NodeJS" are the same; "C" and "C#" are not, and no normaliser
        should be trusted to know the difference on its own.
        """
        buckets = {}

        for skill in Skill.objects.filter(is_deprecated=False):
            key = (
                skill.name.lower()
                .replace(' ', '').replace('.', '')
                .replace('-', '').replace('_', '')
            )
            buckets.setdefault(key, []).append(skill)

        return [
            {'normalised': key, 'skills': group}
            for key, group in buckets.items()
            if len(group) > 1
        ][:limit]
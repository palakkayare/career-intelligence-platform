"""
Profile strength score calculation.
Out of 100, weighted by section importance.
"""

from rest_framework.exceptions import ValidationError


class ProfileStrengthService:
    """Compute a profile completeness score with breakdown."""

    @classmethod
    def calculate(cls, profile):
        """
        Returns: {
            'score': int (0-100),
            'breakdown': {section: points, ...},
            'next_step': str (suggestion for biggest score boost)
        }
        """
        breakdown = {
            "basic_info": cls._score_basic_info(profile),
            "career_goals": cls._score_career_goals(profile),
            "skills": cls._score_skills(profile),
            "experience": cls._score_experience(profile),
            "education": cls._score_education(profile),
            "portfolio": cls._score_portfolio(profile),
        }
        total = sum(breakdown.values())

        return {
            "score": total,
            "breakdown": breakdown,
            "next_step": cls._suggest_next_step(breakdown),
        }

    @classmethod
    def refresh(cls, profile) -> int:
        """
        Recompute and store the score.

        Writes through a queryset update so the profile's own post_save does
        not fire again and recurse.
        """
        from .models import SeekerProfile

        score = cls.calculate(profile)["score"]

        if profile.profile_strength != score:
            SeekerProfile.objects.filter(pk=profile.pk).update(
                profile_strength=score,
            )
            profile.profile_strength = score

        return score

    @staticmethod
    def _score_basic_info(profile):
        """Max 20 points — name, bio, location, photo."""
        score = 0
        if profile.full_name:
            score += 5
        if profile.bio and len(profile.bio) >= 50:
            score += 5
        if profile.location:
            score += 5
        if profile.profile_photo:
            score += 5
        return score

    @staticmethod
    def _score_career_goals(profile):
        """Max 15 points — current title + target role."""
        score = 0
        if profile.current_title:
            score += 5
        if profile.target_role:
            score += 10  # More important for matching
        return score

    @staticmethod
    def _score_skills(profile):
        """Max 25 points — 5 each up to 5 skills."""
        count = profile.seeker_skills.count()
        return min(count * 5, 25)

    @staticmethod
    def _score_experience(profile):
        """Max 20 points — 10 each up to 2 experiences."""
        count = profile.experiences.count()
        return min(count * 10, 20)

    @staticmethod
    def _score_education(profile):
        """Max 10 points — at least 1 education."""
        return 10 if profile.educations.exists() else 0

    @staticmethod
    def _score_portfolio(profile):
        """Max 10 points — 5 per link, up to 2 links."""
        links = [
            profile.github_url,
            profile.linkedin_url,
            profile.behance_url,
            profile.portfolio_url,
        ]
        count = sum(1 for url in links if url)
        return min(count * 5, 10)

    @staticmethod
    def _suggest_next_step(breakdown):
        """Find the section with biggest gap → suggest action."""
        max_scores = {
            "basic_info": 20,
            "career_goals": 15,
            "skills": 25,
            "experience": 20,
            "education": 10,
            "portfolio": 10,
        }
        suggestions = {
            "basic_info": "Complete your basic info (name, bio, location, photo).",
            "career_goals": "Add your current title and target role.",
            "skills": "Add more skills to your profile (aim for at least 5).",
            "experience": "Add your work experience.",
            "education": "Add your education details.",
            "portfolio": "Add portfolio links (GitHub, LinkedIn, etc.).",
        }

        gaps = {section: max_scores[section] - breakdown[section] for section in breakdown}

        if not any(gaps.values()):
            return "Profile complete! 🎉"

        biggest_gap_section = max(gaps, key=gaps.get)
        return suggestions[biggest_gap_section]


class SkillEndorsementService:
    """
    Endorsing another person's skill.

    The rules exist because an endorsement is only worth anything if it is
    hard to manufacture. Self-endorsement and repeat clicks are the two ways
    to manufacture one cheaply.
    """

    @classmethod
    def endorse(cls, seeker_skill, endorsed_by):
        """
        Record an endorsement. Idempotent - clicking twice is not an error,
        it just does not count twice.
        """
        from .models import SkillEndorsement

        if seeker_skill.seeker.user_id == endorsed_by.id:
            raise ValidationError(
                {
                    "detail": "You cannot endorse your own skills.",
                }
            )

        endorsement, created = SkillEndorsement.objects.get_or_create(
            seeker_skill=seeker_skill,
            endorsed_by=endorsed_by,
        )
        return endorsement, created

    @classmethod
    def withdraw(cls, seeker_skill, endorsed_by):
        """Take an endorsement back. Returns True if there was one."""
        from .models import SkillEndorsement

        deleted, _ = SkillEndorsement.objects.filter(
            seeker_skill=seeker_skill,
            endorsed_by=endorsed_by,
        ).delete()
        return bool(deleted)

    @staticmethod
    def refresh_count(seeker_skill):
        """
        Recompute the denormalised counter.

        Written through a queryset update so the SeekerSkill post_save does
        not fire again and recurse into the profile-strength signal.
        """
        from .models import SeekerSkill

        count = seeker_skill.endorsements.count()

        if seeker_skill.endorsement_count != count:
            SeekerSkill.objects.filter(pk=seeker_skill.pk).update(
                endorsement_count=count,
            )
            seeker_skill.endorsement_count = count

        return count

"""
Profile strength score calculation.
Out of 100, weighted by section importance.
"""


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
            'basic_info': cls._score_basic_info(profile),
            'career_goals': cls._score_career_goals(profile),
            'skills': cls._score_skills(profile),
            'experience': cls._score_experience(profile),
            'education': cls._score_education(profile),
            'portfolio': cls._score_portfolio(profile),
        }
        total = sum(breakdown.values())

        return {
            'score': total,
            'breakdown': breakdown,
            'next_step': cls._suggest_next_step(breakdown),
        }

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
            'basic_info': 20,
            'career_goals': 15,
            'skills': 25,
            'experience': 20,
            'education': 10,
            'portfolio': 10,
        }
        suggestions = {
            'basic_info': 'Complete your basic info (name, bio, location, photo).',
            'career_goals': 'Add your current title and target role.',
            'skills': 'Add more skills to your profile (aim for at least 5).',
            'experience': 'Add your work experience.',
            'education': 'Add your education details.',
            'portfolio': 'Add portfolio links (GitHub, LinkedIn, etc.).',
        }

        gaps = {
            section: max_scores[section] - breakdown[section]
            for section in breakdown
        }

        if not any(gaps.values()):
            return "Profile complete! 🎉"

        biggest_gap_section = max(gaps, key=gaps.get)
        return suggestions[biggest_gap_section]
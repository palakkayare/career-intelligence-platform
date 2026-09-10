"""
Resume parsing service.
Coordinates section detection, skill extraction, contact extraction, and ATS scoring.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from django.db import transaction

from apps.skills.models import Skill

from .models import Resume, ResumeSkill
from .nlp import get_nlp

logger = logging.getLogger(__name__)

# ─── Section header detection patterns ───
SECTION_PATTERNS = {
    "experience": re.compile(
        r"(?im)^\s*(work\s+experience|professional\s+experience|employment|experience)\s*$",
        re.MULTILINE,
    ),
    "education": re.compile(
        r"(?im)^\s*(education|academic\s+(qualifications?|background)|qualifications?)\s*$",
        re.MULTILINE,
    ),
    "skills": re.compile(
        r"(?im)^\s*(technical\s+skills|skills?(\s*&\s*expertise)?|technologies|expertise)\s*$",
        re.MULTILINE,
    ),
    "projects": re.compile(
        r"(?im)^\s*(projects|personal\s+projects|side\s+projects)\s*$",
        re.MULTILINE,
    ),
}

# ─── Contact info detection patterns ───
EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[\s-]?)?\(?\d{2,5}\)?(?:[\s-]?\d{2,5}){1,3}")
LINKEDIN_PATTERN = re.compile(r"(?i)linkedin\.com/in/[\w-]+")
GITHUB_PATTERN = re.compile(r"(?i)github\.com/[\w-]+")


@dataclass
class ParseResult:
    """Structured result returned after parsing a resume."""

    sections: Dict[str, str] = field(default_factory=dict)
    contact: Dict[str, Optional[str]] = field(default_factory=dict)
    extracted_skills: List[dict] = field(default_factory=list)
    ats_score: int = 0
    ats_breakdown: Dict = field(default_factory=dict)


class ResumeParserService:
    """Main parser class. Orchestrates all parsing steps."""

    @classmethod
    @transaction.atomic
    def parse(cls, resume: Resume) -> ParseResult:
        """
        Parse the resume's extracted_text.
        Returns a ParseResult and updates the Resume model in the database.
        """
        text = resume.extracted_text
        if not text:
            raise ValueError("No text to parse — extraction may have failed")

        result = ParseResult()

        # ─── Step 1: Section detection ───
        result.sections = cls._detect_sections(text)

        # ─── Step 2: Contact info extraction ───
        result.contact = cls._extract_contact(text)

        # ─── Step 3: Skill extraction (spaCy) ───
        result.extracted_skills = cls._extract_skills(text, result.sections)

        # ─── Step 4: ATS score calculation ───
        result.ats_score, result.ats_breakdown = cls._calculate_ats_score(
            text, result.sections, result.contact, result.extracted_skills
        )

        # ─── Save everything to the database ───
        cls._save_results(resume, result)

        return result
        # ─── Section Detection ───

    @classmethod
    def _detect_sections(cls, text: str) -> Dict[str, str]:
        """
        Find section header positions in the text.
        Returns a dict of section_name -> section_text.
        """
        sections = {}

        # Find every section header's position in the text
        header_positions = []
        for section_name, pattern in SECTION_PATTERNS.items():
            for match in pattern.finditer(text):
                header_positions.append((match.start(), match.end(), section_name))

        # Sort headers by their position in the text
        header_positions.sort()

        # Extract each section's content (from end of this header to start of next header)
        for i, (start, end, section_name) in enumerate(header_positions):
            content_start = end
            content_end = header_positions[i + 1][0] if i + 1 < len(header_positions) else len(text)
            section_text = text[content_start:content_end].strip()
            sections[section_name] = section_text

        return sections

    # ─── Contact Extraction ───
    @classmethod
    def _extract_contact(cls, text: str) -> Dict[str, Optional[str]]:
        """Extract email, phone, LinkedIn, and GitHub using regex."""
        # Limit search to the first 1500 chars — contact info is usually at the top
        header_text = text[:1500]

        contact = {
            "email": None,
            "phone": None,
            "linkedin": None,
            "github": None,
        }

        email_match = EMAIL_PATTERN.search(header_text)
        if email_match:
            contact["email"] = email_match.group(0)

        phone_match = PHONE_PATTERN.search(header_text)
        if phone_match:
            phone = phone_match.group(0).strip()
            # Filter out things like years/dates that look like phone numbers
            if len(re.sub(r"\D", "", phone)) >= 8:
                contact["phone"] = phone

        linkedin_match = LINKEDIN_PATTERN.search(text)
        if linkedin_match:
            contact["linkedin"] = "https://" + linkedin_match.group(0)

        github_match = GITHUB_PATTERN.search(text)
        if github_match:
            contact["github"] = "https://" + github_match.group(0)

        return contact

        # ─── Skill Extraction (spaCy) ───

    @classmethod
    def _extract_skills(cls, text: str, sections: Dict[str, str]) -> List[dict]:
        """
        Extract skills from text using spaCy's PhraseMatcher.
        Returns a list of dicts with skill_id, confidence, and source.
        """
        from spacy.matcher import PhraseMatcher

        nlp = get_nlp()

        # Build the matcher using all known skills from our Skill master table
        skills_qs = Skill.objects.filter(is_approved=True, is_deprecated=False)
        skill_map = {s.name.lower(): s for s in skills_qs}

        # Also include aliases (e.g. "JS" -> JavaScript)
        alias_to_skill = {}
        for skill in skills_qs:
            for alias in skill.aliases or []:
                alias_to_skill[alias.lower()] = skill

        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")  # case-insensitive matching
        patterns = [nlp.make_doc(name) for name in skill_map.keys()]
        if alias_to_skill:
            patterns.extend([nlp.make_doc(alias) for alias in alias_to_skill.keys()])
        matcher.add("SKILLS", patterns)

        # Run the matcher on the full resume text
        doc = nlp(text)
        matches = matcher(doc)

        # Collect: skill_id -> {count, sections it appeared in}
        skill_data = defaultdict(lambda: {"count": 0, "sections": set()})

        for match_id, start, end in matches:
            span = doc[start:end]
            matched_text = span.text.lower()

            # Find which Skill object this matched text corresponds to
            skill = skill_map.get(matched_text) or alias_to_skill.get(matched_text)
            if not skill:
                continue

            skill_data[skill.id]["count"] += 1

            # Determine which section this match falls in
            char_offset = span.start_char
            section = cls._find_section_for_offset(char_offset, text, sections)
            skill_data[skill.id]["sections"].add(section)

        # Compute confidence score + primary source for each matched skill
        results = []
        for skill_id, data in skill_data.items():
            confidence, source = cls._compute_confidence(
                count=data["count"],
                sections=data["sections"],
            )
            results.append(
                {
                    "skill_id": skill_id,
                    "confidence": confidence,
                    "source": source,
                    "mention_count": data["count"],
                }
            )

        # Sort by confidence, highest first
        return sorted(results, key=lambda x: x["confidence"], reverse=True)

    @staticmethod
    def _find_section_for_offset(char_offset: int, text: str, sections: Dict[str, str]) -> str:
        """Determine which section a given character offset falls inside."""
        section_starts = []
        for section_name in sections:
            try:
                start = text.index(sections[section_name])
                section_starts.append((start, section_name))
            except ValueError:
                continue

        section_starts.sort()

        # Find the latest section whose start position is <= the offset
        current_section = "general"
        for start, name in section_starts:
            if start <= char_offset:
                current_section = name
            else:
                break

        return current_section

    @staticmethod
    def _compute_confidence(count: int, sections: set) -> tuple:
        """Compute a confidence score (0.0-1.0) and the primary source for a skill match."""
        # Priority order — if a skill appears in multiple sections, pick the highest-priority one
        priority = ["skills", "experience", "projects", "education", "general"]
        primary_source = next((s for s in priority if s in sections), "general")

        # Base confidence score depending on which section the skill was found in
        source_scores = {
            "skills": 0.85,
            "experience": 0.75,
            "projects": 0.70,
            "education": 0.55,
            "general": 0.40,
        }
        confidence = source_scores.get(primary_source, 0.40)

        # Boost confidence if the skill is mentioned multiple times
        if count >= 3:
            confidence += 0.10
        elif count >= 2:
            confidence += 0.05

        # Map our internal section names to the ResumeSkill.Source choices
        source_map = {
            "skills": ResumeSkill.Source.SKILLS_SECTION,
            "experience": ResumeSkill.Source.EXPERIENCE,
            "education": ResumeSkill.Source.EDUCATION,
            "projects": ResumeSkill.Source.GENERAL,
            "general": ResumeSkill.Source.GENERAL,
        }

        return min(1.0, confidence), source_map[primary_source]

        # ─── ATS Scoring ───

    @classmethod
    def _calculate_ats_score(cls, text, sections, contact, extracted_skills) -> tuple:
        """Calculate ATS compatibility score (0-100) with a detailed breakdown."""
        breakdown = {}
        score = 0

        # Check 1: Is text actually extractable (not an image-based PDF)? — 40 pts
        if text and len(text.strip()) > 100:
            breakdown["text_extractable"] = {"score": 40, "max": 40, "passed": True}
            score += 40
        else:
            breakdown["text_extractable"] = {
                "score": 0,
                "max": 40,
                "passed": False,
                "reason": "PDF appears to be image-based or empty. ATS will reject.",
            }

        # Check 2: Word count in a reasonable range — 15 pts
        word_count = len(text.split())
        if 200 <= word_count <= 2500:
            breakdown["word_count"] = {
                "score": 15,
                "max": 15,
                "passed": True,
                "value": word_count,
            }
            score += 15
        elif word_count < 200:
            breakdown["word_count"] = {
                "score": 5,
                "max": 15,
                "passed": False,
                "value": word_count,
                "reason": "Resume is too short. Aim for 400-1500 words.",
            }
            score += 5
        else:
            breakdown["word_count"] = {
                "score": 5,
                "max": 15,
                "passed": False,
                "value": word_count,
                "reason": "Resume is too long. Keep under 2500 words.",
            }
            score += 5

        # Check 3: Key sections detected — 20 pts
        section_count = sum(1 for s in ["experience", "education", "skills"] if s in sections)
        section_pts = min(20, section_count * 7)
        breakdown["sections"] = {
            "score": section_pts,
            "max": 20,
            "passed": section_count >= 2,
            "detected": list(sections.keys()),
        }
        score += section_pts

        # Check 4: Contact info present — 10 pts
        contact_pts = 0
        if contact.get("email"):
            contact_pts += 7
        if contact.get("phone"):
            contact_pts += 3
        breakdown["contact"] = {
            "score": contact_pts,
            "max": 10,
            "passed": contact_pts >= 7,
            "detected": {k: v for k, v in contact.items() if v},
        }
        score += contact_pts

        # Check 5: Skills detected — 10 pts
        skill_count = len(extracted_skills)
        if skill_count >= 5:
            skill_pts = 10
        elif skill_count >= 3:
            skill_pts = 7
        elif skill_count >= 1:
            skill_pts = 4
        else:
            skill_pts = 0
        breakdown["skills_detected"] = {
            "score": skill_pts,
            "max": 10,
            "passed": skill_count >= 3,
            "count": skill_count,
        }
        score += skill_pts

        # Check 6: No obvious format flags — 5 pts (simple proxy for now)
        # Advanced checks (action verbs, quantifiable achievements, etc.) come in Phase 3
        format_pts = 5 if len(text) > 100 else 0
        breakdown["format"] = {"score": format_pts, "max": 5, "passed": format_pts > 0}
        score += format_pts

        return score, breakdown

    # ─── Persistence ───
    @classmethod
    @transaction.atomic
    def _save_results(cls, resume: Resume, result: ParseResult):
        """Save the parsed results into the Resume and ResumeSkill tables."""
        # Update the Resume record
        resume.parsed_data = {
            "sections": {k: v[:1000] for k, v in result.sections.items()},  # truncate for storage
            "contact": result.contact,
            "word_count": len(resume.extracted_text.split()),
        }
        resume.ats_score = result.ats_score
        resume.ats_breakdown = result.ats_breakdown
        resume.save()

        # Clear previously AI-extracted skills only.
        # IMPORTANT: never delete user-added skills (is_user_added=True) — see Mistake #5.
        ResumeSkill.objects.filter(
            resume=resume,
            is_user_added=False,
        ).delete()

        # Save the newly extracted skills
        for skill_data in result.extracted_skills:
            ResumeSkill.objects.update_or_create(
                resume=resume,
                skill_id=skill_data["skill_id"],
                defaults={
                    "confidence": skill_data["confidence"],
                    "source": skill_data["source"],
                    "mention_count": skill_data["mention_count"],
                    "is_confirmed": False,
                    "is_user_added": False,
                },
            )

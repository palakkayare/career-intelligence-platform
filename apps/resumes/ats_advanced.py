"""
Advanced ATS analysis components.

Every analyzer here is a pure function: text in, dict out. No database
access, which makes them cheap to unit-test and safe to call from tasks,
views or the shell.

NOTE: the vocabularies below assume English-language resumes.
Multilingual support is out of scope for this phase.
"""

import re
from typing import Dict, List, Optional, Set

# A resume shorter than this is not worth analysing — the scores would be
# noise. Both the analyzer and the Celery task use this same constant so
# they can never disagree about what counts as "too short".
MIN_ANALYSABLE_LENGTH = 100


# --------------------------------------------------------------------------- #
# Action verbs
# --------------------------------------------------------------------------- #

STRONG_ACTION_VERBS = {
    "leadership": {
        "led",
        "managed",
        "directed",
        "spearheaded",
        "supervised",
        "coached",
        "mentored",
        "guided",
        "orchestrated",
        "oversaw",
        "championed",
        "pioneered",
    },
    "building": {
        "built",
        "developed",
        "created",
        "designed",
        "engineered",
        "architected",
        "implemented",
        "constructed",
        "crafted",
        "authored",
        "programmed",
        "coded",
    },
    "improvement": {
        "optimized",
        "reduced",
        "increased",
        "streamlined",
        "improved",
        "enhanced",
        "accelerated",
        "simplified",
        "refactored",
        "modernized",
        "upgraded",
        "scaled",
    },
    "achievement": {
        "delivered",
        "shipped",
        "launched",
        "achieved",
        "executed",
        "completed",
        "accomplished",
        "succeeded",
        "exceeded",
        "won",
        "awarded",
    },
    "analysis": {
        "analyzed",
        "researched",
        "investigated",
        "evaluated",
        "identified",
        "discovered",
        "diagnosed",
        "measured",
    },
    "collaboration": {
        "collaborated",
        "partnered",
        "coordinated",
        "facilitated",
        "negotiated",
        "communicated",
        "presented",
    },
}

WEAK_PHRASES = [
    "responsible for",
    "duties included",
    "tasks were",
    "was tasked with",
    "helped with",
    "worked on",
    "assisted with",
    "involved in",
]

# Pre-compile every verb pattern once at import time instead of rebuilding
# ~60 regexes on every single analysis call.
_VERB_PATTERNS = {
    category: [
        (verb, re.compile(rf"\b{re.escape(verb)}\b", re.IGNORECASE)) for verb in sorted(verbs)
    ]
    for category, verbs in STRONG_ACTION_VERBS.items()
}


def analyze_action_verbs(text: str) -> Dict:
    """
    Score how assertively the resume describes its accomplishments.

    Rewards: variety of strong verbs, spread across categories.
    Penalises: filler phrases like "responsible for".
    Returns a dict with a score out of 25.
    """
    found = {}
    total_strong = 0

    for category, patterns in _VERB_PATTERNS.items():
        hits = []
        for verb, pattern in patterns:
            count = len(pattern.findall(text))
            if count:
                hits.append({"verb": verb, "count": count})
                total_strong += count
        if hits:
            found[category] = hits

    text_lower = text.lower()
    weak_found = [
        {"phrase": phrase, "count": text_lower.count(phrase)}
        for phrase in WEAK_PHRASES
        if text_lower.count(phrase) > 0
    ]

    # ---- Scoring, out of 25 ----
    unique_strong_count = sum(len(hits) for hits in found.values())

    # Breadth of vocabulary: roughly 8 distinct verbs earns the full 15
    diversity_score = min(15, unique_strong_count * 2)

    # Bonus for showing range rather than repeating one kind of verb
    if len(found) >= 4:
        diversity_bonus = 5
    elif len(found) >= 3:
        diversity_bonus = 3
    else:
        diversity_bonus = 0

    # Reward sustained use, not just a single strong bullet
    quantity_bonus = min(5, max(0, total_strong - 5))

    # Each filler phrase costs 2 points, capped so one bad line is not fatal
    weak_penalty = min(10, sum(item["count"] for item in weak_found) * 2)

    score = diversity_score + diversity_bonus + quantity_bonus - weak_penalty
    score = max(0, min(25, score))

    suggestions = []
    if unique_strong_count < 5:
        suggestions.append(
            "Use more strong action verbs such as led, built, optimized " "or delivered."
        )
    if weak_found:
        phrases = ", ".join(item["phrase"] for item in weak_found[:3])
        suggestions.append(f"Replace weak phrases: {phrases}.")
    if len(found) < 3:
        suggestions.append(
            "Vary your verbs so the resume shows leadership, building and "
            "measurable improvement."
        )

    return {
        "score": score,
        "max": 25,
        "unique_strong_count": unique_strong_count,
        "total_strong_uses": total_strong,
        "categories_used": sorted(found.keys()),
        "verbs_found": found,
        "weak_phrases_found": weak_found,
        "suggestions": suggestions,
    }

    # --------------------------------------------------------------------------- #


# Quantifiable achievements
# --------------------------------------------------------------------------- #

QUANTITY_PATTERNS = [
    # A bare count after an achievement verb: "shipped 12 features",
    # "closed 30 tickets". The unit is open-ended because every team
    # measures a different thing.
    re.compile(
        r"\b(?:shipped|launched|delivered|built|created|managed|led|hired|"
        r"closed|resolved|migrated|automated|onboarded|trained|published|"
        r"reviewed|integrated|supported|handled|processed)\s+"
        r"(?:over\s+|more\s+than\s+)?\d+(?:,\d{3})*\+?\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%"),  # 40%, 25.5%
    re.compile(r"\$\d+(?:[,.]\d+)*\s*(?:K|M|k|m|thousand|million)?"),
    re.compile(r"₹\d+(?:[,.]\d+)*\s*(?:K|M|k|m|L|Cr|cr|lakh)?"),
    re.compile(r"\b\d+x\b", re.IGNORECASE),  # 5x, 10x
    re.compile(
        r"\b\d+(?:,\d{3})*\+?\s+"
        r"(?:users|customers|clients|requests|orders|engineers|teams|"
        r"developers|people|transactions|records|queries)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b\d+(?:\.\d+)?\s+(?:million|billion|thousand|crore|lakh)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:from|by|to)\s+\d+(?:,\d{3})*", re.IGNORECASE),
    re.compile(
        r"\b\d+\s*(?:ms|sec|seconds?|mins?|minutes?|hours?|days?|weeks?|" r"months?|years?)\b",
        re.IGNORECASE,
    ),
]

# Things that look numeric but say nothing about impact. Checked first so a
# bullet is not credited just for containing a page number or a clock time.
FALSE_QUANTIFIER_PATTERNS = [
    re.compile(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", re.IGNORECASE),  # 10:00 AM
    re.compile(r"\bpage\s+\d+\b", re.IGNORECASE),  # Page 5
    re.compile(
        r"\b(?:19|20)\d{2}\s*[-–]\s*(?:(?:19|20)\d{2}|present)\b", re.IGNORECASE
    ),  # 2021-2023
]


def _strip_false_quantifiers(bullet: str) -> str:
    """Remove number-like noise so it cannot be mistaken for a real metric."""
    cleaned = bullet
    for pattern in FALSE_QUANTIFIER_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def _split_into_bullets(text: str) -> List[str]:
    """
    Prefer real bullet points. If the resume has almost none (common with
    plain-text exports), fall back to sentences so the analysis still works.
    """
    bullets = re.findall(r"(?:^|\n)\s*[•\-\*\u25cf\u25aa]\s*(.+?)(?=\n|$)", text)
    bullets = [b.strip() for b in bullets if len(b.strip()) > 15]

    if len(bullets) >= 3:
        return bullets

    return [s.strip() for s in re.split(r"[.!?\n]+", text) if len(s.strip()) > 20]


def analyze_quantification(text: str) -> Dict:
    """
    Measure how many accomplishments carry a concrete number.
    Industry guidance is that roughly 30% of bullets should be quantified.
    Returns a dict with a score out of 25.
    """
    bullets = _split_into_bullets(text)

    if not bullets:
        return {
            "score": 0,
            "max": 25,
            "total_bullets": 0,
            "quantified_count": 0,
            "pct_quantified": 0.0,
            "examples": [],
            "suggestions": [
                "Use bullet points for your accomplishments so each one can "
                "be read and measured separately.",
            ],
        }

    quantified_count = 0
    examples = []

    for bullet in bullets:
        cleaned = _strip_false_quantifiers(bullet)
        if any(pattern.search(cleaned) for pattern in QUANTITY_PATTERNS):
            quantified_count += 1
            if len(examples) < 5:
                examples.append(bullet[:150])

    total_bullets = len(bullets)
    pct_quantified = quantified_count / total_bullets * 100

    if pct_quantified >= 30:
        score = 25
    elif pct_quantified >= 20:
        score = 18
    elif pct_quantified >= 10:
        score = 12
    elif pct_quantified >= 5:
        score = 6
    else:
        score = 0

    suggestions = []
    if pct_quantified < 30:
        suggestions.append(
            f"Only {pct_quantified:.0f}% of your bullets contain numbers. "
            f'Aim for 30% or more — add metrics like "increased signups by '
            f'25%" or "managed a team of 8".'
        )
    if pct_quantified < 5:
        suggestions.append("Numbers turn claims into evidence. Even rough figures help.")

    return {
        "score": score,
        "max": 25,
        "total_bullets": total_bullets,
        "quantified_count": quantified_count,
        "pct_quantified": round(pct_quantified, 1),
        "examples": examples,
        "suggestions": suggestions,
    }


# --------------------------------------------------------------------------- #
# Language quality: passive voice + spelling
# --------------------------------------------------------------------------- #

PASSIVE_PATTERNS = [
    re.compile(r"\b(?:was|were)\s+\w+ed\b", re.IGNORECASE),
    re.compile(r"\b(?:been|being)\s+\w+ed\b", re.IGNORECASE),
    re.compile(r"\bwas\s+responsible\b", re.IGNORECASE),
]

# Domain vocabulary the general English dictionary does not know. Without
# this, every technical resume would be flagged as full of typos.
TECH_TERMS = {
    "django",
    "flask",
    "fastapi",
    "pyramid",
    "celery",
    "gunicorn",
    "uvicorn",
    "kubernetes",
    "docker",
    "helm",
    "terraform",
    "ansible",
    "nginx",
    "postgresql",
    "postgres",
    "mysql",
    "sqlite",
    "redis",
    "mongodb",
    "elasticsearch",
    "cassandra",
    "dynamodb",
    "aws",
    "gcp",
    "azure",
    "ec2",
    "rds",
    "lambda",
    "cloudwatch",
    "cloudfront",
    "react",
    "vue",
    "angular",
    "svelte",
    "nextjs",
    "nuxt",
    "gatsby",
    "jquery",
    "graphql",
    "restful",
    "grpc",
    "websocket",
    "websockets",
    "webhook",
    "sqlalchemy",
    "redux",
    "mobx",
    "pydantic",
    "alembic",
    "oauth",
    "jwt",
    "saml",
    "openid",
    "ldap",
    "github",
    "gitlab",
    "bitbucket",
    "jira",
    "confluence",
    "jenkins",
    "kafka",
    "rabbitmq",
    "airflow",
    "spark",
    "hadoop",
    "pytest",
    "unittest",
    "jest",
    "mocha",
    "cypress",
    "selenium",
    "devops",
    "agile",
    "scrum",
    "kanban",
    "sprint",
    "standup",
    "tensorflow",
    "pytorch",
    "keras",
    "sklearn",
    "numpy",
    "pandas",
    "scipy",
    "matplotlib",
    "seaborn",
    "spacy",
    "nltk",
    "huggingface",
    "transformers",
    "fullstack",
    "backend",
    "frontend",
    "middleware",
    "microservices",
    "microservice",
    "monolith",
    "serverless",
    "android",
    "kotlin",
    "swift",
    "flutter",
    "dart",
    "javascript",
    "typescript",
    "python",
    "golang",
    "rust",
    "scala",
    "html",
    "css",
    "scss",
    "sass",
    "tailwind",
    "bootstrap",
    "webpack",
    "vite",
    "rollup",
    "babel",
    "eslint",
    "nosql",
    "rdbms",
    "crud",
    "orm",
    "jsonb",
    "protobuf",
    "yaml",
    "saas",
    "paas",
    "iaas",
    "cicd",
    "sre",
    "slo",
    "sla",
    "dataset",
    "datasets",
    "dataframe",
    "notebook",
    "jupyter",
    "roadmap",
    "stakeholders",
    "onboarding",
    "scalable",
    "scalability",
    "refactored",
    "refactoring",
    "dockerized",
    "containerized",
}

# Words shorter than this are skipped: short tokens produce almost all the
# false positives (initials, abbreviations, fragments).
MIN_SPELLCHECK_WORD_LENGTH = 5


def check_spelling(text: str) -> List[str]:
    """
    Return up to 10 words that look misspelled, ignoring technical
    vocabulary. Returns an empty list if pyspellchecker is unavailable so a
    missing optional dependency never breaks the whole analysis.
    """
    try:
        from spellchecker import SpellChecker
    except ImportError:
        return []

    spell = SpellChecker()
    spell.word_frequency.load_words(TECH_TERMS)

    # Emails, URLs and handles are identifiers, never spelling mistakes.
    # Strip them before tokenising or every resume header looks broken.
    text = re.sub(r"\S+@\S+", " ", text)
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)

    words = {
        word.lower() for word in re.findall(rf"\b[a-zA-Z]{{{MIN_SPELLCHECK_WORD_LENGTH},}}\b", text)
    }
    if not words:
        return []

    # Words that appear capitalised in the original are almost always
    # proper nouns - names, cities, colleges. Telling someone their own
    # surname is misspelled is worse than saying nothing.
    proper_nouns = {w.lower() for w in re.findall(r"\b[A-Z][a-zA-Z]{3,}\b", text)}

    misspelled = [
        word for word in spell.unknown(words) if word not in TECH_TERMS and word not in proper_nouns
    ]

    # Longer words first: they are more likely to be genuine words the
    # candidate misspelled, rather than an acronym or a product name.
    misspelled.sort(key=len, reverse=True)
    return misspelled[:10]


def analyze_language_quality(text: str) -> Dict:
    """
    Combine passive-voice detection and spell checking into one score
    out of 20 (12 for voice, 8 for spelling).

    Passive voice is judged on a tolerance curve, not banned outright —
    some technical statements are legitimately passive.
    """
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if len(s.strip()) > 10]

    passive_count = 0
    passive_examples = []
    for sentence in sentences:
        if any(pattern.search(sentence) for pattern in PASSIVE_PATTERNS):
            passive_count += 1
            if len(passive_examples) < 3:
                passive_examples.append(sentence[:150])

    pct_passive = (passive_count / len(sentences) * 100) if sentences else 0.0

    spelling_issues = check_spelling(text)

    # ---- Passive voice, out of 12 ----
    if pct_passive < 10:
        passive_score = 12
    elif pct_passive < 20:
        passive_score = 9
    elif pct_passive < 30:
        passive_score = 6
    else:
        passive_score = 2

    # ---- Spelling, out of 8 ----
    if not spelling_issues:
        spelling_score = 8
    elif len(spelling_issues) <= 3:
        spelling_score = 5
    elif len(spelling_issues) <= 7:
        spelling_score = 2
    else:
        spelling_score = 0

    suggestions = []
    if pct_passive >= 20:
        suggestions.append(
            f"{pct_passive:.0f}% of your sentences use passive voice. "
            f'Prefer "I designed the system" over "the system was designed '
            f'by me".'
        )
    if spelling_issues:
        suggestions.append(f'Possible spelling issues: {", ".join(spelling_issues[:5])}.')

    return {
        "score": passive_score + spelling_score,
        "max": 20,
        "passive_voice": {
            "count": passive_count,
            "pct": round(pct_passive, 1),
            "total_sentences": len(sentences),
            "examples": passive_examples,
        },
        "spelling_issues": spelling_issues,
        "suggestions": suggestions,
    }

    # --------------------------------------------------------------------------- #


# Job-description keyword matching
# --------------------------------------------------------------------------- #

QUALIFICATION_PATTERNS = [
    re.compile(r"bachelor['’]?s?\s+(?:degree|in|of)", re.IGNORECASE),
    re.compile(r"master['’]?s?\s+(?:degree|in|of)", re.IGNORECASE),
    re.compile(r"\bphd\b", re.IGNORECASE),
    re.compile(r"\bb\.?(?:tech|sc|com|ca|e)\b", re.IGNORECASE),
    re.compile(r"\bm\.?(?:tech|sc|com|ca|ba|s)\b", re.IGNORECASE),
]

YEARS_PATTERN = re.compile(r"(\d+)\+?\s*years?\s+(?:of\s+)?experience", re.IGNORECASE)


def extract_jd_keywords(jd_text: str, skill_names: Set[str]) -> Dict:
    """
    Pull structured requirements out of a job description.

    Skills come from the canonical skill database rather than raw word
    splitting, which would turn "Python." and "Python," into separate
    meaningless keywords.
    """
    matched_skills = {
        skill
        for skill in skill_names
        if re.search(rf"\b{re.escape(skill.lower())}\b", jd_text.lower())
    }

    qualifications = []
    for pattern in QUALIFICATION_PATTERNS:
        match = pattern.search(jd_text)
        if match:
            qualifications.append(match.group(0))

    years_match = YEARS_PATTERN.search(jd_text)
    required_years = int(years_match.group(1)) if years_match else None

    return {
        "skills": sorted(matched_skills),
        "qualifications": qualifications,
        "required_years": required_years,
    }


def analyze_jd_match(resume_text: str, jd_text: str, skill_names: Set[str]) -> Dict:
    """
    Compare a resume against one job description. Score out of 30.

    Only skills the job description actually names are considered, so a
    generic JD cannot inflate or deflate the result.
    """
    jd_keywords = extract_jd_keywords(jd_text, skill_names)
    resume_lower = resume_text.lower()

    matched_skills = []
    missing_skills = []
    for skill in jd_keywords["skills"]:
        if re.search(rf"\b{re.escape(skill.lower())}\b", resume_lower):
            matched_skills.append(skill)
        else:
            missing_skills.append(skill)

    total_jd_skills = len(jd_keywords["skills"])

    # A job description with no recognisable skills cannot be scored
    # honestly. Report that instead of inventing a number.
    if total_jd_skills == 0:
        return {
            "score": 0,
            "max": 30,
            "scorable": False,
            "skill_match_pct": 0.0,
            "matched_skills": [],
            "missing_skills": [],
            "jd_keywords_total": 0,
            "required_years": jd_keywords["required_years"],
            "suggestions": [
                "This job description does not list recognisable skills, so "
                "keyword matching was skipped.",
            ],
        }

    skill_match_pct = len(matched_skills) / total_jd_skills * 100

    if skill_match_pct >= 80:
        score = 30
    elif skill_match_pct >= 60:
        score = 22
    elif skill_match_pct >= 40:
        score = 14
    elif skill_match_pct >= 20:
        score = 7
    else:
        score = 2

    suggestions = []
    if missing_skills:
        suggestions.append(
            f"Consider mentioning these keywords from the job description, "
            f'if they apply to you: {", ".join(missing_skills[:5])}.'
        )
        suggestions.append(
            "Do not keyword-stuff — only add skills you can speak to in an " "interview."
        )

    return {
        "score": score,
        "max": 30,
        "scorable": True,
        "skill_match_pct": round(skill_match_pct, 1),
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "jd_keywords_total": total_jd_skills,
        "required_years": jd_keywords["required_years"],
        "suggestions": suggestions,
    }

    # --------------------------------------------------------------------------- #


# Orchestration
# --------------------------------------------------------------------------- #


def _rating_for(pct: float) -> str:
    """Translate a percentage into a letter grade users can act on."""
    if pct >= 85:
        return "A — Excellent"
    if pct >= 70:
        return "B — Good"
    if pct >= 55:
        return "C — Fair"
    if pct >= 40:
        return "D — Needs Improvement"
    return "F — Poor"


def _empty_result(message: str) -> Dict:
    """
    Placeholder result for text that cannot be analysed.

    This deliberately has the SAME keys as a real result. Callers such as
    the Celery task read fields like advanced_score_pct unconditionally, so
    a short-circuit return that omitted them would raise a KeyError.
    """
    return {
        "advanced_score": 0,
        "advanced_max": 70,
        "advanced_score_pct": 0.0,
        "rating": _rating_for(0),
        "analysable": False,
        "message": message,
        "breakdown": {},
        "top_suggestions": [
            "Upload a resume with more content so it can be analysed.",
        ],
        "has_jd_analysis": False,
    }


def run_full_analysis(
    resume_text: str,
    jd_text: Optional[str] = None,
    skill_names: Optional[Set[str]] = None,
) -> Dict:
    """
    Run every analyzer and combine them into one normalised score.

    Without a job description the maximum is 70 points; with one it is 100.
    The result is reported as a percentage so both modes are comparable.
    """
    if not resume_text or len(resume_text.strip()) < MIN_ANALYSABLE_LENGTH:
        return _empty_result("Resume text is too short to analyse.")

    action_verbs = analyze_action_verbs(resume_text)
    quantification = analyze_quantification(resume_text)
    language = analyze_language_quality(resume_text)

    breakdown = {
        "action_verbs": action_verbs,
        "quantification": quantification,
        "language_quality": language,
    }

    components = [action_verbs, quantification, language]

    jd_match = None
    if jd_text and skill_names:
        jd_match = analyze_jd_match(resume_text, jd_text, skill_names)
        breakdown["jd_match"] = jd_match
        components.append(jd_match)

    # A JD that yielded no keywords contributes no points and no ceiling,
    # otherwise the candidate would be punished for a vague job posting.
    jd_counts_toward_total = bool(jd_match and jd_match["scorable"])

    advanced_max = 70 + (30 if jd_counts_toward_total else 0)
    advanced_score = (
        action_verbs["score"]
        + quantification["score"]
        + language["score"]
        + (jd_match["score"] if jd_counts_toward_total else 0)
    )
    advanced_pct = round(advanced_score / advanced_max * 100, 1)

    all_suggestions = []
    for component in components:
        all_suggestions.extend(component.get("suggestions", []))

    return {
        "advanced_score": advanced_score,
        "advanced_max": advanced_max,
        "advanced_score_pct": advanced_pct,
        "rating": _rating_for(advanced_pct),
        "analysable": True,
        "breakdown": breakdown,
        # Capped at five: a long list of fixes makes people do nothing.
        "top_suggestions": all_suggestions[:5],
        "has_jd_analysis": jd_match is not None,
    }

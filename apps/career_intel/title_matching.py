"""
Match a person's job title against the career-graph node names.

People write their title however they like: "Backend Engineer", "Sr. Backend
Developer", "SDE II", "Data Scientist | Flipkart". The graph has one fixed
name per role. Matching these by exact string, then by first word, produced
confident wrong answers - "Backend Engineer" resolved to *Junior* Backend
Developer, and every path shown from there was for the wrong seniority.

The approach here:

1. Split off a company suffix ("at Acme", "| Flipkart").
2. Pull the seniority out of the words ("senior", "sr", "junior", "ii"), so
   it can be compared separately instead of drowning the role itself.
3. Fold the remaining words to a canonical form, because "engineer",
   "developer", "dev" and "sde" all name the same thing here.
4. Score the overlap, weighting each word by how rare it is across the node
   names. "backend" appears in a few names and says a lot; "developer"
   appears in half of them and says almost nothing.
5. Require at least one *distinctive* word in common. Without this, "Software
   Engineer" matches "Principal Engineer" on the strength of "engineer"
   alone, which is a confident answer to a question we cannot answer.

Pure functions over a list of names: no database, no Django, so the whole
thing is testable directly.
"""

import math
import re

# Seniority words, and how they rank. Extracted from the title and compared
# separately: "Senior Backend Developer" and "Backend Developer" share every
# other word, and the difference between them is the whole point.
SENIORITY_RANK = {
    "intern": 0,
    "trainee": 0,
    "junior": 1,
    "jr": 1,
    "associate": 1,
    "entry": 1,
    "graduate": 1,
    "grad": 1,
    "mid": 2,
    "ii": 2,
    "senior": 3,
    "sr": 3,
    "iii": 3,
    "lead": 4,
    "principal": 4,
    "staff": 4,
    "head": 5,
    "director": 5,
    "vp": 5,
    "chief": 5,
}

# Words that name the same role. Only folds that are safe in this domain -
# "architect" is deliberately not folded into "developer".
CANONICAL = {
    "engineer": "developer",
    "engineers": "developer",
    "dev": "developer",
    "devs": "developer",
    "programmer": "developer",
    "coder": "developer",
    "sde": "developer",
    "swe": "developer",
    "front": "frontend",
    "fe": "frontend",
    "back": "backend",
    "be": "backend",
    "fullstack": "full stack",
    "ui": "ui ux",
    "ux": "ui ux",
    "uiux": "ui ux",
    "pm": "product manager",
    "sre": "devops",
    "infra": "devops",
    "infrastructure": "devops",
    "ml": "data",
    "ai": "data",
}

# A company or employer usually follows one of these.
COMPANY_SUFFIX = re.compile(r"\s+(?:at|@|for|with)\s+|[|,()\u2013\u2014]")

# A word shared with a node name only counts as evidence if it appears in at
# most this share of node names. "developer" is in half of them and means
# little; "backend" is in a few and means a lot.
DISTINCTIVE_SHARE = 0.35

# Below this, the overlap is too thin to call a match.
MINIMUM_SCORE = 0.4


def parse_title(title):
    """
    Split a title into (seniority rank or None, set of canonical words).

        "Sr. Backend Developer at Acme" -> (3, {"backend", "developer"})
    """
    text = COMPANY_SUFFIX.split((title or "").lower().strip())[0]
    words = [word for word in re.split(r"[^a-z0-9]+", text) if word]

    rank = None
    canonical = []
    for word in words:
        if word in SENIORITY_RANK:
            # Only the first seniority word counts: "Senior Staff Engineer"
            # is senior, and taking the last would call it staff.
            if rank is None:
                rank = SENIORITY_RANK[word]
            continue
        canonical.extend(CANONICAL.get(word, word).split())

    return rank, set(canonical)


class TitleMatcher:
    """
    Matches titles against one fixed catalogue of names.

    Built once per catalogue because the word weights depend on the whole
    catalogue, not on any single name.
    """

    def __init__(self, names):
        self.names = list(names)
        self.parsed = {name: parse_title(name) for name in self.names}
        self.total = len(self.names) or 1
        self.document_frequency = {}
        for _, words in self.parsed.values():
            for word in words:
                self.document_frequency[word] = self.document_frequency.get(word, 0) + 1

    def weight(self, word):
        """Rare words carry more evidence than common ones."""
        frequency = self.document_frequency.get(word, 0)
        return math.log((self.total + 1) / (frequency + 1)) + 1

    def is_distinctive(self, word):
        return self.document_frequency.get(word, 0) <= DISTINCTIVE_SHARE * self.total

    def score(self, title, name):
        """Weighted overlap of two titles, between 0 and 1."""
        _, words = parse_title(title)
        _, other = self.parsed.get(name, parse_title(name))
        if not words or not other:
            return 0.0
        union = sum(self.weight(word) for word in words | other)
        if not union:
            return 0.0
        return sum(self.weight(word) for word in words & other) / union

    def ranked(self, title):
        """
        Every name, best first.

        Ties are broken so the same title always resolves to the same name:
        matching seniority first, then the shorter name, then alphabetically.
        Without the ordering, "Backend Engineer" could resolve to a different
        node run to run, which is worse than resolving to the wrong one.
        """
        rank, words = parse_title(title)

        def key(name):
            other_rank, _ = self.parsed[name]
            return (-self.score(title, name), other_rank != rank, len(name), name)

        return sorted(self.names, key=key)

    def best(self, title):
        """
        The one name this title means, or None.

        None is a real answer: "Software Engineer" names no single role in a
        graph that distinguishes backend from frontend, and guessing one
        sends the person down somebody else's career path.
        """
        rank, words = parse_title(title)
        if not words:
            return None

        # A name the person typed exactly always wins, even when its words are
        # too common to count as evidence on their own: "Principal Engineer"
        # shares only "engineer" with everything, and is still that node.
        for name in self.names:
            if self.parsed[name] == (rank, words):
                return name

        for name in self.ranked(title):
            _, other = self.parsed[name]
            shared = words & other
            if not shared:
                break
            if self.score(title, name) < MINIMUM_SCORE:
                break
            if any(self.is_distinctive(word) for word in shared):
                return name
        return None

    def suggestions(self, title, limit=5):
        """The closest names, for when nothing matched well enough."""
        return [name for name in self.ranked(title)[:limit]]

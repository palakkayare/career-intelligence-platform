"""
Matching a person's own job title to a node in the career graph.

Regression: the matcher took the first node whose name contained the first
word of the title. "Backend Engineer" resolved to *Junior* Backend Developer
and the person was shown a more junior person's career path, with nothing to
say the match was wrong.
"""

import pytest

from apps.career_intel.title_matching import TitleMatcher, parse_title

# The seeded catalogue, so these tests describe the real product.
NODES = [
    "Associate Product Manager",
    "Data Analyst",
    "Junior Backend Developer",
    "Junior Frontend Developer",
    "Junior UI/UX Designer",
    "Backend Developer",
    "Data Scientist",
    "DevOps Engineer",
    "Frontend Developer",
    "Full Stack Developer",
    "Product Manager",
    "UI/UX Designer",
    "Senior Backend Developer",
    "Senior Data Scientist",
    "Senior DevOps Engineer",
    "Senior Frontend Developer",
    "Senior Product Manager",
    "Senior UI/UX Designer",
    "Engineering Manager",
    "Principal Engineer",
    "Tech Lead",
    "CTO",
    "Engineering Director",
]


@pytest.fixture(scope="module")
def matcher():
    return TitleMatcher(NODES)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Backend Developer", "Backend Developer"),
        ("backend developer", "Backend Developer"),
        ("  Backend Developer  ", "Backend Developer"),
        ("Principal Engineer", "Principal Engineer"),
        ("CTO", "CTO"),
    ],
)
def test_a_name_from_the_catalogue_resolves_to_itself(matcher, title, expected):
    assert matcher.best(title) == expected


def test_every_node_name_resolves_to_itself(matcher):
    """If a catalogue name did not match itself, nothing else would be safe."""
    for name in NODES:
        assert matcher.best(name) == name


@pytest.mark.regression
@pytest.mark.parametrize(
    "title, expected",
    [
        # The bug: these picked Junior Backend Developer.
        ("Backend Engineer", "Backend Developer"),
        ("Backend Developer at Acme", "Backend Developer"),
        ("Backend Developer | Flipkart", "Backend Developer"),
        # These found nothing at all.
        ("Sr. Backend Developer", "Senior Backend Developer"),
        ("Sr Product Manager", "Senior Product Manager"),
        ("Front End Developer", "Frontend Developer"),
        ("Full-Stack Engineer", "Full Stack Developer"),
        ("UX Designer", "UI/UX Designer"),
        ("SRE", "DevOps Engineer"),
    ],
)
def test_titles_people_actually_write(matcher, title, expected):
    assert matcher.best(title) == expected


@pytest.mark.regression
@pytest.mark.parametrize(
    "title, expected",
    [
        ("Senior Backend Developer", "Senior Backend Developer"),
        ("Junior Backend Developer", "Junior Backend Developer"),
        ("Backend Developer", "Backend Developer"),
    ],
)
def test_seniority_is_not_dropped(matcher, title, expected):
    """
    Showing a senior engineer the junior's path is the failure that started
    this: every onward step is one the person took years ago.
    """
    assert matcher.best(title) == expected


@pytest.mark.parametrize(
    "title",
    ["Software Engineer", "SDE II", "Junior Dev", "ML Engineer", "Chef", "Marketing Head", ""],
)
def test_a_title_with_no_clear_role_matches_nothing(matcher, title):
    """
    None is a real answer. "Software Engineer" does not say backend or
    frontend, and guessing sends the person down somebody else's path.
    """
    assert matcher.best(title) is None


def test_a_failed_match_still_offers_the_closest_names(matcher):
    suggestions = matcher.suggestions("ML Engineer", limit=3)

    assert len(suggestions) == 3
    assert "Data Scientist" in suggestions


@pytest.mark.regression
def test_the_same_title_always_gives_the_same_answer(matcher):
    """
    The old query had no ordering, so which wrong node it picked could change
    between requests.
    """
    answers = {matcher.best("Backend Engineer") for _ in range(20)}

    assert answers == {"Backend Developer"}


@pytest.mark.parametrize(
    "title, rank, words",
    [
        ("Sr. Backend Developer at Acme", 3, {"backend", "developer"}),
        ("Junior Frontend Engineer", 1, {"frontend", "developer"}),
        ("Product Manager", None, {"product", "manager"}),
        ("Senior Staff Engineer", 3, {"developer"}),
    ],
)
def test_parsing_splits_seniority_from_the_role(title, rank, words):
    assert parse_title(title) == (rank, words)


def test_an_empty_catalogue_matches_nothing():
    assert TitleMatcher([]).best("Backend Developer") is None

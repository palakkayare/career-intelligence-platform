"""
Career path graph.

Roles are nodes, transitions are edges, and the service answers "how do I
get from here to there". The graph is built fresh from the database on every
call, so these tests build small purpose-shaped graphs rather than relying
on whatever the seed command happens to contain.
"""
from decimal import Decimal

import pytest

from apps.career_intel.models import CareerPathEdge, CareerPathNode
from apps.career_intel.path_services import CareerPathService

pytestmark = pytest.mark.django_db


def node(name, slug, level=CareerPathNode.Level.MID, salary=None, years=3):
    return CareerPathNode.objects.create(
        name=name, slug=slug, level=level,
        typical_experience_years=years,
        avg_salary_inr=Decimal(str(salary)) if salary else None,
    )


def edge(from_node, to_node, months=12, weight=3, skills=None):
    link = CareerPathEdge.objects.create(
        from_node=from_node, to_node=to_node,
        time_months=months, weight=weight,
        rationale=f'{from_node.name} to {to_node.name}',
    )
    if skills:
        link.required_skills.set(skills)
    return link


@pytest.fixture
def straight_line():
    """junior -> mid -> senior, the simplest possible career ladder."""
    junior = node('Junior Developer', 'junior-developer',
                  CareerPathNode.Level.JUNIOR, salary=600000, years=1)
    mid = node('Backend Developer', 'backend-developer', salary=1500000)
    senior = node('Senior Engineer', 'senior-engineer',
                  CareerPathNode.Level.SENIOR, salary=3000000, years=7)

    edge(junior, mid, months=18, weight=2)
    edge(mid, senior, months=24, weight=4)
    return junior, mid, senior


@pytest.fixture
def two_routes(straight_line):
    """
    Adds a slower but easier detour through a lead role, so the graph has a
    genuine choice between optimising for time and optimising for effort.
    """
    junior, mid, senior = straight_line
    lead = node('Tech Lead', 'tech-lead', CareerPathNode.Level.SENIOR)

    edge(mid, lead, months=6, weight=1)
    edge(lead, senior, months=30, weight=1)
    return junior, mid, senior, lead


# --------------------------------------------------------------------------
# Graph construction
# --------------------------------------------------------------------------

@pytest.mark.regression
def test_the_graph_is_built_from_active_rows(straight_line):
    """Regression: path_services.py sat at 17% coverage."""
    graph = CareerPathService.build_graph()

    assert set(graph.nodes) == {
        'junior-developer', 'backend-developer', 'senior-engineer',
    }
    assert graph.number_of_edges() == 2


def test_an_inactive_node_is_left_out(straight_line):
    _, mid, _ = straight_line
    mid.is_active = False
    mid.save()

    graph = CareerPathService.build_graph()

    assert 'backend-developer' not in graph.nodes


@pytest.mark.regression
def test_an_edge_dies_with_either_of_its_nodes(straight_line):
    """
    An edge pointing at a retired role would produce paths through a role
    nobody can hold any more.
    """
    _, mid, _ = straight_line
    mid.is_active = False
    mid.save()

    graph = CareerPathService.build_graph()

    assert graph.number_of_edges() == 0


def test_an_inactive_edge_is_left_out(straight_line):
    junior, mid, _ = straight_line
    CareerPathEdge.objects.filter(from_node=junior, to_node=mid).update(
        is_active=False,
    )

    graph = CareerPathService.build_graph()

    assert not graph.has_edge('junior-developer', 'backend-developer')


def test_node_attributes_survive_into_the_graph(straight_line):
    graph = CareerPathService.build_graph()
    attrs = graph.nodes['backend-developer']

    assert attrs['name'] == 'Backend Developer'
    assert attrs['avg_salary_inr'] == 1500000.0


def test_edge_attributes_survive_into_the_graph(straight_line, skill):
    junior, mid, _ = straight_line
    CareerPathEdge.objects.filter(from_node=junior).first().required_skills.set(
        [skill],
    )

    graph = CareerPathService.build_graph()
    attrs = graph.edges['junior-developer', 'backend-developer']

    assert attrs['time_months'] == 18
    assert attrs['required_skill_names'] == [skill.name]


# --------------------------------------------------------------------------
# Path finding
# --------------------------------------------------------------------------

def test_a_direct_route_is_found(straight_line):
    result = CareerPathService.find_paths(
        'junior-developer', 'senior-engineer',
    )

    assert result['paths']
    assert result['from']['name'] == 'Junior Developer'
    assert result['to']['name'] == 'Senior Engineer'


def test_an_unknown_starting_role_returns_the_same_shape(straight_line):
    """
    The frontend reads 'from', 'to' and 'paths' unconditionally, so the error
    cases have to carry those keys too.
    """
    result = CareerPathService.find_paths('nope', 'senior-engineer')

    assert 'error' in result
    assert result['paths'] == []
    assert 'from' in result and 'to' in result


def test_an_unknown_target_role_is_reported(straight_line):
    result = CareerPathService.find_paths('junior-developer', 'nope')

    assert 'error' in result
    assert result['paths'] == []


def test_asking_for_the_role_you_already_hold(straight_line):
    result = CareerPathService.find_paths(
        'backend-developer', 'backend-developer',
    )

    assert result['paths'] == []
    assert 'already' in result['message'].lower()


@pytest.mark.regression
def test_a_backwards_query_says_so_rather_than_erroring(straight_line):
    """
    The graph is forward-only by design, so senior-to-junior has no route.
    That is an answer, not a failure.
    """
    result = CareerPathService.find_paths(
        'senior-engineer', 'junior-developer',
    )

    assert result['paths'] == []
    assert 'no path' in result['message'].lower()


def test_a_path_carries_its_steps_and_totals(straight_line):
    result = CareerPathService.find_paths(
        'junior-developer', 'senior-engineer',
    )
    path = result['paths'][0]

    assert path['total_steps'] == 2
    assert path['total_months'] == 42  # 18 + 24
    assert path['total_years'] == 3.5
    assert path['total_difficulty'] == 6  # 2 + 4
    assert len(path['transitions']) == 2


def test_a_path_lists_every_skill_it_requires(straight_line, skill, make_job):
    from apps.skills.models import Skill

    junior, mid, senior = straight_line
    second_skill = Skill.objects.create(name='Kubernetes')
    CareerPathEdge.objects.get(from_node=junior).required_skills.set([skill])
    CareerPathEdge.objects.get(from_node=mid).required_skills.set([second_skill])

    result = CareerPathService.find_paths(
        'junior-developer', 'senior-engineer',
    )

    assert result['paths'][0]['all_skills_to_learn'] == sorted(
        [skill.name, 'Kubernetes'],
    )


@pytest.mark.regression
def test_one_obvious_route_is_not_returned_three_times(straight_line):
    """
    Fastest, easiest and most direct all resolve to the same path here.
    Reporting it three times would look like three options.
    """
    result = CareerPathService.find_paths(
        'junior-developer', 'senior-engineer',
    )

    assert len(result['paths']) == 1


def test_time_and_effort_can_disagree(two_routes):
    """
    The detour is slower overall but easier at every step, so a graph with a
    real trade-off should surface more than one option.
    """
    result = CareerPathService.find_paths(
        'backend-developer', 'senior-engineer',
    )

    assert len(result['paths']) >= 2
    labels = {path['optimization'] for path in result['paths']}
    assert 'fastest' in labels


def test_max_paths_caps_the_primary_candidates(two_routes):
    result = CareerPathService.find_paths(
        'backend-developer', 'senior-engineer', max_paths=1,
    )

    primary = [
        path for path in result['paths']
        if path['optimization'] != 'alternative'
    ]
    assert len(primary) == 1


# --------------------------------------------------------------------------
# Reachability
# --------------------------------------------------------------------------

def test_everything_downstream_is_reachable(straight_line):
    result = CareerPathService.reachable_from('junior-developer')

    slugs = {item['slug'] for item in result['reachable']}
    assert slugs == {'backend-developer', 'senior-engineer'}
    assert result['total_reachable'] == 2


def test_reachable_roles_carry_hops_and_time(straight_line):
    result = CareerPathService.reachable_from('junior-developer')
    by_slug = {item['slug']: item for item in result['reachable']}

    assert by_slug['backend-developer']['hops'] == 1
    assert by_slug['backend-developer']['estimated_months'] == 18
    assert by_slug['senior-engineer']['hops'] == 2
    assert by_slug['senior-engineer']['estimated_months'] == 42


def test_the_hop_limit_is_respected(straight_line):
    result = CareerPathService.reachable_from('junior-developer', max_hops=1)

    assert result['total_reachable'] == 1


def test_results_are_ordered_by_distance(straight_line):
    result = CareerPathService.reachable_from('junior-developer')

    hops = [item['hops'] for item in result['reachable']]
    assert hops == sorted(hops)


def test_a_terminal_role_reaches_nothing(straight_line):
    result = CareerPathService.reachable_from('senior-engineer')

    assert result['reachable'] == []


def test_an_unknown_role_is_reported(straight_line):
    result = CareerPathService.reachable_from('nope')

    assert 'error' in result
    assert result['reachable'] == []


# --------------------------------------------------------------------------
# Graph export
# --------------------------------------------------------------------------

def test_the_whole_graph_can_be_exported(straight_line):
    result = CareerPathService.get_graph_data()

    assert len(result['nodes']) == 3
    assert len(result['edges']) == 2


def test_exported_nodes_carry_display_fields(straight_line):
    result = CareerPathService.get_graph_data()
    backend = next(
        item for item in result['nodes'] if item['id'] == 'backend-developer'
    )

    assert backend['name'] == 'Backend Developer'
    assert 'level' in backend


def test_an_empty_graph_exports_cleanly():
    """A fresh install has no career data seeded yet."""
    result = CareerPathService.get_graph_data()

    assert result['nodes'] == []
    assert result['edges'] == []
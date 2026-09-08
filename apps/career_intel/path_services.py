"""
apps/career_intel/path_services.py

Career path engine built on NetworkX.

Roles are nodes, transitions are directed edges. Each edge carries an effort
weight and a typical duration, so the same pair of roles can be routed
differently depending on what the user wants to optimise for.
"""

import logging
from typing import Dict, List, Optional

import networkx as nx

from .models import CareerPathEdge, CareerPathNode

logger = logging.getLogger(__name__)


class CareerPathService:
    """Builds the career graph from the database and runs path queries on it."""

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------
    @classmethod
    def build_graph(cls) -> nx.DiGraph:
        """
        Build a directed graph from the active nodes and edges.

        The graph is rebuilt on every call. That is fine at this size (roughly
        23 nodes and 28 edges, two queries total). Phase 4 should cache it in
        Redis and invalidate on edge save.
        """
        graph = nx.DiGraph()

        for node in CareerPathNode.objects.filter(is_active=True):
            graph.add_node(
                node.slug,
                node_id=node.id,
                name=node.name,
                level=node.level,
                category=node.category,
                avg_salary_inr=float(node.avg_salary_inr) if node.avg_salary_inr else None,
                typical_experience_years=node.typical_experience_years,
            )

        edges = (
            CareerPathEdge.objects
            .filter(is_active=True, from_node__is_active=True, to_node__is_active=True)
            .select_related('from_node', 'to_node')
            # Without this prefetch, reading required_skills below would fire
            # one query per edge.
            .prefetch_related('required_skills')
        )

        for edge in edges:
            skills = list(edge.required_skills.all())
            graph.add_edge(
                edge.from_node.slug,
                edge.to_node.slug,
                edge_id=edge.id,
                weight=edge.weight,
                time_months=edge.time_months,
                transition_type=edge.transition_type,
                rationale=edge.rationale,
                required_skill_ids=[s.id for s in skills],
                required_skill_names=[s.name for s in skills],
            )

        return graph

    # ------------------------------------------------------------------
    # Path finding
    # ------------------------------------------------------------------
    @classmethod
    def find_paths(cls, from_slug: str, to_slug: str, max_paths: int = 3) -> Dict:
        """
        Find candidate career paths between two roles.

        Returns up to three primary candidates -- fastest by time, easiest by
        effort, and most direct by hop count -- plus alternative routes when
        they exist. Identical routes are returned only once, so asking for a
        path with an obvious single route yields a single option.

        The response always carries 'from', 'to' and 'paths' keys so the
        frontend can rely on one shape, even in the error cases.
        """
        graph = cls.build_graph()

        # --- Validate the endpoints before touching any algorithm ---
        if from_slug not in graph.nodes:
            return {
                'error': f'Unknown starting role: {from_slug}',
                'from': None, 'to': None, 'paths': [],
            }
        if to_slug not in graph.nodes:
            return {
                'error': f'Unknown target role: {to_slug}',
                'from': None, 'to': None, 'paths': [],
            }

        origin = cls._node_summary(graph, from_slug)
        destination = cls._node_summary(graph, to_slug)

        if from_slug == to_slug:
            return {
                'message': 'You are already in this role.',
                'from': origin, 'to': destination, 'paths': [],
            }

        # --- Primary candidates ---
        # Each optimisation may return the same route; seen_paths keeps the
        # response free of duplicates.
        candidates = []
        seen_paths = set()

        try:
            fastest = nx.shortest_path(graph, from_slug, to_slug, weight='time_months')
            seen_paths.add(tuple(fastest))
            candidates.append({
                'optimization': 'fastest',
                'label': 'Fastest path',
                'path': fastest,
            })
        except nx.NetworkXNoPath:
            # No route at all. The career graph is mostly forward-only, so this
            # is the expected answer for backwards queries.
            return {
                'message': (
                    f'No path exists from {origin["name"]} to {destination["name"]}. '
                    f'Career transitions in this graph move forward only.'
                ),
                'from': origin, 'to': destination, 'paths': [],
            }

        easiest = nx.shortest_path(graph, from_slug, to_slug, weight='weight')
        if tuple(easiest) not in seen_paths:
            seen_paths.add(tuple(easiest))
            candidates.append({
                'optimization': 'easiest',
                'label': 'Easiest path',
                'path': easiest,
            })

        # No weight argument means every edge counts as 1, i.e. fewest hops.
        direct = nx.shortest_path(graph, from_slug, to_slug)
        if tuple(direct) not in seen_paths:
            seen_paths.add(tuple(direct))
            candidates.append({
                'optimization': 'direct',
                'label': 'Most direct',
                'path': direct,
            })

        enriched_paths = []
        for candidate in candidates[:max_paths]:
            enriched = cls._enrich_path(graph, candidate['path'])
            enriched['optimization'] = candidate['optimization']
            enriched['label'] = candidate['label']
            enriched_paths.append(enriched)

        # --- Alternative routes, up to two beyond the primary candidates ---
        alternative_limit = max_paths + 2
        try:
            alternatives = list(
                nx.all_simple_paths(graph, from_slug, to_slug, cutoff=5)
            )
            alternatives.sort(key=len)

            for path in alternatives:
                if len(enriched_paths) >= alternative_limit:
                    break
                if tuple(path) in seen_paths:
                    continue
                seen_paths.add(tuple(path))
                enriched = cls._enrich_path(graph, path)
                enriched['optimization'] = 'alternative'
                enriched['label'] = 'Alternative route'
                enriched_paths.append(enriched)
        except nx.NodeNotFound:
            pass

        return {
            'from': origin,
            'to': destination,
            'paths': enriched_paths,
            'total_options_found': len(enriched_paths),
        }

    # ------------------------------------------------------------------
    # Reachability
    # ------------------------------------------------------------------
    @classmethod
    def reachable_from(cls, from_slug: str, max_hops: int = 3) -> Dict:
        """
        Every role reachable from a starting role within max_hops.

        Powers the "what can I become from here?" view. Results are sorted by
        hop count first, then by estimated time.
        """
        graph = cls.build_graph()

        if from_slug not in graph.nodes:
            return {'error': f'Unknown role: {from_slug}', 'from': None, 'reachable': []}

        reachable = []

        # nx.descendants returns every node with a path from from_slug, at any
        # distance; max_hops then trims that set.
        for target in nx.descendants(graph, from_slug):
            hops = nx.shortest_path_length(graph, from_slug, target)
            if hops > max_hops:
                continue

            attrs = graph.nodes[target]
            quickest = nx.shortest_path(graph, from_slug, target, weight='time_months')
            total_months = sum(
                graph.edges[quickest[i], quickest[i + 1]]['time_months']
                for i in range(len(quickest) - 1)
            )

            reachable.append({
                'slug': target,
                'name': attrs['name'],
                'level': attrs['level'],
                'category': attrs['category'],
                'hops': hops,
                'estimated_months': total_months,
                'estimated_years': round(total_months / 12, 1),
            })

        reachable.sort(key=lambda item: (item['hops'], item['estimated_months']))

        return {
            'from': cls._node_summary(graph, from_slug),
            'max_hops': max_hops,
            'reachable': reachable,
            'total_reachable': len(reachable),
        }

    # ------------------------------------------------------------------
    # Visualisation
    # ------------------------------------------------------------------
    @classmethod
    def get_graph_data(cls) -> Dict:
        """Return the whole graph as JSON for a frontend renderer (D3, Sigma.js)."""
        graph = cls.build_graph()

        nodes_list = [
            {
                'id': slug,
                'name': attrs['name'],
                'level': attrs['level'],
                'category': attrs['category'],
                'avg_salary_inr': attrs.get('avg_salary_inr'),
            }
            for slug, attrs in graph.nodes(data=True)
        ]

        edges_list = [
            {
                'source': source,
                'target': target,
                'weight': attrs['weight'],
                'time_months': attrs['time_months'],
                'transition_type': attrs['transition_type'],
            }
            for source, target, attrs in graph.edges(data=True)
        ]

        return {
            'nodes': nodes_list,
            'edges': edges_list,
            'total_nodes': len(nodes_list),
            'total_edges': len(edges_list),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _node_summary(graph, slug: str) -> Dict:
        """Compact node description, used wherever a node is referenced."""
        attrs = graph.nodes[slug]
        return {
            'slug': slug,
            'name': attrs['name'],
            'level': attrs['level'],
            'avg_salary_inr': attrs.get('avg_salary_inr'),
        }

    @classmethod
    def _enrich_path(cls, graph, path: List[str]) -> Optional[Dict]:
        """
        Turn a raw path (a list of slugs) into a full response object with
        per-step transitions, aggregate time and effort, and the union of all
        skills the route requires.
        """
        if not path:
            return None

        transitions = []
        all_skills = set()
        total_months = 0
        total_weight = 0

        for i in range(len(path) - 1):
            from_slug, to_slug = path[i], path[i + 1]
            attrs = graph.edges[from_slug, to_slug]

            transitions.append({
                'from': cls._node_summary(graph, from_slug),
                'to': cls._node_summary(graph, to_slug),
                'time_months': attrs['time_months'],
                'difficulty_weight': attrs['weight'],
                'transition_type': attrs['transition_type'],
                'rationale': attrs['rationale'],
                'required_skills': [
                    {'id': skill_id, 'name': skill_name}
                    for skill_id, skill_name in zip(
                        attrs['required_skill_ids'],
                        attrs['required_skill_names'],
                    )
                ],
            })

            all_skills.update(attrs['required_skill_names'])
            total_months += attrs['time_months']
            total_weight += attrs['weight']

        return {
            'nodes': [cls._node_summary(graph, slug) for slug in path],
            'transitions': transitions,
            'total_steps': len(path) - 1,
            'total_months': total_months,
            'total_years': round(total_months / 12, 1),
            'total_difficulty': total_weight,
            'all_skills_to_learn': sorted(all_skills),
        }
import itertools
import random

import networkx as nx
import pytest

from src.graph import AdjacencyGraph
from src.routing.weights import distance_weight, free_flow_weight
from src.routing.yen import overlap_similarity, yen_k_shortest
from tests.helpers import close, random_geo_graph, synthetic_city, to_simple_digraph


def nx_costs(G, s, t, k):
    gen = nx.shortest_simple_paths(G, s, t, weight="weight")
    return [nx.path_weight(G, p, weight="weight") for p in itertools.islice(gen, k)]


@pytest.mark.parametrize("algorithm", ["dijkstra", "astar"])
@pytest.mark.parametrize("seed", range(40))
def test_first_k_costs_match_networkx(seed, algorithm):
    rng = random.Random(seed)
    g = random_geo_graph(seed, n=rng.randint(6, 18), extra_edges=rng.randint(10, 40), parallel=False)
    G = to_simple_digraph(g, "time")
    weight = free_flow_weight(g)
    for _ in range(3):
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        if s == t:
            continue
        k = rng.randint(1, 6)
        expected = nx_costs(G, s, t, k) if nx.has_path(G, s, t) else []
        res = yen_k_shortest(g, s, t, weight, k, algorithm=algorithm)
        got = [p.cost for p in res.paths]
        assert len(got) == len(expected)
        for a, b in zip(got, expected):
            assert close(a, b, rel=1e-9, abs_=1e-9)


@pytest.mark.parametrize("seed", range(25))
def test_paths_are_loopless_distinct_and_sorted(seed):
    rng = random.Random(seed)
    g = random_geo_graph(seed, n=14, extra_edges=40, parallel=True)
    weight = distance_weight(g)
    s, t = rng.sample(range(g.n), 2)
    res = yen_k_shortest(g, s, t, weight, 8)
    seen = set()
    previous = -1.0
    for path in res.paths:
        assert len(set(path.nodes)) == len(path.nodes)
        assert path.nodes[0] == s and path.nodes[-1] == t
        key = tuple(path.edges)
        assert key not in seen
        seen.add(key)
        assert path.cost >= previous - 1e-9
        previous = path.cost
        recomputed = sum(weight(e, 0.0) for e in path.edges)
        assert close(recomputed, path.cost)
        for e, a, b in zip(path.edges, path.nodes, path.nodes[1:]):
            assert g.edge_source(e) == a and g.edge_target(e) == b


def test_unreachable_and_trivial_cases():
    g = AdjacencyGraph([1, 2, 3], [24.0, 24.001, 24.002], [67.0] * 3)
    g.add_edge(0, 1, 5.0, 5.0)
    weight = distance_weight(g)
    assert yen_k_shortest(g, 0, 2, weight, 3).paths == []
    single = yen_k_shortest(g, 1, 1, weight, 3)
    assert len(single.paths) == 1 and single.paths[0].cost == 0.0
    with pytest.raises(ValueError):
        yen_k_shortest(g, 0, 1, weight, 0)


def test_fewer_paths_than_k_available():
    g = AdjacencyGraph([1, 2, 3], [24.0, 24.001, 24.002], [67.0] * 3)
    g.add_edge(0, 1, 1.0, 1.0)
    g.add_edge(1, 2, 1.0, 1.0)
    res = yen_k_shortest(g, 0, 2, distance_weight(g), 5)
    assert len(res.paths) == 1


def test_overlap_similarity_is_length_weighted_jaccard():
    lengths = [100.0, 300.0, 50.0, 50.0]
    assert overlap_similarity([0, 1], [0, 1], lengths) == 1.0
    assert overlap_similarity([0, 1], [2, 3], lengths) == 0.0
    assert overlap_similarity([0, 1], [1, 2], lengths) == pytest.approx(300 / 450)
    assert overlap_similarity([], [], [1.0]) == 1.0


def ladder_with_detours():
    n = 12
    lat = [24.86 + 0.0005 * i for i in range(n)]
    g = AdjacencyGraph(list(range(n)), lat, [67.03] * n)
    for a, b in zip(range(n - 1), range(1, n)):
        g.add_edge(a, b, 100.0, 10.0)
        g.add_edge(b, a, 100.0, 10.0)
    for a, b in [(1, 3), (5, 7), (8, 10)]:
        g.add_edge(a, b, 210.0, 21.0)
        g.add_edge(b, a, 210.0, 21.0)
    return g


def test_diversity_filter_removes_near_duplicates():
    g = ladder_with_detours()
    weight = distance_weight(g)
    lengths = g.weight_list("length")
    plain = yen_k_shortest(g, 0, 11, weight, 4)
    assert len(plain.paths) == 4
    assert all(overlap_similarity(plain.paths[0].edges, other.edges, lengths) > 0.6 for other in plain.paths[1:])
    diverse = yen_k_shortest(g, 0, 11, weight, 4, diversity_threshold=0.6)
    for a, b in itertools.combinations(diverse.paths, 2):
        assert overlap_similarity(a.edges, b.edges, lengths) <= 0.6
    assert diverse.rejected_as_similar > 0
    assert diverse.enumerated > len(diverse.paths)
    assert diverse.paths[0].cost == plain.paths[0].cost


def test_diversity_search_reaches_a_genuinely_different_route():
    g = AdjacencyGraph([1, 2, 3, 4, 5, 6, 7], [24.86 + 0.0005 * i for i in range(7)], [67.03] * 7)
    for a, b, w in [(0, 1, 100), (1, 2, 100), (2, 6, 100), (1, 3, 105), (3, 2, 105)]:
        g.add_edge(a, b, float(w), float(w))
    for a, b, w in [(0, 4, 160), (4, 5, 160), (5, 6, 160)]:
        g.add_edge(a, b, float(w), float(w))
    weight = distance_weight(g)
    plain = yen_k_shortest(g, 0, 6, weight, 2)
    diverse = yen_k_shortest(g, 0, 6, weight, 2, diversity_threshold=0.3)
    assert plain.paths[1].nodes == [0, 1, 3, 2, 6]
    assert diverse.paths[1].nodes == [0, 4, 5, 6]


def test_threshold_of_one_accepts_everything():
    g = synthetic_city(8, 8)
    weight = free_flow_weight(g)
    res = yen_k_shortest(g, 0, g.n - 1, weight, 5, diversity_threshold=1.0)
    assert len(res.paths) == 5 and res.rejected_as_similar == 0


def test_search_limit_stops_the_diversity_loop():
    g = synthetic_city(8, 8)
    weight = free_flow_weight(g)
    res = yen_k_shortest(g, 0, g.n - 1, weight, 5, diversity_threshold=0.0, max_paths=6)
    assert res.enumerated <= 6
    assert len(res.paths) < 5


def test_real_city_alternatives_are_diverse_by_default():
    g = synthetic_city(14, 14, seed=2)
    weight = free_flow_weight(g)
    lengths = g.weight_list("length")
    res = yen_k_shortest(g, 0, g.n - 1, weight, 4, diversity_threshold=0.7)
    assert len(res.paths) >= 2
    for a, b in itertools.combinations(res.paths, 2):
        assert overlap_similarity(a.edges, b.edges, lengths) <= 0.7

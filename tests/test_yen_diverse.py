import itertools
import random

import networkx as nx
import pytest

from src.congestion import CongestionModel
from src.routing.astar import astar
from src.routing.dijkstra import backward_distances, dijkstra
from src.routing.weights import distance_weight, free_flow_weight
from src.routing.yen import overlap_similarity, yen_k_shortest
from tests.helpers import close, random_geo_graph, synthetic_city, to_networkx, to_simple_digraph


@pytest.mark.parametrize("seed", range(20))
def test_backward_distances_match_networkx_on_the_reversed_graph(seed):
    g = random_geo_graph(seed, n=25, extra_edges=60)
    weight = distance_weight(g)
    target = random.Random(seed).randrange(g.n)
    dist, settled, relaxed = backward_distances(g, target, weight)
    expected = nx.single_source_dijkstra_path_length(to_networkx(g, "length").reverse(), target)
    assert set(dist) == set(expected)
    for node, value in expected.items():
        assert close(dist[node], value)
    assert settled == len(dist) and relaxed >= settled - 1


@pytest.mark.parametrize("seed", range(30))
def test_reverse_heuristic_yen_matches_networkx(seed):
    rng = random.Random(seed)
    g = random_geo_graph(seed, n=rng.randint(6, 16), extra_edges=rng.randint(10, 35), parallel=False)
    G = to_simple_digraph(g, "time")
    weight = free_flow_weight(g)
    s, t = rng.sample(range(g.n), 2)
    k = rng.randint(1, 5)
    expected = []
    if nx.has_path(G, s, t):
        expected = [
            nx.path_weight(G, p, weight="weight") for p in itertools.islice(nx.shortest_simple_paths(G, s, t, weight="weight"), k)
        ]
    res = yen_k_shortest(g, s, t, weight, k, algorithm="astar", heuristic="reverse")
    assert len(res.paths) == len(expected)
    for got, want in zip(res.paths, expected):
        assert close(got.cost, want)


def test_reverse_heuristic_with_time_dependent_weight_matches_dijkstra():
    g = synthetic_city(12, 12, seed=4)
    model = CongestionModel(g)
    weight = model.weight("weekday", 8.5 * 3600)
    for s, t in ((0, g.n - 1), (5, 100), (30, 7)):
        plain = yen_k_shortest(g, s, t, weight, 4, algorithm="dijkstra")
        fast = yen_k_shortest(g, s, t, weight, 4, algorithm="astar", heuristic="reverse")
        assert [round(p.cost, 6) for p in plain.paths] == [round(p.cost, 6) for p in fast.paths]
        assert fast.settled <= plain.settled


def test_reverse_heuristic_needs_a_lower_bound():
    from src.routing.weights import make_weight

    g = synthetic_city(5, 5)
    weight = make_weight(lambda e, d: 1.0, "td", time_dependent=True)
    with pytest.raises(ValueError):
        yen_k_shortest(g, 0, 20, weight, 2, algorithm="astar", heuristic="reverse")
    with pytest.raises(ValueError):
        yen_k_shortest(g, 0, 20, distance_weight(g), 2, heuristic="nonsense")


@pytest.mark.parametrize("engine", ["dijkstra", "astar"])
def test_cost_limit_stops_the_search(engine):
    g = synthetic_city(8, 8)
    weight = distance_weight(g)
    optimum = dijkstra(g, 0, g.n - 1, weight).cost

    def run(limit):
        if engine == "dijkstra":
            return dijkstra(g, 0, g.n - 1, weight, cost_limit=limit)
        return astar(g, 0, g.n - 1, weight, lambda u: 0.0, cost_limit=limit)

    assert not run(optimum * 0.99).found
    found = run(optimum * 1.0000001)
    assert found.found and close(found.cost, optimum)
    assert run(float("inf")).found


def test_max_cost_ratio_drops_expensive_alternatives():
    g = synthetic_city(10, 10, seed=2)
    weight = free_flow_weight(g)
    unlimited = yen_k_shortest(g, 0, g.n - 1, weight, 12)
    limited = yen_k_shortest(g, 0, g.n - 1, weight, 12, max_cost_ratio=1.02)
    best = unlimited.paths[0].cost
    assert all(p.cost <= best * 1.02 + 1e-9 for p in limited.paths)
    assert len(limited.paths) <= len(unlimited.paths)


def test_window_mode_returns_loopless_diverse_routes_quickly():
    g = synthetic_city(16, 16, seed=6)
    model = CongestionModel(g)
    weight = model.weight("weekday", 9 * 3600)
    lengths = g.weight_list("length")
    theta = 0.7
    window = (1 - theta) / (1 + theta)
    s, t = 2, g.n - 3
    cap = 24
    filtered_only = yen_k_shortest(
        g, s, t, weight, 4, algorithm="astar", heuristic="reverse", diversity_threshold=theta, max_paths=cap
    )
    windowed = yen_k_shortest(
        g,
        s,
        t,
        weight,
        4,
        algorithm="astar",
        heuristic="reverse",
        diversity_threshold=theta,
        max_paths=cap,
        window_fraction=window,
        spur_stride_fraction=window / 4,
        max_cost_ratio=1.5,
    )
    assert len(windowed.paths) >= len(filtered_only.paths)
    assert len(windowed.paths) >= 3
    for path in windowed.paths:
        assert len(set(path.nodes)) == len(path.nodes)
    for a, b in itertools.combinations(windowed.paths, 2):
        assert overlap_similarity(a.edges, b.edges, lengths) <= theta
    assert windowed.paths[0].cost == pytest.approx(filtered_only.paths[0].cost)


def test_stride_reduces_the_number_of_spur_searches():
    g = synthetic_city(16, 16, seed=6)
    weight = free_flow_weight(g)
    common = dict(algorithm="astar", heuristic="reverse", diversity_threshold=0.7, max_paths=8, window_fraction=0.17)
    dense = yen_k_shortest(g, 0, g.n - 1, weight, 3, **common)
    sparse = yen_k_shortest(g, 0, g.n - 1, weight, 3, spur_stride_fraction=0.05, **common)
    assert sparse.spur_searches < dense.spur_searches


def test_window_zero_is_exact_yen():
    g = synthetic_city(8, 8, seed=1)
    weight = free_flow_weight(g)
    exact = yen_k_shortest(g, 0, g.n - 1, weight, 6)
    same = yen_k_shortest(g, 0, g.n - 1, weight, 6, window_fraction=0.0, spur_stride_fraction=0.0)
    assert [p.edges for p in exact.paths] == [p.edges for p in same.paths]

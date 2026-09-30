import math
import random

import networkx as nx
import pytest

from src.graph import AdjacencyGraph, haversine_m
from src.routing.astar import astar
from src.routing.bidirectional import bidirectional_dijkstra
from src.routing.dijkstra import dijkstra
from src.routing.weights import (
    combined_weight,
    distance_weight,
    free_flow_weight,
    haversine_heuristic,
    make_weight,
)
from tests.helpers import close, random_geo_graph, synthetic_city, to_networkx

INF = math.inf


def edge_weight(g, kind):
    arr = g.weight_list(kind)
    return make_weight(lambda eid, d: arr[eid], kind)


def check_path(g, res, weight, s, t):
    assert res.found
    assert res.nodes[0] == s and res.nodes[-1] == t
    assert len(res.nodes) == len(res.edges) + 1
    total = 0.0
    for eid, a, b in zip(res.edges, res.nodes, res.nodes[1:]):
        assert g.edge_source(eid) == a and g.edge_target(eid) == b
        total += weight(eid, total)
    assert close(total, res.cost, rel=1e-9, abs_=1e-9)


def all_searches(g, s, t, weight, kind_weight_heuristic=None):
    results = {
        "dijkstra_lazy": dijkstra(g, s, t, weight),
        "dijkstra_dk": dijkstra(g, s, t, weight, heap="decrease_key"),
        "bidirectional": bidirectional_dijkstra(g, s, t, weight),
        "astar_zero": astar(g, s, t, weight, lambda u: 0.0),
    }
    if kind_weight_heuristic is not None:
        results["astar_haversine"] = astar(g, s, t, weight, haversine_heuristic(g, t, kind_weight_heuristic.per_metre))
    return results


def small_graph():
    g = AdjacencyGraph([10, 20, 30, 40, 50, 60], [24.86 + 0.001 * i for i in range(6)], [67.03] * 6)
    for a, b, w in [(0, 1, 7), (0, 2, 9), (0, 5, 14), (1, 2, 10), (1, 3, 15), (2, 3, 11), (2, 5, 2), (3, 4, 6), (5, 4, 9)]:
        g.add_edge(a, b, float(w), float(w))
        g.add_edge(b, a, float(w), float(w))
    return g


def test_known_answer_on_textbook_graph():
    g = small_graph()
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 0, 4, w).items():
        assert res.cost == 20.0, name
        check_path(g, res, w, 0, 4)


def test_source_equals_target():
    g = small_graph()
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 3, 3, w).items():
        assert res.found and res.cost == 0.0 and res.nodes == [3] and res.edges == [], name


def test_unreachable_target():
    g = AdjacencyGraph([1, 2, 3], [24.0, 24.001, 24.002], [67.0] * 3)
    g.add_edge(0, 1, 5.0, 5.0)
    g.add_edge(2, 1, 5.0, 5.0)
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 0, 2, w).items():
        assert not res.found and res.cost == INF and res.nodes == [], name


def test_one_way_edges_are_respected():
    g = AdjacencyGraph([1, 2, 3], [24.0, 24.001, 24.002], [67.0] * 3)
    g.add_edge(0, 1, 1.0, 1.0)
    g.add_edge(1, 2, 1.0, 1.0)
    g.add_edge(2, 0, 100.0, 100.0)
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 2, 1, w).items():
        assert res.cost == 101.0, name
    for name, res in all_searches(g, 0, 2, w).items():
        assert res.cost == 2.0, name


def test_zero_weight_edges():
    g = AdjacencyGraph([1, 2, 3, 4], [24.0, 24.001, 24.002, 24.003], [67.0] * 4)
    g.add_edge(0, 1, 0.0, 0.0)
    g.add_edge(1, 2, 0.0, 0.0)
    g.add_edge(2, 3, 4.0, 4.0)
    g.add_edge(0, 3, 5.0, 5.0)
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 0, 3, w).items():
        assert res.cost == 4.0, name
        check_path(g, res, w, 0, 3)


def test_parallel_edges_take_the_cheapest():
    g = AdjacencyGraph([1, 2, 3], [24.0, 24.001, 24.002], [67.0] * 3)
    g.add_edge(0, 1, 9.0, 9.0)
    cheap = g.add_edge(0, 1, 2.0, 2.0)
    g.add_edge(0, 1, 5.0, 5.0)
    g.add_edge(1, 2, 1.0, 1.0)
    w = edge_weight(g, "length")
    for name, res in all_searches(g, 0, 2, w).items():
        assert res.cost == 3.0, name
        assert res.edges[0] == cheap, name


def test_counters_and_record():
    g = synthetic_city(8, 8)
    w = edge_weight(g, "time")
    res = dijkstra(g, 0, g.n - 1, w, record=True)
    assert res.settled == len(res.explored) and res.settled > 0
    assert res.relaxed >= res.settled - 1
    bi = bidirectional_dijkstra(g, 0, g.n - 1, w, record=True)
    assert bi.settled == len(bi.explored) + len(bi.explored_backward)


def test_full_search_without_target_settles_reachable_nodes():
    g = synthetic_city(6, 6)
    w = edge_weight(g, "length")
    res = dijkstra(g, 0, None, w)
    assert not res.found and res.settled == g.n
    ref = nx.single_source_dijkstra_path_length(to_networkx(g), 0)
    for node, dist in ref.items():
        assert close(res.dist[node], dist)


def test_bidirectional_rejects_time_dependent_weight():
    g = small_graph()
    w = make_weight(lambda eid, d: 1.0, "td", time_dependent=True)
    with pytest.raises(ValueError):
        bidirectional_dijkstra(g, 0, 4, w)


@pytest.mark.parametrize("seed", range(300))
def test_matches_networkx_on_random_directed_graphs(seed):
    rng = random.Random(seed)
    g = random_geo_graph(seed, n=rng.randint(5, 40), extra_edges=rng.randint(0, 90), zero_weight=seed % 5 == 0)
    ref = to_networkx(g, "length")
    w = edge_weight(g, "length")
    for _ in range(4):
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        try:
            expected = nx.dijkstra_path_length(ref, s, t, weight="weight")
        except nx.NetworkXNoPath:
            expected = INF
        for name, res in all_searches(g, s, t, w).items():
            assert close(res.cost, expected, rel=1e-9, abs_=1e-9), (name, s, t)
            if expected < INF:
                check_path(g, res, w, s, t)
            else:
                assert not res.found


@pytest.mark.parametrize("seed", range(60))
def test_astar_with_admissible_heuristic_matches_networkx(seed):
    rng = random.Random(1000 + seed)
    g = random_geo_graph(seed, n=rng.randint(10, 40), extra_edges=rng.randint(10, 90))
    for kind, weight in (("length", distance_weight(g)), ("time", free_flow_weight(g))):
        ref = to_networkx(g, kind)
        for _ in range(4):
            s, t = rng.randrange(g.n), rng.randrange(g.n)
            try:
                expected = nx.dijkstra_path_length(ref, s, t, weight="weight")
            except nx.NetworkXNoPath:
                expected = INF
            res = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
            assert close(res.cost, expected, rel=1e-9, abs_=1e-9), (kind, s, t)


def test_astar_combined_weight_matches_dijkstra():
    g = synthetic_city(10, 10)
    weight = combined_weight(g, 1.0, 0.2)
    rng = random.Random(4)
    for _ in range(40):
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        a = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
        d = dijkstra(g, s, t, weight)
        assert close(a.cost, d.cost)


def test_astar_settles_fewer_nodes_than_dijkstra():
    g = synthetic_city(20, 20)
    weight = distance_weight(g)
    rng = random.Random(9)
    astar_total = 0
    dijkstra_total = 0
    for _ in range(40):
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        a = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
        d = dijkstra(g, s, t, weight)
        assert close(a.cost, d.cost)
        astar_total += a.settled
        dijkstra_total += d.settled
    assert astar_total < dijkstra_total


def test_astar_equals_dijkstra_on_synthetic_city_for_200_pairs():
    g = synthetic_city(14, 14, seed=7)
    rng = random.Random(11)
    for weight in (distance_weight(g), free_flow_weight(g)):
        for _ in range(200):
            s, t = rng.randrange(g.n), rng.randrange(g.n)
            a = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
            d = dijkstra(g, s, t, weight)
            assert close(a.cost, d.cost, rel=1e-9, abs_=1e-6), (s, t)


def build_inadmissible_example():
    lat = [24.860, 24.897, 24.860]
    lon = [67.000, 67.025, 67.050]
    g = AdjacencyGraph([1, 2, 3], lat, lon)
    direct = haversine_m(lat[0], lon[0], lat[2], lon[2]) * 1.01
    leg1 = haversine_m(lat[0], lon[0], lat[1], lon[1]) * 1.01
    leg2 = haversine_m(lat[1], lon[1], lat[2], lon[2]) * 1.01
    g.add_edge(0, 2, direct, direct / (10 / 3.6))
    g.add_edge(0, 1, leg1, leg1 / (100 / 3.6))
    g.add_edge(1, 2, leg2, leg2 / (100 / 3.6))
    return g


def test_inadmissible_heuristic_can_return_a_worse_path():
    g = build_inadmissible_example()
    weight = free_flow_weight(g)
    optimal = dijkstra(g, 0, 2, weight)
    admissible = astar(g, 0, 2, weight, haversine_heuristic(g, 2, weight.per_metre))
    slow_speed = 10 / 3.6
    inadmissible = astar(g, 0, 2, weight, haversine_heuristic(g, 2, 1.0 / slow_speed))
    direct_time = g.weight_list("time")[0]
    assert optimal.edges == [1, 2]
    assert close(admissible.cost, optimal.cost)
    assert inadmissible.edges == [0]
    assert inadmissible.cost == pytest.approx(direct_time)
    assert inadmissible.cost > 3 * optimal.cost


def test_inadmissible_heuristic_is_suboptimal_on_a_city_grid():
    g = synthetic_city(14, 14, seed=3)
    weight = free_flow_weight(g)
    slow = haversine_heuristic
    rng = random.Random(5)
    worse = 0
    for _ in range(150):
        s, t = rng.randrange(g.n), rng.randrange(g.n)
        optimal = dijkstra(g, s, t, weight).cost
        biased = astar(g, s, t, weight, slow(g, t, 6.0 / g.max_speed_mps())).cost
        assert biased >= optimal - 1e-9
        worse += biased > optimal + 1e-6
    assert worse > 0


def naive_first_meeting(g, s, t, weight):
    dist = [{s: 0.0}, {t: 0.0}]
    frontier = [[(0.0, s)], [(0.0, t)]]
    edges = [g.out_edges, g.in_edges]
    side = 0
    while frontier[0] or frontier[1]:
        if not frontier[side]:
            side = 1 - side
            continue
        frontier[side].sort()
        d, u = frontier[side].pop(0)
        if d > dist[side][u]:
            continue
        for eid, v in edges[side](u):
            nd = d + weight(eid, d)
            if nd < dist[side].get(v, INF):
                dist[side][v] = nd
                frontier[side].append((nd, v))
            if v in dist[1 - side]:
                return dist[side][v] + dist[1 - side][v]
        side = 1 - side
    return INF


def test_stopping_at_the_first_meeting_node_is_wrong():
    g = AdjacencyGraph([1, 2, 3, 4, 5], [24.0 + 0.001 * i for i in range(5)], [67.0] * 5)
    S, M, P, Q, T = range(5)
    g.add_edge(S, M, 5.0, 5.0)
    g.add_edge(M, T, 5.0, 5.0)
    g.add_edge(S, P, 1.0, 1.0)
    g.add_edge(P, Q, 1.0, 1.0)
    g.add_edge(Q, T, 1.0, 1.0)
    w = edge_weight(g, "length")
    assert naive_first_meeting(g, S, T, w) == 10.0
    assert bidirectional_dijkstra(g, S, T, w).cost == 3.0
    assert dijkstra(g, S, T, w).cost == 3.0


@pytest.mark.real_graph
def test_astar_equals_dijkstra_on_real_graph_for_200_pairs():
    from src import config
    from src.graph import CSRGraph

    path = config.graph_path()
    if not path.exists():
        pytest.skip("real graph not built; run python -m scripts.build_graph")
    g = CSRGraph.load(path)
    rng = random.Random(2024)
    for weight in (distance_weight(g), free_flow_weight(g)):
        for _ in range(200):
            s, t = rng.randrange(g.n), rng.randrange(g.n)
            a = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
            d = dijkstra(g, s, t, weight)
            assert close(a.cost, d.cost, rel=1e-9, abs_=1e-6), (s, t)


@pytest.mark.parametrize("seed", range(10))
def test_csr_and_adjacency_representations_give_identical_costs(seed):
    rng = random.Random(seed)
    adjacency = random_geo_graph(seed, n=30, extra_edges=80)
    csr = adjacency.to_csr()
    for kind in ("length", "time"):
        wa = edge_weight(adjacency, kind)
        wc = edge_weight(csr, kind)
        for _ in range(6):
            s, t = rng.randrange(adjacency.n), rng.randrange(adjacency.n)
            expected = dijkstra(adjacency, s, t, wa).cost
            assert close(dijkstra(csr, s, t, wc).cost, expected)
            assert close(bidirectional_dijkstra(csr, s, t, wc).cost, expected)
            assert close(astar(csr, s, t, wc, lambda u: 0.0).cost, expected)

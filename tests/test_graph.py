import networkx as nx
import numpy as np
import pytest

from src.graph import AdjacencyGraph, CSRGraph, haversine_m
from src.scc import largest_scc_mask, strongly_connected_components
from tests.helpers import random_geo_graph, synthetic_city


def edge_multiset(g):
    out = []
    for u in range(g.n):
        for eid, v in g.out_edges(u):
            out.append((u, v, round(g.weight_list("length")[eid], 6), round(g.weight_list("time")[eid], 6)))
    return sorted(out)


def test_haversine_known_distance():
    assert haversine_m(24.86, 67.03, 24.86, 67.03) == 0.0
    one_degree = haversine_m(0.0, 0.0, 1.0, 0.0)
    assert one_degree == pytest.approx(111194.9, rel=1e-4)


def test_adjacency_and_csr_expose_same_graph():
    g = random_geo_graph(3, n=25, extra_edges=50)
    csr = g.to_csr()
    assert (csr.n, csr.m) == (g.n, g.m)
    assert edge_multiset(csr) == edge_multiset(g)
    back = csr.to_adjacency()
    assert edge_multiset(back) == edge_multiset(g)


def test_in_edges_mirror_out_edges():
    csr = random_geo_graph(4, n=25, extra_edges=60).to_csr()
    forward = {(u, v, eid) for u in range(csr.n) for eid, v in csr.out_edges(u)}
    backward = {(u, v, eid) for v in range(csr.n) for eid, u in csr.in_edges(v)}
    assert forward == backward


def test_csr_edge_source_matches_out_edges():
    csr = random_geo_graph(5, n=20, extra_edges=40).to_csr()
    for u in range(csr.n):
        for eid, _ in csr.out_edges(u):
            assert csr.edge_source(eid) == u


def test_csr_save_and_load_roundtrip(tmp_path):
    g = synthetic_city(6, 6).to_csr()
    g.meta = {"nodes": g.n, "note": "roundtrip"}
    path = tmp_path / "g.npz"
    g.save(path)
    loaded = CSRGraph.load(path)
    assert loaded.meta == g.meta
    for name in CSRGraph.ARRAYS:
        assert np.array_equal(getattr(loaded, name), getattr(g, name))


def test_geometry_and_names_survive_conversion():
    g = AdjacencyGraph([1, 2], [24.0, 24.001], [67.0, 67.0])
    g.add_edge(0, 1, 120.0, 10.0, "primary", "Main Road", True, [(24.0004, 67.0002), (24.0007, 67.0001)])
    csr = g.to_csr()
    assert csr.edge_name(0) == "Main Road"
    assert csr.edge_imputed(0) is True
    poly = csr.edge_polyline(0)
    assert len(poly) == 4
    assert poly[1][0] == pytest.approx(24.0004, abs=1e-5)
    assert csr.edge_class_name(0) == "primary"


def test_max_speed_is_at_least_every_edge_speed():
    g = synthetic_city(8, 8)
    vmax = g.max_speed_mps()
    for length, time in zip(g.weight_list("length"), g.weight_list("time")):
        assert length / time <= vmax


def test_subgraph_keeps_only_selected_nodes():
    csr = synthetic_city(8, 8).to_csr()
    keep = np.zeros(csr.n, dtype=bool)
    keep[:20] = True
    sub = csr.subgraph(keep)
    assert sub.n == 20
    for u in range(sub.n):
        for _, v in sub.out_edges(u):
            assert v < sub.n
    original = {(u, v) for u in range(20) for _, v in csr.out_edges(u) if v < 20}
    assert {(u, v) for u in range(sub.n) for _, v in sub.out_edges(u)} == original


@pytest.mark.parametrize("seed", range(20))
def test_scc_matches_networkx(seed):
    g = random_geo_graph(seed, n=40, extra_edges=25, parallel=False)
    csr = g.to_csr()
    comp = strongly_connected_components(csr.offsets.tolist(), csr.targets.tolist())
    nx_graph = nx.DiGraph((u, v) for u in range(csr.n) for _, v in csr.out_edges(u))
    nx_graph.add_nodes_from(range(csr.n))
    expected = {frozenset(c) for c in nx.strongly_connected_components(nx_graph)}
    groups = {}
    for node, c in enumerate(comp):
        groups.setdefault(c, set()).add(node)
    assert {frozenset(v) for v in groups.values()} == expected


def test_largest_scc_mask_drops_dead_ends():
    g = AdjacencyGraph([1, 2, 3, 4], [24.0, 24.001, 24.002, 24.003], [67.0] * 4)
    for a, b in [(0, 1), (1, 0), (1, 2), (2, 3)]:
        g.add_edge(a, b, 100.0, 10.0)
    mask = largest_scc_mask(g.to_csr())
    assert mask.tolist() == [True, True, False, False]

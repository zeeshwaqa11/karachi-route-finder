import networkx as nx
import pytest

from src import config
from src.osm_convert import convert_osmnx_graph, parse_maxspeed, road_class_of, road_name_of


class FakeLine:
    def __init__(self, coords):
        self.coords = coords


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("50", 50.0),
        ("30 mph", pytest.approx(48.28, abs=0.01)),
        ("['40', '60']", 40.0),
        (["80", "signals"], 80.0),
        ("none", None),
        ("walk", None),
        (None, None),
        ("2", None),
        ("500", None),
    ],
)
def test_parse_maxspeed(raw, expected):
    assert parse_maxspeed(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("primary_link", "primary"),
        ("unclassified", "tertiary"),
        (["residential", "secondary"], "secondary"),
        ("['service', 'residential']", "residential"),
        ("track", config.FALLBACK_CLASS),
        (None, config.FALLBACK_CLASS),
    ],
)
def test_road_class_of(raw, expected):
    assert road_class_of(raw) == expected


def test_road_name_of_joins_distinct_names():
    assert road_name_of(["A Road", "A Road", "B Road"]) == "A Road / B Road"
    assert road_name_of(None) == ""


def make_osm_graph():
    G = nx.MultiDiGraph()
    coords = {1: (24.860, 67.030), 2: (24.861, 67.031), 3: (24.862, 67.032), 4: (24.870, 67.040), 5: (24.850, 67.020)}
    for nid, (lat, lon) in coords.items():
        G.add_node(nid, y=lat, x=lon)
    G.add_edge(1, 2, length=200.0, highway="primary", maxspeed="60", name="Main Road")
    G.add_edge(2, 1, length=200.0, highway="primary", maxspeed="60", name="Main Road")
    G.add_edge(2, 3, length=180.0, highway="residential")
    G.add_edge(3, 2, length=180.0, highway="residential")
    G.add_edge(3, 3, length=10.0, highway="residential")
    G.add_edge(1, 3, length=900.0, highway="tertiary", maxspeed="20")
    G.add_edge(1, 3, length=400.0, highway="service")
    G.add_edge(
        3,
        1,
        length=350.0,
        highway="residential",
        geometry=FakeLine([(67.032, 24.862), (67.0311, 24.8612), (67.0305, 24.8606), (67.030, 24.860)]),
    )
    G.add_edge(3, 4, length=1500.0, highway="primary")
    G.add_edge(5, 1, length=1500.0, highway="primary")
    return G


def test_conversion_keeps_largest_scc_and_reports_drops():
    graph, report = convert_osmnx_graph(make_osm_graph())
    assert graph.n == 3
    assert report["osm_nodes_downloaded"] == 5
    assert report["nodes_dropped_by_scc"] == 2
    assert report["edges_dropped_by_scc"] == 2
    assert report["self_loops_dropped"] == 1


def test_parallel_edges_keep_lowest_cost_per_weight_type():
    graph, report = convert_osmnx_graph(make_osm_graph())
    assert report["parallel_edges_merged"] == 1
    node_index = {int(nid): i for i, nid in enumerate(graph.node_ids.tolist())}
    u, v = node_index[1], node_index[3]
    edges = [(eid, t) for eid, t in graph.out_edges(u) if t == v]
    assert len(edges) == 1
    eid = edges[0][0]
    assert graph.length[eid] == pytest.approx(400.0)
    slow_time = 900.0 / (20 / 3.6)
    service_time = 400.0 / (config.DEFAULT_SPEEDS_KMH["service"] / 3.6)
    assert graph.time[eid] == pytest.approx(min(slow_time, service_time))


def test_missing_speeds_are_imputed_from_road_class_and_flagged():
    graph, report = convert_osmnx_graph(make_osm_graph())
    node_index = {int(nid): i for i, nid in enumerate(graph.node_ids.tolist())}
    u, v = node_index[1], node_index[2]
    eid = next(e for e, t in graph.out_edges(u) if t == v)
    assert not graph.imputed[eid]
    assert graph.time[eid] == pytest.approx(200.0 / (60 / 3.6))
    u, v = node_index[2], node_index[3]
    eid = next(e for e, t in graph.out_edges(u) if t == v)
    assert graph.imputed[eid]
    assert graph.time[eid] == pytest.approx(graph.length[eid] / (config.DEFAULT_SPEEDS_KMH["residential"] / 3.6))
    assert report["edges_with_imputed_speed"] == int(graph.imputed.sum())


def test_edge_length_never_below_straight_line_distance():
    G = make_osm_graph()
    G.add_edge(1, 2, length=1.0, highway="primary")
    graph, _ = convert_osmnx_graph(G)
    from src.graph import haversine_m

    for u in range(graph.n):
        for eid, v in graph.out_edges(u):
            straight = haversine_m(graph.lat[u], graph.lon[u], graph.lat[v], graph.lon[v])
            assert graph.length[eid] >= straight - 1e-9


def test_geometry_interior_points_are_kept():
    graph, _ = convert_osmnx_graph(make_osm_graph())
    node_index = {int(nid): i for i, nid in enumerate(graph.node_ids.tolist())}
    u, v = node_index[3], node_index[1]
    eid = next(e for e, t in graph.out_edges(u) if t == v)
    geometry = graph.edge_geometry(eid)
    assert len(geometry) == 2
    assert geometry[0] == pytest.approx((24.8612, 67.0311), abs=1e-5)

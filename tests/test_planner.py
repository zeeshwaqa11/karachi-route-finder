import pytest

from src import config
from src.congestion import CongestionModel
from src.planner import RouteRequest, plan_routes
from tests.helpers import synthetic_city


@pytest.fixture(scope="module")
def setup():
    g = synthetic_city(14, 14, seed=8)
    return g.to_csr(), None


@pytest.fixture(scope="module")
def city_and_model(setup):
    graph = setup[0]
    return graph, CongestionModel(graph)


def request(**kwargs):
    base = dict(source=3, target=150, day="Monday", depart_s=8.5 * 3600, k=3, algorithm="astar")
    base.update(kwargs)
    return RouteRequest(**base)


def test_plan_returns_ranked_diverse_routes(city_and_model):
    graph, model = city_and_model
    response = plan_routes(graph, model, request())
    assert 1 <= len(response.routes) <= 3
    assert [r.rank for r in response.routes] == list(range(1, len(response.routes) + 1))
    assert response.settled > 0 and response.compute_ms > 0
    assert all(r.metrics.travel_s > 0 and r.metrics.distance_m > 0 for r in response.routes)
    scores = [r.score for r in response.routes]
    assert scores == sorted(scores)


def test_dijkstra_and_astar_agree_on_the_fastest_route(city_and_model):
    graph, model = city_and_model
    a = plan_routes(graph, model, request(algorithm="astar", weights={"time": 1, "distance": 0, "congestion": 0}))
    d = plan_routes(graph, model, request(algorithm="dijkstra", weights={"time": 1, "distance": 0, "congestion": 0}))
    assert a.routes[0].metrics.travel_s == pytest.approx(d.routes[0].metrics.travel_s)
    assert a.settled <= d.settled


def test_peak_departure_is_slower_than_night(city_and_model):
    graph, model = city_and_model
    peak = plan_routes(graph, model, request(depart_s=9 * 3600, k=1))
    night = plan_routes(graph, model, request(depart_s=3 * 3600, k=1))
    assert peak.routes[0].metrics.travel_s > night.routes[0].metrics.travel_s
    assert peak.routes[0].metrics.avg_multiplier > night.routes[0].metrics.avg_multiplier


def test_weekend_is_calmer_than_weekday(city_and_model):
    graph, model = city_and_model
    weekday = plan_routes(graph, model, request(day="Tuesday", depart_s=9 * 3600, k=1))
    weekend = plan_routes(graph, model, request(day="Sunday", depart_s=9 * 3600, k=1))
    assert weekend.routes[0].metrics.travel_s < weekday.routes[0].metrics.travel_s


def test_k_one_returns_single_route_and_found_all_flag(city_and_model):
    graph, model = city_and_model
    response = plan_routes(graph, model, request(k=1))
    assert len(response.routes) == 1 and response.found_all


def test_same_origin_and_destination(city_and_model):
    graph, model = city_and_model
    response = plan_routes(graph, model, request(source=5, target=5))
    assert len(response.routes) == 1
    assert response.routes[0].metrics.distance_m == 0.0


def test_defaults_come_from_config():
    r = RouteRequest(source=0, target=1)
    assert r.weights == config.DEFAULT_ROUTE_WEIGHTS
    assert r.diversity_threshold == config.DIVERSITY_THRESHOLD


@pytest.mark.real_graph
def test_every_builtin_place_snaps_within_the_warning_distance():
    from src.graph import CSRGraph
    from src.places import PLACES
    from src.spatial import KDTree, snap_point

    path = config.graph_path()
    if not path.exists():
        pytest.skip("real graph not built; run python -m scripts.build_graph")
    graph = CSRGraph.load(path)
    tree = KDTree(graph.lat, graph.lon)
    for place in PLACES:
        snap = snap_point(tree, place.lat, place.lon)
        assert not snap.far, (place.name, snap.distance_m)

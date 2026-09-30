import pytest

from src.congestion import RouteMetrics
from src.ranking import combined_costs, normalise_weights, rank_routes
from src.routing.yen import RoutePath


def candidate(name, time_s, dist_m, mult):
    path = RoutePath(time_s, [0, 1], [abs(hash(name)) % 1000])
    return path, RouteMetrics(dist_m, time_s / mult, time_s, mult, "Low")


def test_weights_are_normalised_and_zero_falls_back_to_equal():
    w = normalise_weights({"time": 2, "distance": 1, "congestion": 1})
    assert w == {"time": 0.5, "distance": 0.25, "congestion": 0.25}
    assert normalise_weights({"time": 0, "distance": 0, "congestion": 0}) == pytest.approx(
        {"time": 1 / 3, "distance": 1 / 3, "congestion": 1 / 3}
    )


def test_combined_cost_uses_ratio_to_best():
    a = candidate("a", 600, 5000, 1.2)[1]
    b = candidate("b", 900, 4000, 1.5)[1]
    costs = combined_costs([a, b], {"time": 1, "distance": 0, "congestion": 0})
    assert costs == pytest.approx([1.0, 1.5])
    costs = combined_costs([a, b], {"time": 0, "distance": 1, "congestion": 0})
    assert costs == pytest.approx([1.25, 1.0])


def test_ranking_changes_with_weights():
    fast_long = candidate("fast", 600, 9000, 1.6)
    slow_short = candidate("short", 800, 6000, 1.6)
    calm = candidate("calm", 700, 8000, 1.1)
    by_time = rank_routes([fast_long, slow_short, calm], {"time": 1, "distance": 0, "congestion": 0})
    assert by_time[0].path is fast_long[0]
    by_distance = rank_routes([fast_long, slow_short, calm], {"time": 0, "distance": 1, "congestion": 0})
    assert by_distance[0].path is slow_short[0]
    by_congestion = rank_routes([fast_long, slow_short, calm], {"time": 0, "distance": 0, "congestion": 1})
    assert by_congestion[0].path is calm[0]
    assert [r.rank for r in by_time] == [1, 2, 3]


def test_labels_mark_the_best_route_per_measure():
    fast_long = candidate("fast", 600, 9000, 1.6)
    slow_short = candidate("short", 800, 6000, 1.6)
    calm = candidate("calm", 700, 8000, 1.1)
    ranked = rank_routes([fast_long, slow_short, calm])
    labels = {id(r.path): r.labels for r in ranked}
    assert labels[id(fast_long[0])] == ["Fastest"]
    assert labels[id(slow_short[0])] == ["Shortest"]
    assert labels[id(calm[0])] == ["Least congested"]


def test_one_route_can_hold_every_label_and_single_route_ranks_first():
    only = candidate("only", 600, 5000, 1.2)
    ranked = rank_routes([only])
    assert ranked[0].rank == 1
    assert ranked[0].labels == ["Fastest", "Shortest", "Least congested"]
    assert rank_routes([]) == []


def test_display_helpers():
    r = rank_routes([candidate("x", 600, 5000, 1.2)])[0]
    assert r.distance_km == pytest.approx(5.0)
    assert r.time_min == pytest.approx(10.0)
    assert "Fastest" in r.label_text

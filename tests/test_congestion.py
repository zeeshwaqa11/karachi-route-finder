import itertools
import random

import networkx as nx
import pytest

from src import config
from src.congestion import (
    DAY_SECONDS,
    SLOT_SECONDS,
    CongestionModel,
    build_slot_table,
    congestion_level,
    day_type_of,
    interpolate_anchors,
    normalise_name,
)
from src.graph import AdjacencyGraph
from src.routing.astar import astar
from src.routing.dijkstra import dijkstra
from src.routing.weights import haversine_heuristic
from src.routing.yen import path_prefix_costs, yen_k_shortest
from tests.helpers import close, random_geo_graph, synthetic_city


@pytest.fixture(scope="module")
def city():
    return synthetic_city(12, 12, seed=5)


@pytest.fixture(scope="module")
def model(city):
    return CongestionModel(city)


def hours(h, m=0):
    return (h * 60 + m) * 60.0


def test_slot_table_has_wraparound_entry_and_bounds():
    table = build_slot_table(config.WEEKDAY_ANCHORS_HOURS, 1.0)
    assert len(table) == config.SLOTS_PER_DAY + 1
    assert table[-1] == table[0]
    assert min(table) >= 1.0


def test_weekday_peaks_where_expected(model):
    table = model.profile_curve("weekday", "primary")
    slot = lambda h: int(h * 60 // config.SLOT_MINUTES)  # noqa: E731
    morning = max(table[slot(8) : slot(10) + 1])
    evening = max(table[slot(17) : slot(20) + 1])
    night = table[slot(3)]
    midday = table[slot(12)]
    assert morning > midday > night
    assert evening > midday
    weekend = model.profile_curve("weekend", "primary")
    assert weekend[slot(9)] < table[slot(9)]


def test_class_sensitivity_orders_congestion(model):
    slot = int(9 * 60 // config.SLOT_MINUTES)
    values = [model.profile_curve("weekday", c)[slot] for c in ("primary", "residential", "service")]
    assert values[0] > values[1] > values[2] >= 1.0


def test_interpolate_anchors():
    anchors = [(0.0, 1.0), (2.0, 3.0), (4.0, 3.0)]
    assert interpolate_anchors(anchors, 1.0) == 2.0
    assert interpolate_anchors(anchors, 3.0) == 3.0
    assert interpolate_anchors(anchors, 9.0) == 3.0


def test_multiplier_is_piecewise_linear_between_slot_starts(city, model):
    eid = 0
    cls_table = model.tables["weekday"][model._cls[eid]]
    corr = model.corridor_factor[eid]
    k = 34
    start = k * SLOT_SECONDS
    assert model.multiplier(eid, "weekday", start) == pytest.approx(corr * cls_table[k])
    mid = model.multiplier(eid, "weekday", start + SLOT_SECONDS / 2)
    assert mid == pytest.approx(corr * (cls_table[k] + cls_table[k + 1]) / 2)
    assert model.multiplier(eid, "weekday", DAY_SECONDS - 1e-6) == pytest.approx(corr * cls_table[0], rel=1e-3)


def test_multipliers_never_below_one(city, model):
    rng = random.Random(1)
    for _ in range(2000):
        eid = rng.randrange(city.m)
        day = rng.choice(["weekday", "weekend"])
        assert model.multiplier(eid, day, rng.uniform(0, 2 * DAY_SECONDS)) >= 1.0 - 1e-12


def test_weight_matches_multiplier_times_free_flow(city, model):
    weight = model.weight("weekday", hours(8, 30))
    base = city.weight_list("time")
    rng = random.Random(2)
    for _ in range(300):
        eid = rng.randrange(city.m)
        elapsed = rng.uniform(0, 3000)
        expected = base[eid] * model.multiplier(eid, "weekday", hours(8, 30) + elapsed)
        assert weight(eid, elapsed) == pytest.approx(expected)
    assert weight.time_dependent is True


def test_fifo_holds_for_every_edge_and_day_type(city, model):
    rng = random.Random(3)
    step = 60.0
    for day in ("weekday", "weekend"):
        for eid in rng.sample(range(city.m), 60):
            previous = None
            clock = 0.0
            while clock < 2 * DAY_SECONDS:
                arrival = clock + model.edge_travel_time(eid, day, clock)
                if previous is not None:
                    assert arrival >= previous - 1e-9
                previous = arrival
                clock += step
    assert model.fifo_ratio["weekday"] <= 1.0


def test_fifo_holds_for_random_pairs_of_departures(city, model):
    rng = random.Random(4)
    for _ in range(5000):
        eid = rng.randrange(city.m)
        t1 = rng.uniform(0, DAY_SECONDS)
        t2 = t1 + rng.uniform(0, 4000)
        day = rng.choice(["weekday", "weekend"])
        a1 = t1 + model.edge_travel_time(eid, day, t1)
        a2 = t2 + model.edge_travel_time(eid, day, t2)
        assert a1 <= a2 + 1e-9


def test_profile_that_breaks_fifo_is_rejected():
    g = AdjacencyGraph([1, 2], [24.86, 24.87], [67.03, 67.03])
    g.add_edge(0, 1, 10000.0, 1200.0, "primary", "Long Road")
    g.add_edge(1, 0, 10000.0, 1200.0, "primary", "Long Road")
    steep = [(0.0, 1.0), (8.0, 6.0), (8.25, 1.0), (24.0, 1.0)]
    with pytest.raises(ValueError, match="FIFO"):
        CongestionModel(g, weekday_anchors=steep)
    gentle = [(0.0, 1.0), (8.0, 1.5), (9.0, 1.0), (24.0, 1.0)]
    assert CongestionModel(g, weekday_anchors=gentle).fifo_ratio["weekday"] <= 1.0


def test_multipliers_below_one_are_rejected(city):
    with pytest.raises(ValueError):
        CongestionModel(city, weekday_anchors=[(0.0, 0.8), (24.0, 0.8)])


def test_costs_change_with_departure_time(city, model):
    s, t = 0, city.n - 1
    costs = {}
    for label, depart in (("night", hours(3)), ("peak", hours(9)), ("midday", hours(12, 30))):
        weight = model.weight("weekday", depart)
        costs[label] = dijkstra(city, s, t, weight).cost
    assert costs["peak"] > costs["midday"] > costs["night"]
    static = sum(city.weight_list("time")[e] for e in dijkstra(city, s, t, model.weight("weekday", hours(3))).edges)
    assert costs["night"] >= static - 1e-9


def test_later_departure_never_arrives_earlier(city, model):
    rng = random.Random(6)
    for _ in range(25):
        s, t = rng.randrange(city.n), rng.randrange(city.n)
        arrivals = []
        for depart in range(0, int(DAY_SECONDS), 1800):
            cost = dijkstra(city, s, t, model.weight("weekday", float(depart))).cost
            arrivals.append(depart + cost)
        assert all(b >= a - 1e-6 for a, b in zip(arrivals, arrivals[1:]))


def label_correcting_oracle(g, s, weight):
    best = {s: 0.0}
    changed = True
    while changed:
        changed = False
        for u in list(best):
            for eid, v in g.out_edges(u):
                nd = best[u] + weight(eid, best[u])
                if nd < best.get(v, float("inf")) - 1e-12:
                    best[v] = nd
                    changed = True
    return best


@pytest.mark.parametrize("seed", range(15))
def test_time_dependent_search_matches_label_correcting_oracle(seed):
    g = random_geo_graph(seed, n=14, extra_edges=30)
    model = CongestionModel(g)
    rng = random.Random(seed)
    depart = rng.uniform(0, DAY_SECONDS)
    weight = model.weight("weekday", depart)
    s = rng.randrange(g.n)
    oracle = label_correcting_oracle(g, s, weight)
    for t in range(g.n):
        d = dijkstra(g, s, t, weight)
        a = astar(g, s, t, weight, haversine_heuristic(g, t, weight.per_metre))
        expected = oracle.get(t, float("inf"))
        assert close(d.cost, expected, rel=1e-9, abs_=1e-6)
        assert close(a.cost, expected, rel=1e-9, abs_=1e-6)


def test_yen_under_time_dependent_costs_matches_brute_force():
    g = random_geo_graph(11, n=9, extra_edges=18, parallel=False)
    model = CongestionModel(g)
    weight = model.weight("weekday", hours(8, 40))
    G = nx.DiGraph()
    edge_of = {}
    for u in range(g.n):
        for eid, v in g.out_edges(u):
            G.add_edge(u, v)
            edge_of[(u, v)] = eid
    for s, t in itertools.islice(itertools.permutations(range(g.n), 2), 0, 40, 3):
        costs = sorted(
            path_prefix_costs(weight, [edge_of[(a, b)] for a, b in zip(p, p[1:])])[-1] for p in nx.all_simple_paths(G, s, t)
        )
        got = yen_k_shortest(g, s, t, weight, 5, algorithm="astar")
        assert len(got.paths) == min(5, len(costs))
        for a, b in zip([p.cost for p in got.paths], costs):
            assert close(a, b, rel=1e-9, abs_=1e-6)


def test_normalise_name_handles_punctuation_case_and_urdu():
    assert normalise_name("M.A. Jinnah Road") == normalise_name("m a jinnah road")
    assert normalise_name("Shahrah-e-Faisal") == normalise_name("Shahrah e Faisal")
    assert normalise_name("یونیورسٹی روڈ") == "یونیورسٹیروڈ"


def test_corridor_matching_by_name(city):
    g = AdjacencyGraph([1, 2, 3, 4, 5], [24.86 + 0.001 * i for i in range(5)], [67.03] * 5)
    names = ["Shahrah e Faisal", "New M A Jinnah Road", "یونیورسٹی روڈ", "Fatima Jinnah Road", "Quaid Street"]
    for i, name in enumerate(names):
        g.add_edge(i, (i + 1) % 5, 100.0, 10.0, "primary", name)
    model = CongestionModel(g)
    spec = config.CORRIDOR_MULTIPLIERS
    assert model.corridor_factor[0] == spec["Shahrah-e-Faisal"]["multiplier"]
    assert model.corridor_factor[1] == spec["M.A. Jinnah Road"]["multiplier"]
    assert model.corridor_factor[2] == spec["University Road"]["multiplier"]
    assert model.corridor_factor[3] == 1.0
    assert model.corridor_factor[4] == 1.0
    assert model.corridor_edges["Shahrah-e-Faisal"] == 1


def test_corridor_slows_matching_edges(city, model):
    named = [e for e in range(city.m) if model.corridor_factor[e] > 1.0]
    assert named
    other = next(e for e in range(city.m) if model.corridor_factor[e] == 1.0 and model._cls[e] == model._cls[named[0]])
    clock = hours(9)
    assert model.multiplier(named[0], "weekday", clock) > model.multiplier(other, "weekday", clock)


def test_route_metrics_length_weighted_average():
    g = AdjacencyGraph([1, 2, 3], [24.86, 24.87, 24.88], [67.03] * 3)
    g.add_edge(0, 1, 1000.0, 100.0, "primary", "A")
    g.add_edge(1, 2, 3000.0, 300.0, "primary", "B")
    model = CongestionModel(g, corridors={})
    peak = hours(9)
    metrics = model.route_metrics([0, 1], "weekday", peak)
    m1 = model.multiplier(0, "weekday", peak)
    m2 = model.multiplier(1, "weekday", peak + 100.0 * m1)
    assert metrics.distance_m == 4000.0
    assert metrics.free_flow_s == 400.0
    assert metrics.travel_s == pytest.approx(100.0 * m1 + 300.0 * m2)
    assert metrics.avg_multiplier == pytest.approx((1000 * m1 + 3000 * m2) / 4000)
    night = model.route_metrics([0, 1], "weekday", hours(3))
    assert night.level == "Low"
    assert metrics.level in ("Moderate", "Heavy")


def test_congestion_level_thresholds():
    t = config.CONGESTION_THRESHOLDS
    assert congestion_level(1.0) == "Low"
    assert congestion_level(t["low_below"]) == "Moderate"
    assert congestion_level(t["heavy_from"] - 1e-9) == "Moderate"
    assert congestion_level(t["heavy_from"]) == "Heavy"
    assert congestion_level(1.5, {"low_below": 1.6, "heavy_from": 2.0}) == "Low"


def test_day_type_mapping():
    assert day_type_of("Saturday") == "weekend"
    assert day_type_of("Monday") == "weekday"
    assert day_type_of("Friday") == "weekday"

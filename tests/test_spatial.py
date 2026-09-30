import math
import random

import numpy as np
import pytest

from src.graph import haversine_m
from src.spatial import KDTree, snap_point
from tests.helpers import BASE_LAT, BASE_LON, synthetic_city


def brute_projected(tree, lat, lon):
    d2 = [tree.projected_distance2(lat, lon, i) for i in range(len(tree.lat))]
    return int(np.argmin(d2)), min(d2)


@pytest.mark.parametrize("seed", range(6))
def test_kdtree_matches_brute_force_on_random_points(seed):
    rng = random.Random(seed)
    n = rng.choice([1, 2, 7, 50, 400, 3000])
    lat = [BASE_LAT + rng.uniform(0, 0.2) for _ in range(n)]
    lon = [BASE_LON + rng.uniform(0, 0.2) for _ in range(n)]
    tree = KDTree(lat, lon)
    for _ in range(300):
        qlat = BASE_LAT + rng.uniform(-0.05, 0.25)
        qlon = BASE_LON + rng.uniform(-0.05, 0.25)
        idx, dist = tree.nearest(qlat, qlon)
        _, bd2 = brute_projected(tree, qlat, qlon)
        assert tree.projected_distance2(qlat, qlon, idx) == pytest.approx(bd2, rel=1e-12, abs=1e-9)
        best_haversine = min(haversine_m(qlat, qlon, a, b) for a, b in zip(lat, lon))
        assert dist == pytest.approx(best_haversine, abs=0.5 + 1e-3 * best_haversine)


def test_kdtree_finds_exact_point_and_handles_duplicates():
    lat = [24.86, 24.86, 24.87, 24.88]
    lon = [67.03, 67.03, 67.04, 67.05]
    tree = KDTree(lat, lon, leaf_size=1)
    idx, dist = tree.nearest(24.87, 67.04)
    assert idx == 2 and dist == 0.0
    idx, dist = tree.nearest(24.86, 67.03)
    assert idx in (0, 1) and dist == 0.0


def test_kdtree_on_city_nodes_matches_brute_force():
    g = synthetic_city(15, 15)
    tree = KDTree(g.lat_list(), g.lon_list())
    rng = random.Random(0)
    for _ in range(500):
        qlat = BASE_LAT + rng.uniform(-0.002, 0.026)
        qlon = BASE_LON + rng.uniform(-0.002, 0.026)
        idx, _ = tree.nearest(qlat, qlon)
        _, bd2 = brute_projected(tree, qlat, qlon)
        assert tree.projected_distance2(qlat, qlon, idx) == pytest.approx(bd2, rel=1e-12, abs=1e-9)


def test_kdtree_rejects_empty_input():
    with pytest.raises(ValueError):
        KDTree([], [])


def test_snap_warns_when_far():
    tree = KDTree([24.86], [67.03])
    near = snap_point(tree, 24.8601, 67.0301)
    assert near.node == 0 and not near.far and near.distance_m < 30
    far = snap_point(tree, 24.87, 67.03)
    assert far.far and far.distance_m == pytest.approx(1111.9, rel=1e-2)
    assert not snap_point(tree, 24.87, 67.03, threshold_m=5000).far
    assert math.isfinite(far.distance_m)

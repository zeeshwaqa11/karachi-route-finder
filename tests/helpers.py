import math
import random

import networkx as nx

from src import config
from src.graph import AdjacencyGraph, haversine_m

BASE_LAT = 24.86
BASE_LON = 67.03


def speed_mps(class_name: str) -> float:
    return config.DEFAULT_SPEEDS_KMH[class_name] / 3.6


def random_geo_graph(seed: int, n: int = 30, extra_edges: int = 60, parallel: bool = True, zero_weight: bool = False):
    rng = random.Random(seed)
    lat = [BASE_LAT + rng.uniform(0, 0.08) for _ in range(n)]
    lon = [BASE_LON + rng.uniform(0, 0.08) for _ in range(n)]
    g = AdjacencyGraph(list(range(1000, 1000 + n)), lat, lon)
    order = list(range(n))
    rng.shuffle(order)
    pairs = []
    for i in range(n):
        a, b = order[i], order[(i + 1) % n]
        pairs.append((a, b))
    for _ in range(extra_edges):
        a = rng.randrange(n)
        b = rng.randrange(n)
        if a != b:
            pairs.append((a, b))
    if parallel:
        for _ in range(max(1, extra_edges // 6)):
            pairs.append(rng.choice(pairs))
    classes = config.ROAD_CLASSES
    for a, b in pairs:
        hav = haversine_m(lat[a], lon[a], lat[b], lon[b])
        length = hav * rng.uniform(1.0, 1.6)
        cls = rng.choice(classes)
        time = length / speed_mps(cls)
        if zero_weight and rng.random() < 0.1:
            length = 0.0 if hav == 0 else length
            time = 0.0
        g.add_edge(a, b, length, time, cls, name=f"road {rng.randrange(10)}")
    return g


def synthetic_city(rows: int = 12, cols: int = 12, seed: int = 1):
    rng = random.Random(seed)
    step = 0.0016
    lat = []
    lon = []
    ids = []
    for r in range(rows):
        for c in range(cols):
            ids.append(r * cols + c + 1)
            lat.append(BASE_LAT + r * step + rng.uniform(-0.00015, 0.00015))
            lon.append(BASE_LON + c * step + rng.uniform(-0.00015, 0.00015))
    g = AdjacencyGraph(ids, lat, lon)

    def node(r, c):
        return r * cols + c

    def road(r1, c1, r2, c2, cls, name):
        a, b = node(r1, c1), node(r2, c2)
        hav = haversine_m(lat[a], lon[a], lat[b], lon[b])
        length = hav * rng.uniform(1.0, 1.12)
        time = length / speed_mps(cls)
        one_way = cls in ("residential", "service") and rng.random() < 0.25
        g.add_edge(a, b, length, time, cls, name)
        if not one_way:
            g.add_edge(b, a, length, time, cls, name)

    for r in range(rows):
        for c in range(cols):
            horizontal_cls = "primary" if r % 4 == 0 else ("secondary" if r % 4 == 2 else "residential")
            vertical_cls = "trunk" if c % 5 == 0 else ("tertiary" if c % 5 == 3 else "residential")
            h_name = "Shahrah-e-Faisal" if r == 0 else (f"Street {r}" if horizontal_cls == "residential" else f"Avenue {r}")
            v_name = "University Road" if c == 0 else f"Lane {c}"
            if c + 1 < cols:
                road(r, c, r, c + 1, horizontal_cls, h_name)
            if r + 1 < rows:
                road(r, c, r + 1, c, vertical_cls, v_name)
    return g


def to_networkx(g, kind: str = "length") -> nx.MultiDiGraph:
    weights = g.weight_list(kind)
    G = nx.MultiDiGraph()
    G.add_nodes_from(range(g.n))
    for u in range(g.n):
        for eid, v in g.out_edges(u):
            G.add_edge(u, v, key=eid, weight=weights[eid])
    return G


def to_simple_digraph(g, kind: str = "length") -> nx.DiGraph:
    weights = g.weight_list(kind)
    G = nx.DiGraph()
    G.add_nodes_from(range(g.n))
    for u in range(g.n):
        for eid, v in g.out_edges(u):
            if not G.has_edge(u, v) or weights[eid] < G[u][v]["weight"]:
                G.add_edge(u, v, weight=weights[eid])
    return G


def close(a: float, b: float, rel: float = 1e-9, abs_: float = 1e-9) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=abs_)

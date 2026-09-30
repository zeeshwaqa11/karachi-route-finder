import math

from src.graph import EARTH_RADIUS_M

HEURISTIC_SLACK = 1e-9


def _tag(fn, name: str, time_dependent: bool, per_metre: float):
    fn.weight_name = name
    fn.time_dependent = time_dependent
    fn.per_metre = per_metre
    return fn


def make_weight(fn, name: str, *, time_dependent: bool = False, per_metre: float = 0.0):
    return _tag(fn, name, time_dependent, per_metre)


def distance_weight(g):
    arr = g.weight_list("length")

    def weight(eid, d):
        return arr[eid]

    return _tag(weight, "distance", False, 1.0 - HEURISTIC_SLACK)


def free_flow_weight(g):
    arr = g.weight_list("time")

    def weight(eid, d):
        return arr[eid]

    return _tag(weight, "free_flow_time", False, 1.0 / g.max_speed_mps())


def combined_weight(g, time_coeff: float, distance_coeff: float):
    times = g.weight_list("time")
    lengths = g.weight_list("length")

    def weight(eid, d):
        return time_coeff * times[eid] + distance_coeff * lengths[eid]

    per_metre = time_coeff / g.max_speed_mps() + distance_coeff * (1.0 - HEURISTIC_SLACK)
    return _tag(weight, "combined", False, per_metre)


def is_time_dependent(weight) -> bool:
    return bool(getattr(weight, "time_dependent", False))


def haversine_heuristic(g, target: int, per_metre: float):
    cached = g._cache.get("trig")
    if cached is None:
        lat, lon = g.coords_lists()
        phi = [math.radians(x) for x in lat]
        lam = [math.radians(x) for x in lon]
        cosphi = [math.cos(x) for x in phi]
        cached = (phi, lam, cosphi)
        g._cache["trig"] = cached
    phi, lam, cosphi = cached
    tphi = phi[target]
    tlam = lam[target]
    tcos = cosphi[target]
    scale = per_metre * 2.0 * EARTH_RADIUS_M
    sin = math.sin
    asin = math.asin
    sqrt = math.sqrt

    def h(u):
        a = sin((phi[u] - tphi) * 0.5) ** 2 + cosphi[u] * tcos * sin((lam[u] - tlam) * 0.5) ** 2
        if a > 1.0:
            a = 1.0
        return scale * asin(sqrt(a))

    return h

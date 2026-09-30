import ast
import re
from collections import Counter

from src import config
from src.graph import AdjacencyGraph, CSRGraph, haversine_m
from src.scc import largest_scc_mask

_NUMBER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?\s*$", re.IGNORECASE)


def _as_list(value):
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        except (ValueError, SyntaxError):
            pass
    return [value]


def parse_maxspeed(value) -> float | None:
    speeds = []
    for item in _as_list(value):
        if item is None:
            continue
        match = _NUMBER.match(str(item))
        if not match:
            continue
        speed = float(match.group(1))
        if match.group(2) and match.group(2).lower() == "mph":
            speed *= 1.609344
        if config.MIN_VALID_SPEED_KMH <= speed <= config.MAX_VALID_SPEED_KMH:
            speeds.append(speed)
    return min(speeds) if speeds else None


def road_class_of(highway) -> str:
    best = None
    for item in _as_list(highway):
        cls = config.HIGHWAY_TO_CLASS.get(str(item))
        if cls is None:
            continue
        if best is None or config.ROAD_CLASSES.index(cls) < config.ROAD_CLASSES.index(best):
            best = cls
    return best or config.FALLBACK_CLASS


def road_name_of(name) -> str:
    parts = []
    for item in _as_list(name):
        if item and str(item) not in parts:
            parts.append(str(item))
    return " / ".join(parts)


def _interior_geometry(data, lat_u, lon_u, lat_v, lon_v):
    geom = data.get("geometry")
    if geom is None:
        return ()
    coords = [(float(y), float(x)) for x, y in geom.coords]
    if len(coords) <= 2:
        return ()
    if haversine_m(*coords[0], lat_u, lon_u) > haversine_m(*coords[0], lat_v, lon_v):
        coords.reverse()
    return tuple(coords[1:-1])


def convert_osmnx_graph(osm_graph) -> tuple[CSRGraph, dict]:
    node_list = list(osm_graph.nodes(data=True))
    index = {nid: i for i, (nid, _) in enumerate(node_list)}
    lat = [float(d["y"]) for _, d in node_list]
    lon = [float(d["x"]) for _, d in node_list]

    best: dict[tuple[int, int], dict] = {}
    self_loops = 0
    parallel_dropped = 0
    raw_edges = 0
    for u_id, v_id, data in osm_graph.edges(data=True):
        raw_edges += 1
        u = index[u_id]
        v = index[v_id]
        if u == v:
            self_loops += 1
            continue
        hav = haversine_m(lat[u], lon[u], lat[v], lon[v])
        length = max(float(data.get("length", hav)), hav)
        cls = road_class_of(data.get("highway"))
        speed = parse_maxspeed(data.get("maxspeed"))
        imputed = speed is None
        if imputed:
            speed = config.DEFAULT_SPEEDS_KMH[cls]
        time = length / (speed / 3.6)
        record = {
            "length": length,
            "time": time,
            "cls": cls,
            "name": road_name_of(data.get("name")),
            "imputed": imputed,
            "geometry": _interior_geometry(data, lat[u], lon[u], lat[v], lon[v]),
        }
        key = (u, v)
        current = best.get(key)
        if current is None:
            best[key] = record
            continue
        parallel_dropped += 1
        min_length = min(current["length"], record["length"])
        if (record["time"], record["length"]) < (current["time"], current["length"]):
            record["time"] = min(record["time"], current["time"])
            record["length"] = min_length
            best[key] = record
        else:
            current["length"] = min_length
            current["time"] = min(current["time"], record["time"])

    graph = AdjacencyGraph([nid for nid, _ in node_list], lat, lon)
    for (u, v), rec in best.items():
        graph.add_edge(u, v, rec["length"], rec["time"], rec["cls"], rec["name"], rec["imputed"], rec["geometry"])
    csr = graph.to_csr()

    nodes_before = csr.n
    edges_before = csr.m
    keep = largest_scc_mask(csr)
    csr = csr.subgraph(keep)

    class_counts = Counter(config.ROAD_CLASSES[c] for c in csr.road_class.tolist())
    area = config.AREAS[config.area_key()]
    report = {
        "area_key": config.area_key(),
        "area_label": area["label"],
        "osm_nodes_downloaded": len(node_list),
        "osm_edges_downloaded": raw_edges,
        "self_loops_dropped": self_loops,
        "parallel_edges_merged": parallel_dropped,
        "nodes_before_scc": nodes_before,
        "edges_before_scc": edges_before,
        "nodes": csr.n,
        "edges": csr.m,
        "nodes_dropped_by_scc": nodes_before - csr.n,
        "edges_dropped_by_scc": edges_before - csr.m,
        "edges_with_imputed_speed": int(csr.imputed.sum()),
        "imputed_share": float(csr.imputed.mean()) if csr.m else 0.0,
        "edges_by_class": {name: class_counts.get(name, 0) for name in config.ROAD_CLASSES},
        "default_speeds_kmh": config.DEFAULT_SPEEDS_KMH,
    }
    csr.meta = report
    return csr, report

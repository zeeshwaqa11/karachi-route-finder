import json
import math
from bisect import bisect_right
from pathlib import Path

import numpy as np

from src import config

EARTH_RADIUS_M = 6371009.0

CLASS_INDEX = {name: i for i, name in enumerate(config.ROAD_CLASSES)}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


class Edge:
    __slots__ = ("eid", "source", "target", "length", "time", "road_class", "name", "imputed", "geometry")

    def __init__(self, eid, source, target, length, time, road_class, name, imputed, geometry):
        self.eid = eid
        self.source = source
        self.target = target
        self.length = length
        self.time = time
        self.road_class = road_class
        self.name = name
        self.imputed = imputed
        self.geometry = geometry


class _GraphCommon:
    def coords_lists(self):
        return self.lat_list(), self.lon_list()

    def edge_class_name(self, eid: int) -> str:
        return config.ROAD_CLASSES[self.class_list()[eid]]

    def max_speed_mps(self) -> float:
        cached = self._cache.get("vmax")
        if cached is None:
            best = 0.0
            for length, time in zip(self.weight_list("length"), self.weight_list("time")):
                if time > 0.0 and length > 0.0:
                    speed = length / time
                    if speed > best:
                        best = speed
            cached = best * (1.0 + 1e-9)
            self._cache["vmax"] = cached
        return cached

    def edge_polyline(self, eid: int) -> list[tuple[float, float]]:
        s = self.edge_source(eid)
        t = self.edge_target(eid)
        lat, lon = self.lat_list(), self.lon_list()
        return [(lat[s], lon[s]), *self.edge_geometry(eid), (lat[t], lon[t])]

    def path_polyline(self, edge_ids) -> list[tuple[float, float]]:
        points: list[tuple[float, float]] = []
        for eid in edge_ids:
            poly = self.edge_polyline(eid)
            if points:
                poly = poly[1:]
            points.extend(poly)
        return points


class AdjacencyGraph(_GraphCommon):
    def __init__(self, node_ids, lat, lon):
        self.node_id = list(node_ids)
        self._lat = [float(x) for x in lat]
        self._lon = [float(x) for x in lon]
        self.n = len(self.node_id)
        self.edges: list[Edge] = []
        self._out: list[list[tuple[int, int]]] = [[] for _ in range(self.n)]
        self._in: list[list[tuple[int, int]]] = [[] for _ in range(self.n)]
        self._cache: dict = {}

    @property
    def m(self) -> int:
        return len(self.edges)

    def add_edge(self, source, target, length, time, road_class="residential", name="", imputed=False, geometry=()):
        eid = len(self.edges)
        cls = road_class if isinstance(road_class, int) else CLASS_INDEX[road_class]
        self.edges.append(Edge(eid, source, target, float(length), float(time), cls, name, bool(imputed), tuple(geometry)))
        self._out[source].append((eid, target))
        self._in[target].append((eid, source))
        self._cache.clear()
        return eid

    def out_edges(self, u: int):
        return self._out[u]

    def in_edges(self, v: int):
        return self._in[v]

    def edge_source(self, eid: int) -> int:
        return self.edges[eid].source

    def edge_target(self, eid: int) -> int:
        return self.edges[eid].target

    def edge_name(self, eid: int) -> str:
        return self.edges[eid].name

    def edge_imputed(self, eid: int) -> bool:
        return self.edges[eid].imputed

    def edge_geometry(self, eid: int):
        return self.edges[eid].geometry

    def lat_list(self):
        return self._lat

    def lon_list(self):
        return self._lon

    def weight_list(self, kind: str):
        key = ("w", kind)
        if key not in self._cache:
            if kind == "length":
                self._cache[key] = [e.length for e in self.edges]
            elif kind == "time":
                self._cache[key] = [e.time for e in self.edges]
            else:
                raise KeyError(kind)
        return self._cache[key]

    def class_list(self):
        if "cls" not in self._cache:
            self._cache["cls"] = [e.road_class for e in self.edges]
        return self._cache["cls"]

    def name_list(self):
        return [e.name for e in self.edges]

    def to_csr(self) -> "CSRGraph":
        order = sorted(range(self.m), key=lambda i: (self.edges[i].source, i))
        edges = [self.edges[i] for i in order]
        offsets = np.zeros(self.n + 1, dtype=np.int64)
        for e in edges:
            offsets[e.source + 1] += 1
        np.cumsum(offsets, out=offsets)
        names = sorted({e.name for e in edges} | {""})
        name_ix = {nm: i for i, nm in enumerate(names)}
        geom_counts = np.array([len(e.geometry) for e in edges], dtype=np.int64)
        geom_offsets = np.zeros(len(edges) + 1, dtype=np.int64)
        np.cumsum(geom_counts, out=geom_offsets[1:])
        flat = [pt for e in edges for pt in e.geometry]
        geom_xy = np.array(flat, dtype=np.float32).reshape(-1, 2)
        return CSRGraph(
            node_ids=np.array(self.node_id, dtype=np.int64),
            lat=np.array(self._lat, dtype=np.float64),
            lon=np.array(self._lon, dtype=np.float64),
            offsets=offsets.astype(np.int32),
            targets=np.array([e.target for e in edges], dtype=np.int32),
            length=np.array([e.length for e in edges], dtype=np.float64),
            time=np.array([e.time for e in edges], dtype=np.float64),
            road_class=np.array([e.road_class for e in edges], dtype=np.uint8),
            imputed=np.array([e.imputed for e in edges], dtype=bool),
            name_idx=np.array([name_ix[e.name] for e in edges], dtype=np.int32),
            names=np.array(names, dtype=str),
            geom_offsets=geom_offsets.astype(np.int32),
            geom_xy=geom_xy,
        )


class CSRGraph(_GraphCommon):
    ARRAYS = (
        "node_ids",
        "lat",
        "lon",
        "offsets",
        "targets",
        "length",
        "time",
        "road_class",
        "imputed",
        "name_idx",
        "names",
        "geom_offsets",
        "geom_xy",
    )

    def __init__(
        self,
        node_ids,
        lat,
        lon,
        offsets,
        targets,
        length,
        time,
        road_class,
        imputed,
        name_idx,
        names,
        geom_offsets,
        geom_xy,
        meta=None,
    ):
        self.node_ids = node_ids
        self.lat = lat
        self.lon = lon
        self.offsets = offsets
        self.targets = targets
        self.length = length
        self.time = time
        self.road_class = road_class
        self.imputed = imputed
        self.name_idx = name_idx
        self.names = names
        self.geom_offsets = geom_offsets
        self.geom_xy = geom_xy
        self.meta = dict(meta or {})
        self.n = int(len(lat))
        self._cache: dict = {}

    @property
    def m(self) -> int:
        return int(len(self.targets))

    @property
    def node_id(self):
        return self.node_ids

    def _py(self, key, array):
        if key not in self._cache:
            self._cache[key] = array.tolist()
        return self._cache[key]

    def lat_list(self):
        return self._py("lat", self.lat)

    def lon_list(self):
        return self._py("lon", self.lon)

    def weight_list(self, kind: str):
        if kind == "length":
            return self._py("length", self.length)
        if kind == "time":
            return self._py("time", self.time)
        raise KeyError(kind)

    def class_list(self):
        return self._py("cls", self.road_class)

    def _reverse(self):
        if "rev" not in self._cache:
            counts = np.diff(self.offsets.astype(np.int64))
            src = np.repeat(np.arange(self.n, dtype=np.int32), counts)
            order = np.argsort(self.targets, kind="stable").astype(np.int32)
            r_offsets = np.zeros(self.n + 1, dtype=np.int64)
            np.cumsum(np.bincount(self.targets, minlength=self.n), out=r_offsets[1:])
            self._cache["rev"] = (r_offsets.tolist(), order.tolist(), src[order].tolist())
        return self._cache["rev"]

    def out_edges(self, u: int):
        off = self._py("off", self.offsets)
        a = off[u]
        b = off[u + 1]
        return zip(range(a, b), self._py("tgt", self.targets)[a:b])

    def in_edges(self, v: int):
        r_off, r_eid, r_src = self._reverse()
        a = r_off[v]
        b = r_off[v + 1]
        return zip(r_eid[a:b], r_src[a:b])

    def edge_source(self, eid: int) -> int:
        return bisect_right(self._py("off", self.offsets), eid) - 1

    def edge_target(self, eid: int) -> int:
        return self._py("tgt", self.targets)[eid]

    def edge_name(self, eid: int) -> str:
        return str(self.names[self.name_idx[eid]])

    def edge_imputed(self, eid: int) -> bool:
        return bool(self.imputed[eid])

    def edge_geometry(self, eid: int):
        a = int(self.geom_offsets[eid])
        b = int(self.geom_offsets[eid + 1])
        return [(float(x), float(y)) for x, y in self.geom_xy[a:b]]

    def name_list(self):
        names = self.names.tolist()
        return [names[i] for i in self.name_idx.tolist()]

    def to_adjacency(self) -> AdjacencyGraph:
        g = AdjacencyGraph(self.node_ids.tolist(), self.lat, self.lon)
        off = self.offsets.tolist()
        for u in range(self.n):
            for eid in range(off[u], off[u + 1]):
                g.add_edge(
                    u,
                    int(self.targets[eid]),
                    self.length[eid],
                    self.time[eid],
                    int(self.road_class[eid]),
                    self.edge_name(eid),
                    bool(self.imputed[eid]),
                    self.edge_geometry(eid),
                )
        return g

    def array_bytes(self) -> int:
        return int(sum(getattr(self, name).nbytes for name in self.ARRAYS))

    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: getattr(self, name) for name in self.ARRAYS}
        payload["meta_json"] = np.array(json.dumps(self.meta))
        np.savez_compressed(path, **payload)

    @classmethod
    def load(cls, path) -> "CSRGraph":
        with np.load(Path(path), allow_pickle=False) as z:
            arrays = {name: z[name] for name in cls.ARRAYS}
            meta = json.loads(str(z["meta_json"])) if "meta_json" in z.files else {}
        return cls(**arrays, meta=meta)

    def subgraph(self, keep: np.ndarray) -> "CSRGraph":
        keep = np.asarray(keep, dtype=bool)
        counts = np.diff(self.offsets.astype(np.int64))
        src = np.repeat(np.arange(self.n), counts)
        edge_keep = keep[src] & keep[self.targets]
        new_index = np.cumsum(keep) - 1
        new_src = new_index[src[edge_keep]]
        new_off = np.zeros(int(keep.sum()) + 1, dtype=np.int64)
        np.cumsum(np.bincount(new_src, minlength=int(keep.sum())), out=new_off[1:])
        gcounts = np.diff(self.geom_offsets.astype(np.int64))
        kept_geom_counts = gcounts[edge_keep]
        geom_off = np.zeros(int(edge_keep.sum()) + 1, dtype=np.int64)
        np.cumsum(kept_geom_counts, out=geom_off[1:])
        point_keep = np.repeat(edge_keep, gcounts)
        return CSRGraph(
            node_ids=self.node_ids[keep],
            lat=self.lat[keep],
            lon=self.lon[keep],
            offsets=new_off.astype(np.int32),
            targets=new_index[self.targets[edge_keep]].astype(np.int32),
            length=self.length[edge_keep],
            time=self.time[edge_keep],
            road_class=self.road_class[edge_keep],
            imputed=self.imputed[edge_keep],
            name_idx=self.name_idx[edge_keep],
            names=self.names,
            geom_offsets=geom_off.astype(np.int32),
            geom_xy=self.geom_xy[point_keep],
            meta=self.meta,
        )

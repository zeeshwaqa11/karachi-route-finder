import math
from dataclasses import dataclass

import numpy as np

from src import config
from src.graph import EARTH_RADIUS_M, haversine_m

LEAF_SIZE = 8


class KDTree:
    def __init__(self, lat, lon, leaf_size: int = LEAF_SIZE):
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        if len(lat) == 0:
            raise ValueError("cannot build a KD-tree without points")
        self.lat = lat.tolist()
        self.lon = lon.tolist()
        self.lat0 = float(lat.mean())
        self._ky = EARTH_RADIUS_M * math.pi / 180.0
        self._kx = self._ky * math.cos(math.radians(self.lat0))
        coords = np.column_stack([lon * self._kx, lat * self._ky])
        self._coords = coords
        self.xs = coords[:, 0].tolist()
        self.ys = coords[:, 1].tolist()
        self._leaf_size = max(1, leaf_size)
        self._order = np.arange(len(lat))
        self._axis: list[int] = []
        self._split: list[float] = []
        self._left: list[int] = []
        self._right: list[int] = []
        self._lo: list[int] = []
        self._hi: list[int] = []
        self._build(0, len(lat))
        self.order = self._order.tolist()

    def _new_node(self):
        self._axis.append(-1)
        self._split.append(0.0)
        self._left.append(-1)
        self._right.append(-1)
        self._lo.append(0)
        self._hi.append(0)
        return len(self._axis) - 1

    def _build(self, lo: int, hi: int) -> int:
        node = self._new_node()
        if hi - lo <= self._leaf_size:
            self._lo[node] = lo
            self._hi[node] = hi
            return node
        block = self._order[lo:hi]
        pts = self._coords[block]
        axis = int(np.argmax(pts.max(axis=0) - pts.min(axis=0)))
        sorted_block = block[np.argsort(pts[:, axis], kind="stable")]
        self._order[lo:hi] = sorted_block
        mid = (lo + hi) // 2
        self._axis[node] = axis
        self._split[node] = float(self._coords[sorted_block[mid - lo], axis])
        self._left[node] = self._build(lo, mid)
        self._right[node] = self._build(mid, hi)
        return node

    def nearest(self, lat: float, lon: float) -> tuple[int, float]:
        qx = lon * self._kx
        qy = lat * self._ky
        best = [math.inf, -1]
        self._search(0, qx, qy, best)
        idx = best[1]
        return idx, haversine_m(lat, lon, self.lat[idx], self.lon[idx])

    def _search(self, node: int, qx: float, qy: float, best: list) -> None:
        axis = self._axis[node]
        if axis < 0:
            xs = self.xs
            ys = self.ys
            order = self.order
            for pos in range(self._lo[node], self._hi[node]):
                i = order[pos]
                dx = xs[i] - qx
                dy = ys[i] - qy
                d2 = dx * dx + dy * dy
                if d2 < best[0]:
                    best[0] = d2
                    best[1] = i
            return
        diff = (qx if axis == 0 else qy) - self._split[node]
        if diff < 0.0:
            near, far = self._left[node], self._right[node]
        else:
            near, far = self._right[node], self._left[node]
        self._search(near, qx, qy, best)
        if diff * diff < best[0]:
            self._search(far, qx, qy, best)

    def projected_distance2(self, lat: float, lon: float, idx: int) -> float:
        dx = self.xs[idx] - lon * self._kx
        dy = self.ys[idx] - lat * self._ky
        return dx * dx + dy * dy


@dataclass
class Snap:
    node: int
    distance_m: float
    far: bool


def snap_point(tree: KDTree, lat: float, lon: float, threshold_m: float | None = None) -> Snap:
    limit = config.SNAP_WARNING_METRES if threshold_m is None else threshold_m
    node, dist = tree.nearest(lat, lon)
    return Snap(node, dist, dist > limit)

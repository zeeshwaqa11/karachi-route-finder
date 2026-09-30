from dataclasses import dataclass

from src import config
from src.routing.weights import free_flow_weight, make_weight

DAY_SECONDS = 86400.0
SLOT_SECONDS = config.SLOT_MINUTES * 60.0
INV_SLOT = 1.0 / SLOT_SECONDS
TABLE_LEN = config.SLOTS_PER_DAY + 1


def normalise_name(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def day_type_of(day_name: str) -> str:
    return "weekend" if day_name in config.WEEKEND_DAYS else "weekday"


def interpolate_anchors(anchors, hour: float) -> float:
    if hour <= anchors[0][0]:
        return anchors[0][1]
    for (h0, v0), (h1, v1) in zip(anchors, anchors[1:]):
        if hour <= h1:
            if h1 == h0:
                return v1
            return v0 + (v1 - v0) * (hour - h0) / (h1 - h0)
    return anchors[-1][1]


def build_slot_table(anchors, sensitivity: float) -> list[float]:
    table = []
    for k in range(config.SLOTS_PER_DAY):
        base = interpolate_anchors(anchors, k * config.SLOT_MINUTES / 60.0)
        table.append(1.0 + sensitivity * (base - 1.0))
    table.append(table[0])
    return table


def congestion_level(multiplier: float, thresholds=None) -> str:
    t = thresholds or config.CONGESTION_THRESHOLDS
    if multiplier < t["low_below"]:
        return "Low"
    if multiplier < t["heavy_from"]:
        return "Moderate"
    return "Heavy"


@dataclass
class RouteMetrics:
    distance_m: float
    free_flow_s: float
    travel_s: float
    avg_multiplier: float
    level: str


class CongestionModel:
    def __init__(
        self,
        graph,
        *,
        weekday_anchors=None,
        weekend_anchors=None,
        sensitivity=None,
        corridors=None,
        thresholds=None,
    ):
        self.graph = graph
        self.thresholds = thresholds or config.CONGESTION_THRESHOLDS
        anchors = {
            "weekday": weekday_anchors or config.WEEKDAY_ANCHORS_HOURS,
            "weekend": weekend_anchors or config.WEEKEND_ANCHORS_HOURS,
        }
        sensitivity = sensitivity or config.CLASS_SENSITIVITY
        self.corridors = corridors if corridors is not None else config.CORRIDOR_MULTIPLIERS
        for day, points in anchors.items():
            if min(v for _, v in points) < 1.0:
                raise ValueError(f"{day} profile has a multiplier below 1.0; free-flow time must be a lower bound")
        if min(sensitivity.values()) < 0.0:
            raise ValueError("class sensitivities must be non-negative")
        self.tables = {
            day: [build_slot_table(points, sensitivity[name]) for name in config.ROAD_CLASSES] for day, points in anchors.items()
        }
        self._base = graph.weight_list("time")
        self._length = graph.weight_list("length")
        self._cls = graph.class_list()
        self.corridor_factor, self.corridor_edges = self._match_corridors()
        self.fifo_ratio = {day: self.verify_fifo(day) for day in self.tables}

    def _match_corridors(self):
        wanted = []
        for label, spec in self.corridors.items():
            if spec["multiplier"] < 1.0:
                raise ValueError(f"corridor {label!r} multiplier must be at least 1.0")
            wanted.append((label, spec["multiplier"], [normalise_name(a) for a in spec["aliases"]]))
        cache: dict[str, tuple[float, str | None]] = {}

        def match(name: str):
            if name in cache:
                return cache[name]
            result = (1.0, None)
            for part in name.split(" / "):
                norm = normalise_name(part)
                if not norm:
                    continue
                for label, factor, aliases in wanted:
                    if any(norm.startswith(alias) for alias in aliases) and factor > result[0]:
                        result = (factor, label)
            cache[name] = result
            return result

        factors = []
        counts = {label: 0 for label, _, _ in wanted}
        for name in self.graph.name_list():
            factor, label = match(name)
            factors.append(factor)
            if label is not None:
                counts[label] += 1
        return factors, counts

    def verify_fifo(self, day_type: str) -> float:
        tables = self.tables[day_type]
        worst = 0.0
        biggest = [0.0] * len(tables)
        for base, corr, cls in zip(self._base, self.corridor_factor, self._cls):
            value = base * corr
            if value > biggest[cls]:
                biggest[cls] = value
        for cls, table in enumerate(tables):
            drop = max(max(table[k] - table[k + 1], 0.0) for k in range(config.SLOTS_PER_DAY))
            worst = max(worst, biggest[cls] * drop / SLOT_SECONDS)
        if worst > 1.0:
            raise ValueError(
                f"{day_type} profile violates FIFO: an edge could be traversed faster by leaving later "
                f"(worst slope ratio {worst:.2f} > 1)"
            )
        return worst

    def multiplier(self, eid: int, day_type: str, clock_s: float) -> float:
        x = (clock_s % DAY_SECONDS) * INV_SLOT
        k = int(x)
        tab = self.tables[day_type][self._cls[eid]]
        return self.corridor_factor[eid] * (tab[k] + (x - k) * (tab[k + 1] - tab[k]))

    def edge_travel_time(self, eid: int, day_type: str, clock_s: float) -> float:
        return self._base[eid] * self.multiplier(eid, day_type, clock_s)

    def weight(self, day_type: str, depart_s: float):
        tables = self.tables[day_type]
        base = self._base
        cls = self._cls
        corr = self.corridor_factor
        t0 = depart_s

        def weight(eid, d):
            x = ((t0 + d) % DAY_SECONDS) * INV_SLOT
            k = int(x)
            tab = tables[cls[eid]]
            return base[eid] * corr[eid] * (tab[k] + (x - k) * (tab[k + 1] - tab[k]))

        return make_weight(
            weight,
            "time_dependent",
            time_dependent=True,
            per_metre=1.0 / self.graph.max_speed_mps(),
            lower_bound=free_flow_weight(self.graph),
        )

    def route_metrics(self, edges, day_type: str, depart_s: float) -> RouteMetrics:
        elapsed = 0.0
        distance = 0.0
        free_flow = 0.0
        weighted = 0.0
        for eid in edges:
            mult = self.multiplier(eid, day_type, depart_s + elapsed)
            elapsed += self._base[eid] * mult
            distance += self._length[eid]
            free_flow += self._base[eid]
            weighted += self._length[eid] * mult
        avg = weighted / distance if distance > 0.0 else 1.0
        return RouteMetrics(distance, free_flow, elapsed, avg, congestion_level(avg, self.thresholds))

    def profile_curve(self, day_type: str, class_name: str):
        return self.tables[day_type][config.ROAD_CLASSES.index(class_name)][:-1]

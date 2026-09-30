from dataclasses import dataclass, field

from src import config
from src.congestion import RouteMetrics
from src.routing.yen import RoutePath

LABEL_TOLERANCE = 1e-9


@dataclass
class RankedRoute:
    rank: int
    score: float
    path: RoutePath
    metrics: RouteMetrics
    labels: list[str] = field(default_factory=list)

    @property
    def distance_km(self) -> float:
        return self.metrics.distance_m / 1000.0

    @property
    def time_min(self) -> float:
        return self.metrics.travel_s / 60.0

    @property
    def label_text(self) -> str:
        return " · ".join(self.labels) if self.labels else "Alternative"


def normalise_weights(weights: dict) -> dict:
    cleaned = {k: max(0.0, float(weights.get(k, 0.0))) for k in ("time", "distance", "congestion")}
    total = sum(cleaned.values())
    if total <= 0.0:
        return {k: 1.0 / 3.0 for k in cleaned}
    return {k: v / total for k, v in cleaned.items()}


def combined_costs(metrics: list[RouteMetrics], weights: dict) -> list[float]:
    w = normalise_weights(weights)
    best_time = min(m.travel_s for m in metrics)
    best_dist = min(m.distance_m for m in metrics)
    best_cong = min(m.avg_multiplier for m in metrics)
    costs = []
    for m in metrics:
        time_n = m.travel_s / best_time if best_time > 0 else 1.0
        dist_n = m.distance_m / best_dist if best_dist > 0 else 1.0
        cong_n = m.avg_multiplier / best_cong if best_cong > 0 else 1.0
        costs.append(w["time"] * time_n + w["distance"] * dist_n + w["congestion"] * cong_n)
    return costs


def assign_labels(routes: list[RankedRoute]) -> None:
    if not routes:
        return
    measures = (
        ("Fastest", lambda r: r.metrics.travel_s),
        ("Shortest", lambda r: r.metrics.distance_m),
        ("Least congested", lambda r: r.metrics.avg_multiplier),
    )
    for label, key in measures:
        best = min(key(r) for r in routes)
        for r in routes:
            if key(r) <= best * (1.0 + LABEL_TOLERANCE) + LABEL_TOLERANCE:
                r.labels.append(label)


def rank_routes(candidates: list[tuple[RoutePath, RouteMetrics]], weights: dict | None = None) -> list[RankedRoute]:
    if not candidates:
        return []
    weights = weights or config.DEFAULT_ROUTE_WEIGHTS
    costs = combined_costs([m for _, m in candidates], weights)
    order = sorted(range(len(candidates)), key=lambda i: (costs[i], candidates[i][1].travel_s))
    ranked = [
        RankedRoute(rank=pos + 1, score=costs[i], path=candidates[i][0], metrics=candidates[i][1]) for pos, i in enumerate(order)
    ]
    assign_labels(ranked)
    return ranked

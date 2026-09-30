import time
from dataclasses import dataclass, field

from src import config
from src.congestion import CongestionModel, day_type_of
from src.ranking import RankedRoute, rank_routes
from src.routing.yen import yen_k_shortest


@dataclass
class RouteRequest:
    source: int
    target: int
    day: str = "Monday"
    depart_s: float = 8 * 3600.0
    k: int = 3
    algorithm: str = "astar"
    heuristic: str = "reverse"
    weights: dict = field(default_factory=lambda: dict(config.DEFAULT_ROUTE_WEIGHTS))
    diversity_threshold: float | None = config.DIVERSITY_THRESHOLD


@dataclass
class RouteResponse:
    routes: list[RankedRoute]
    candidates: list
    compute_ms: float
    settled: int
    relaxed: int
    spur_searches: int
    enumerated: int
    rejected_as_similar: int
    requested_k: int

    @property
    def found_all(self) -> bool:
        return len(self.routes) >= self.requested_k


def plan_routes(graph, congestion: CongestionModel, request: RouteRequest) -> RouteResponse:
    day_type = day_type_of(request.day)
    theta = request.diversity_threshold
    window_fraction = (1.0 - theta) / (1.0 + theta) if theta is not None else 0.0
    weight = congestion.weight(day_type, request.depart_s)
    started = time.perf_counter()
    yen = yen_k_shortest(
        graph,
        request.source,
        request.target,
        weight,
        request.k,
        algorithm=request.algorithm,
        heuristic=request.heuristic,
        diversity_threshold=request.diversity_threshold,
        window_fraction=window_fraction,
        spur_stride_fraction=window_fraction / config.SPUR_STRIDE_DIVISOR,
        max_cost_ratio=config.ALTERNATIVE_COST_RATIO if request.diversity_threshold is not None else None,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    candidates = [(p, congestion.route_metrics(p.edges, day_type, request.depart_s)) for p in yen.paths]
    return RouteResponse(
        routes=rank_routes(candidates, request.weights),
        candidates=candidates,
        compute_ms=elapsed_ms,
        settled=yen.settled,
        relaxed=yen.relaxed,
        spur_searches=yen.spur_searches,
        enumerated=yen.enumerated,
        rejected_as_similar=yen.rejected_as_similar,
        requested_k=request.k,
    )

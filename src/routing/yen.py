from bisect import bisect_left
from dataclasses import dataclass, field

from src import config
from src.heap import LazyMinHeap
from src.routing.astar import astar
from src.routing.dijkstra import backward_distances, dijkstra
from src.routing.result import INF
from src.routing.weights import haversine_heuristic


@dataclass
class RoutePath:
    cost: float
    nodes: list[int]
    edges: list[int]
    spur_index: int = 0


@dataclass
class YenResult:
    paths: list[RoutePath] = field(default_factory=list)
    enumerated: int = 0
    rejected_as_similar: int = 0
    spur_searches: int = 0
    settled: int = 0
    relaxed: int = 0
    potential_settled: int = 0


def overlap_similarity(edges_a, edges_b, lengths) -> float:
    set_a = set(edges_a)
    set_b = set(edges_b)
    shared = sum(lengths[e] for e in set_a & set_b)
    union = sum(lengths[e] for e in set_a | set_b)
    if union <= 0.0:
        return 1.0 if set_a == set_b else 0.0
    return shared / union


def path_prefix_costs(weight, edges, start: float = 0.0) -> list[float]:
    costs = [start]
    total = start
    for eid in edges:
        total += weight(eid, total)
        costs.append(total)
    return costs


def _reverse_heuristic(potential: dict):
    get = potential.get

    def h(u):
        return get(u, INF)

    return h


def yen_k_shortest(
    g,
    source: int,
    target: int,
    weight,
    k: int,
    *,
    algorithm: str = "astar",
    heuristic: str = "haversine",
    diversity_threshold: float | None = None,
    max_paths: int | None = None,
    window_fraction: float = 0.0,
    max_cost_ratio: float | None = None,
    spur_stride_fraction: float = 0.0,
) -> YenResult:
    if k < 1:
        raise ValueError("k must be at least 1")
    if algorithm not in ("dijkstra", "astar"):
        raise ValueError(f"unknown algorithm {algorithm!r}")
    if heuristic not in ("haversine", "reverse"):
        raise ValueError(f"unknown heuristic {heuristic!r}")
    result = YenResult()
    lengths = g.weight_list("length")
    guide = None
    if algorithm == "astar":
        if heuristic == "reverse":
            bound = getattr(weight, "lower_bound", None)
            if bound is None:
                raise ValueError("the reverse-distance heuristic needs a weight with a static lower bound")
            potential, settled, relaxed = backward_distances(g, target, bound)
            result.potential_settled = settled
            result.relaxed += relaxed
            guide = _reverse_heuristic(potential)
        else:
            guide = haversine_heuristic(g, target, weight.per_metre)

    limit = [INF]

    def search(start, init, banned_nodes, banned_edges):
        if algorithm == "astar":
            res = astar(
                g,
                start,
                target,
                weight,
                guide,
                init=init,
                banned_nodes=banned_nodes,
                banned_edges=banned_edges,
                cost_limit=limit[0],
            )
        else:
            res = dijkstra(
                g, start, target, weight, init=init, banned_nodes=banned_nodes, banned_edges=banned_edges, cost_limit=limit[0]
            )
        result.spur_searches += 1
        result.settled += res.settled
        result.relaxed += res.relaxed
        return res

    first = search(source, 0.0, frozenset(), frozenset())
    if not first.found:
        return result
    if max_cost_ratio is not None:
        limit[0] = first.cost * max_cost_ratio
    if max_paths is None:
        if diversity_threshold is None:
            max_paths = k
        else:
            max_paths = min(config.YEN_MAX_PATHS_ABSOLUTE, max(k, k * config.YEN_MAX_CANDIDATES_FACTOR))

    enumerated = [RoutePath(first.cost, first.nodes, first.edges, 0)]
    accepted = [enumerated[0]]
    seen = {tuple(first.edges)}
    candidates: dict[int, RoutePath] = {}
    heap = LazyMinHeap()
    counter = 0

    while len(accepted) < k and len(enumerated) < max_paths:
        last = enumerated[-1]
        prefix = path_prefix_costs(weight, last.edges)
        cumulative = [0.0]
        for eid in last.edges:
            cumulative.append(cumulative[-1] + lengths[eid])
        window = window_fraction * cumulative[-1]
        stride = spur_stride_fraction * cumulative[-1]
        next_allowed = -1.0
        for i in range(last.spur_index, len(last.edges)):
            if stride > 0.0:
                if cumulative[i] < next_allowed:
                    continue
                next_allowed = cumulative[i] + stride
            root_edges = last.edges[:i]
            banned_edges = {p.edges[i] for p in enumerated if len(p.edges) > i and p.edges[:i] == root_edges}
            banned_nodes = set(last.nodes[:i])
            if window > 0.0:
                stop = min(bisect_left(cumulative, cumulative[i] + window), len(last.nodes) - 1)
                banned_nodes.update(last.nodes[i + 1 : stop])
            res = search(last.nodes[i], prefix[i], banned_nodes, banned_edges)
            if not res.found:
                continue
            total_edges = root_edges + res.edges
            key = tuple(total_edges)
            if key in seen:
                continue
            seen.add(key)
            candidates[counter] = RoutePath(res.cost, last.nodes[:i] + res.nodes, total_edges, i)
            heap.push(counter, res.cost)
            counter += 1
        if not heap:
            break
        idx, _ = heap.pop()
        best = candidates.pop(idx)
        enumerated.append(best)
        if diversity_threshold is None or all(
            overlap_similarity(best.edges, other.edges, lengths) <= diversity_threshold for other in accepted
        ):
            accepted.append(best)
        else:
            result.rejected_as_similar += 1

    result.paths = accepted
    result.enumerated = len(enumerated)
    return result

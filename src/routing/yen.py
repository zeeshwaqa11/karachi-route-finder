from dataclasses import dataclass, field

from src import config
from src.heap import LazyMinHeap
from src.routing.astar import astar
from src.routing.dijkstra import dijkstra
from src.routing.weights import haversine_heuristic


@dataclass
class RoutePath:
    cost: float
    nodes: list[int]
    edges: list[int]


@dataclass
class YenResult:
    paths: list[RoutePath] = field(default_factory=list)
    enumerated: int = 0
    rejected_as_similar: int = 0
    spur_searches: int = 0
    settled: int = 0
    relaxed: int = 0


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


def yen_k_shortest(
    g,
    source: int,
    target: int,
    weight,
    k: int,
    *,
    algorithm: str = "astar",
    diversity_threshold: float | None = None,
    max_paths: int | None = None,
) -> YenResult:
    if k < 1:
        raise ValueError("k must be at least 1")
    if algorithm not in ("dijkstra", "astar"):
        raise ValueError(f"unknown algorithm {algorithm!r}")
    result = YenResult()
    lengths = g.weight_list("length")
    heuristic = haversine_heuristic(g, target, weight.per_metre) if algorithm == "astar" else None

    def search(start, init, banned_nodes, banned_edges):
        if algorithm == "astar":
            res = astar(g, start, target, weight, heuristic, init=init, banned_nodes=banned_nodes, banned_edges=banned_edges)
        else:
            res = dijkstra(g, start, target, weight, init=init, banned_nodes=banned_nodes, banned_edges=banned_edges)
        result.spur_searches += 1
        result.settled += res.settled
        result.relaxed += res.relaxed
        return res

    first = search(source, 0.0, frozenset(), frozenset())
    if not first.found:
        return result
    if max_paths is None:
        if diversity_threshold is None:
            max_paths = k
        else:
            max_paths = min(config.YEN_MAX_PATHS_ABSOLUTE, max(k, k * config.YEN_MAX_CANDIDATES_FACTOR))

    enumerated = [RoutePath(first.cost, first.nodes, first.edges)]
    accepted = [enumerated[0]]
    seen = {tuple(first.edges)}
    candidates: dict[int, RoutePath] = {}
    heap = LazyMinHeap()
    counter = 0

    while len(accepted) < k and len(enumerated) < max_paths:
        last = enumerated[-1]
        prefix = path_prefix_costs(weight, last.edges)
        for i in range(len(last.edges)):
            root_edges = last.edges[:i]
            banned_edges = {p.edges[i] for p in enumerated if len(p.edges) > i and p.edges[:i] == root_edges}
            banned_nodes = set(last.nodes[:i])
            res = search(last.nodes[i], prefix[i], banned_nodes, banned_edges)
            if not res.found:
                continue
            total_edges = root_edges + res.edges
            key = tuple(total_edges)
            if key in seen:
                continue
            seen.add(key)
            candidates[counter] = RoutePath(res.cost, last.nodes[:i] + res.nodes, total_edges)
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

from dataclasses import dataclass, field

INF = float("inf")


@dataclass
class SearchResult:
    found: bool
    cost: float = INF
    nodes: list[int] = field(default_factory=list)
    edges: list[int] = field(default_factory=list)
    settled: int = 0
    relaxed: int = 0
    explored: list[int] | None = None
    explored_backward: list[int] | None = None
    dist: dict | None = None


def trace_back(prev: dict, source: int, target: int) -> tuple[list[int], list[int]]:
    nodes = [target]
    edges: list[int] = []
    node = target
    while node != source:
        node, eid = prev[node]
        nodes.append(node)
        edges.append(eid)
    nodes.reverse()
    edges.reverse()
    return nodes, edges

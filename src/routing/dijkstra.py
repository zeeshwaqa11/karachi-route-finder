from src.heap import IndexedMinHeap, LazyMinHeap
from src.routing.result import INF, SearchResult, trace_back

NO_BANS: frozenset = frozenset()


def dijkstra(
    g,
    source: int,
    target: int | None,
    weight,
    *,
    init: float = 0.0,
    heap: str = "lazy",
    banned_nodes=NO_BANS,
    banned_edges=NO_BANS,
    record: bool = False,
    cost_limit: float = INF,
) -> SearchResult:
    if heap == "decrease_key":
        return _dijkstra_decrease_key(g, source, target, weight, init, banned_nodes, banned_edges, record, cost_limit)
    if heap != "lazy":
        raise ValueError(f"unknown heap strategy {heap!r}")

    out_edges = g.out_edges
    dist = {source: init}
    prev: dict = {}
    queue = LazyMinHeap()
    push = queue.push
    pop = queue.pop
    push(source, init)
    settled = 0
    relaxed = 0
    order = [] if record else None
    reached = False
    while True:
        try:
            u, d = pop()
        except IndexError:
            break
        if d > dist[u]:
            continue
        settled += 1
        if order is not None:
            order.append(u)
        if u == target:
            reached = True
            break
        for eid, v in out_edges(u):
            if v in banned_nodes or eid in banned_edges:
                continue
            relaxed += 1
            nd = d + weight(eid, d)
            if nd > cost_limit:
                continue
            old = dist.get(v)
            if old is None or nd < old:
                dist[v] = nd
                prev[v] = (u, eid)
                push(v, nd)
    return _finish(reached, source, target, dist, prev, settled, relaxed, order)


def _dijkstra_decrease_key(g, source, target, weight, init, banned_nodes, banned_edges, record, cost_limit):
    out_edges = g.out_edges
    dist = {source: init}
    prev: dict = {}
    queue = IndexedMinHeap()
    push = queue.push
    pop = queue.pop
    decrease = queue.decrease_key
    push(source, init)
    settled = 0
    relaxed = 0
    order = [] if record else None
    reached = False
    while True:
        try:
            u, d = pop()
        except IndexError:
            break
        settled += 1
        if order is not None:
            order.append(u)
        if u == target:
            reached = True
            break
        for eid, v in out_edges(u):
            if v in banned_nodes or eid in banned_edges:
                continue
            relaxed += 1
            nd = d + weight(eid, d)
            if nd > cost_limit:
                continue
            old = dist.get(v)
            if old is None:
                dist[v] = nd
                prev[v] = (u, eid)
                push(v, nd)
            elif nd < old:
                dist[v] = nd
                prev[v] = (u, eid)
                decrease(v, nd)
    return _finish(reached, source, target, dist, prev, settled, relaxed, order)


def _finish(reached, source, target, dist, prev, settled, relaxed, order) -> SearchResult:
    if target is None:
        return SearchResult(False, INF, [], [], settled, relaxed, order, None, dist)
    if not reached:
        return SearchResult(False, INF, [], [], settled, relaxed, order, None, dist)
    nodes, edges = trace_back(prev, source, target)
    return SearchResult(True, dist[target], nodes, edges, settled, relaxed, order, None, dist)


def backward_distances(g, target: int, weight) -> tuple[dict, int, int]:
    in_edges = g.in_edges
    dist = {target: 0.0}
    queue = LazyMinHeap()
    push = queue.push
    pop = queue.pop
    push(target, 0.0)
    settled = 0
    relaxed = 0
    while True:
        try:
            v, d = pop()
        except IndexError:
            break
        if d > dist[v]:
            continue
        settled += 1
        for eid, u in in_edges(v):
            relaxed += 1
            nd = d + weight(eid, d)
            old = dist.get(u)
            if old is None or nd < old:
                dist[u] = nd
                push(u, nd)
    return dist, settled, relaxed

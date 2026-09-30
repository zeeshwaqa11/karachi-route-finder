from src.heap import LazyMinHeap
from src.routing.dijkstra import NO_BANS
from src.routing.result import INF, SearchResult, trace_back


def astar(
    g,
    source: int,
    target: int,
    weight,
    heuristic,
    *,
    init: float = 0.0,
    banned_nodes=NO_BANS,
    banned_edges=NO_BANS,
    record: bool = False,
    cost_limit: float = INF,
) -> SearchResult:
    out_edges = g.out_edges
    dist = {source: init}
    prev: dict = {}
    h_cache = {source: heuristic(source)}
    queue = LazyMinHeap()
    push = queue.push
    pop = queue.pop
    push(source, init + h_cache[source])
    settled = 0
    relaxed = 0
    order = [] if record else None
    while True:
        try:
            u, f = pop()
        except IndexError:
            break
        g_u = dist[u]
        if f > g_u + h_cache[u]:
            continue
        settled += 1
        if order is not None:
            order.append(u)
        if u == target:
            nodes, edges = trace_back(prev, source, target)
            return SearchResult(True, g_u, nodes, edges, settled, relaxed, order, None, dist)
        for eid, v in out_edges(u):
            if v in banned_nodes or eid in banned_edges:
                continue
            relaxed += 1
            nd = g_u + weight(eid, g_u)
            old = dist.get(v)
            if old is None or nd < old:
                hv = h_cache.get(v)
                if hv is None:
                    hv = heuristic(v)
                    h_cache[v] = hv
                f_new = nd + hv
                if hv == INF or f_new > cost_limit:
                    continue
                dist[v] = nd
                prev[v] = (u, eid)
                push(v, f_new)
    return SearchResult(False, INF, [], [], settled, relaxed, order, None, dist)

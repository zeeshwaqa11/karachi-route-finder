from src.heap import LazyMinHeap
from src.routing.result import INF, SearchResult
from src.routing.weights import is_time_dependent


def bidirectional_dijkstra(g, source: int, target: int, weight, *, record: bool = False) -> SearchResult:
    if is_time_dependent(weight):
        raise ValueError("bidirectional search needs a static weight: the arrival time at the target is unknown")
    if source == target:
        return SearchResult(True, 0.0, [source], [], 1, 0, [source] if record else None, [] if record else None)

    out_edges = g.out_edges
    in_edges = g.in_edges
    dist_f = {source: 0.0}
    dist_b = {target: 0.0}
    prev_f: dict = {}
    prev_b: dict = {}
    queue_f = LazyMinHeap()
    queue_b = LazyMinHeap()
    queue_f.push(source, 0.0)
    queue_b.push(target, 0.0)
    order_f = [] if record else None
    order_b = [] if record else None
    best = INF
    meeting = None
    settled = 0
    relaxed = 0

    def clean_top(queue, dist):
        while queue:
            node, key = queue.peek()
            if key > dist[node]:
                queue.pop()
            else:
                return key
        return INF

    while True:
        top_f = clean_top(queue_f, dist_f)
        top_b = clean_top(queue_b, dist_b)
        if top_f == INF or top_b == INF or top_f + top_b >= best:
            break
        if top_f <= top_b:
            u, d = queue_f.pop()
            settled += 1
            if order_f is not None:
                order_f.append(u)
            for eid, v in out_edges(u):
                relaxed += 1
                nd = d + weight(eid, d)
                old = dist_f.get(v)
                if old is None or nd < old:
                    dist_f[v] = nd
                    prev_f[v] = (u, eid)
                    queue_f.push(v, nd)
                other = dist_b.get(v)
                if other is not None and nd + other < best:
                    best = nd + other
                    meeting = v
        else:
            v, d = queue_b.pop()
            settled += 1
            if order_b is not None:
                order_b.append(v)
            for eid, u in in_edges(v):
                relaxed += 1
                nd = d + weight(eid, d)
                old = dist_b.get(u)
                if old is None or nd < old:
                    dist_b[u] = nd
                    prev_b[u] = (v, eid)
                    queue_b.push(u, nd)
                other = dist_f.get(u)
                if other is not None and nd + other < best:
                    best = nd + other
                    meeting = u

    if meeting is None:
        return SearchResult(False, INF, [], [], settled, relaxed, order_f, order_b)

    nodes = [meeting]
    edges: list[int] = []
    node = meeting
    while node != source:
        node, eid = prev_f[node]
        nodes.append(node)
        edges.append(eid)
    nodes.reverse()
    edges.reverse()
    node = meeting
    while node != target:
        node, eid = prev_b[node]
        nodes.append(node)
        edges.append(eid)
    return SearchResult(True, best, nodes, edges, settled, relaxed, order_f, order_b)

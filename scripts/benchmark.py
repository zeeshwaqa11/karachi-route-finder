import argparse
import datetime as dt
import gc
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import tracemalloc

import numpy as np

from src import config
from src.congestion import CongestionModel
from src.graph import CSRGraph
from src.heap import IndexedMinHeap, LazyMinHeap
from src.planner import RouteRequest, plan_routes
from src.routing import dijkstra as dijkstra_module
from src.routing.astar import astar
from src.routing.bidirectional import bidirectional_dijkstra
from src.routing.dijkstra import dijkstra
from src.routing.weights import distance_weight, free_flow_weight, haversine_heuristic
from src.routing.yen import yen_k_shortest
from src.scc import largest_scc_mask

SECTIONS = ("shortest", "heap", "yen", "engines", "diverse", "scaling", "memory")
YEN_DEPARTURE = ("weekday", 8.5 * 3600.0)


def stats(values) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "median": float(np.median(arr)),
        "p95": float(np.percentile(arr, 95)),
        "mean": float(arr.mean()),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }


def pick_pairs(n_nodes: int, count: int, seed: int) -> list[tuple[int, int]]:
    rng = random.Random(seed)
    pairs = []
    while len(pairs) < count:
        s, t = rng.randrange(n_nodes), rng.randrange(n_nodes)
        if s != t:
            pairs.append((s, t))
    return pairs


def timed(fn, *args, **kwargs):
    gc.collect()
    gc.disable()
    started = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
    finally:
        elapsed = (time.perf_counter() - started) * 1000.0
        gc.enable()
    return result, elapsed


def progress(label: str, i: int, total: int, started: float) -> None:
    if i == total or i % max(1, total // 10) == 0:
        print(f"    {label}: {i}/{total} ({time.perf_counter() - started:.0f}s)", flush=True)


def to_networkx(graph):
    import networkx as nx

    G = nx.DiGraph()
    G.add_nodes_from(range(graph.n))
    lengths = graph.weight_list("length")
    times = graph.weight_list("time")
    for u in range(graph.n):
        for eid, v in graph.out_edges(u):
            G.add_edge(u, v, length=lengths[eid], time=times[eid])
    return G


def bench_shortest(graph, pairs) -> tuple[list[dict], dict]:
    import networkx as nx

    print("  building the NetworkX reference graph (not timed)", flush=True)
    G = to_networkx(graph)
    weights = {"distance": distance_weight(graph), "time": free_flow_weight(graph)}
    nx_keys = {"distance": "length", "time": "time"}
    rows = []
    costs: dict[tuple[str, str], list[float]] = {}
    warm_s, warm_t = pairs[0]
    for wname, weight in weights.items():
        haversine_heuristic(graph, warm_t, weight.per_metre)
        runners = {
            "dijkstra": lambda s, t, w=weight: dijkstra(graph, s, t, w),
            "bidirectional": lambda s, t, w=weight: bidirectional_dijkstra(graph, s, t, w),
            "astar": lambda s, t, w=weight: astar(graph, s, t, w, haversine_heuristic(graph, t, w.per_metre)),
        }
        for algo, run in runners.items():
            print(f"  {algo} / {wname}", flush=True)
            runtimes, settled, relaxed, found = [], [], [], []
            started = time.perf_counter()
            for i, (s, t) in enumerate(pairs, 1):
                res, ms = timed(run, s, t)
                runtimes.append(ms)
                settled.append(res.settled)
                relaxed.append(res.relaxed)
                found.append(res.cost)
                progress(f"{algo}/{wname}", i, len(pairs), started)
            costs[(algo, wname)] = found
            rows.append(
                {
                    "algorithm": algo,
                    "weight": wname,
                    "n": len(pairs),
                    "runtime_ms": stats(runtimes),
                    "settled": stats(settled),
                    "relaxed": stats(relaxed),
                }
            )
        for algo, run in {
            "networkx_dijkstra": lambda s, t, k=nx_keys[wname]: nx.dijkstra_path_length(G, s, t, weight=k),
            "networkx_bidirectional": lambda s, t, k=nx_keys[wname]: nx.bidirectional_dijkstra(G, s, t, weight=k)[0],
        }.items():
            print(f"  {algo} / {wname}", flush=True)
            runtimes, found = [], []
            started = time.perf_counter()
            for i, (s, t) in enumerate(pairs, 1):
                value, ms = timed(run, s, t)
                runtimes.append(ms)
                found.append(value)
                progress(f"{algo}/{wname}", i, len(pairs), started)
            costs[(algo, wname)] = found
            rows.append({"algorithm": algo, "weight": wname, "n": len(pairs), "runtime_ms": stats(runtimes)})
    worst = 0.0
    for wname in weights:
        reference = np.array(costs[("networkx_dijkstra", wname)])
        for algo in ("dijkstra", "bidirectional", "astar", "networkx_bidirectional"):
            other = np.array(costs[(algo, wname)])
            worst = max(worst, float(np.max(np.abs(other - reference) / np.maximum(reference, 1e-9))))
    check = {"pairs": len(pairs), "max_relative_cost_difference_vs_networkx": worst, "all_costs_agree": worst < 1e-9}
    return rows, check


class CountingLazy(LazyMinHeap):
    pushes = 0
    pops = 0

    def push(self, item, priority):
        CountingLazy.pushes += 1
        super().push(item, priority)

    def pop(self):
        CountingLazy.pops += 1
        return super().pop()


class CountingIndexed(IndexedMinHeap):
    pushes = 0
    pops = 0
    decreases = 0

    def push(self, item, priority):
        CountingIndexed.pushes += 1
        super().push(item, priority)

    def pop(self):
        CountingIndexed.pops += 1
        return super().pop()

    def decrease_key(self, item, new_priority):
        CountingIndexed.decreases += 1
        super().decrease_key(item, new_priority)


def bench_heap(graph, pairs, sample: int) -> list[dict]:
    weight = free_flow_weight(graph)
    rows = []
    for strategy in ("lazy", "decrease_key"):
        print(f"  dijkstra with {strategy}", flush=True)
        runtimes, settled = [], []
        started = time.perf_counter()
        for i, (s, t) in enumerate(pairs, 1):
            res, ms = timed(dijkstra, graph, s, t, weight, heap=strategy)
            runtimes.append(ms)
            settled.append(res.settled)
            progress(strategy, i, len(pairs), started)
        rows.append(
            {"strategy": strategy, "weight": "time", "n": len(pairs), "runtime_ms": stats(runtimes), "settled": stats(settled)}
        )
    original = (dijkstra_module.LazyMinHeap, dijkstra_module.IndexedMinHeap)
    dijkstra_module.LazyMinHeap = CountingLazy
    dijkstra_module.IndexedMinHeap = CountingIndexed
    try:
        for row, strategy in zip(rows, ("lazy", "decrease_key")):
            CountingLazy.pushes = CountingLazy.pops = 0
            CountingIndexed.pushes = CountingIndexed.pops = CountingIndexed.decreases = 0
            settled_total = 0
            for s, t in pairs[:sample]:
                settled_total += dijkstra(graph, s, t, weight, heap=strategy).settled
            counter = CountingLazy if strategy == "lazy" else CountingIndexed
            row["operations"] = {
                "sample_pairs": sample,
                "pushes": counter.pushes,
                "pops": counter.pops,
                "decrease_keys": getattr(counter, "decreases", 0),
                "settled": settled_total,
                "stale_pops": counter.pops - settled_total if strategy == "lazy" else 0,
            }
    finally:
        dijkstra_module.LazyMinHeap, dijkstra_module.IndexedMinHeap = original
    return rows


def bench_yen(graph, pairs) -> list[dict]:
    weight = free_flow_weight(graph)
    rows = []
    for k in (1, 3, 5):
        print(f"  yen K={k} (A*, reverse-distance heuristic, plain)", flush=True)
        runtimes, searches, settled, found = [], [], [], []
        started = time.perf_counter()
        for i, (s, t) in enumerate(pairs, 1):
            res, ms = timed(yen_k_shortest, graph, s, t, weight, k, algorithm="astar", heuristic="reverse")
            runtimes.append(ms)
            searches.append(res.spur_searches)
            settled.append(res.settled)
            found.append(len(res.paths))
            progress(f"yen K={k}", i, len(pairs), started)
        rows.append(
            {
                "k": k,
                "algorithm": "astar",
                "heuristic": "reverse",
                "diversity": False,
                "weight": "free_flow_time",
                "n": len(pairs),
                "runtime_ms": stats(runtimes),
                "spur_searches": stats(searches),
                "settled": stats(settled),
                "paths_found": stats(found),
            }
        )
    return rows


def bench_engines(graph, pairs, k: int) -> list[dict]:
    weight = free_flow_weight(graph)
    rows = []
    for algorithm, heuristic in (("dijkstra", "haversine"), ("astar", "haversine"), ("astar", "reverse")):
        label = f"{algorithm}/{heuristic}" if algorithm == "astar" else algorithm
        print(f"  yen K={k} engine {label}", flush=True)
        runtimes, searches, settled = [], [], []
        started = time.perf_counter()
        for i, (s, t) in enumerate(pairs, 1):
            res, ms = timed(yen_k_shortest, graph, s, t, weight, k, algorithm=algorithm, heuristic=heuristic)
            runtimes.append(ms)
            searches.append(res.spur_searches)
            settled.append(res.settled)
            progress(label, i, len(pairs), started)
        rows.append(
            {
                "k": k,
                "engine": label,
                "weight": "free_flow_time",
                "n": len(pairs),
                "runtime_ms": stats(runtimes),
                "spur_searches": stats(searches),
                "settled": stats(settled),
            }
        )
    return rows


def bench_diverse(graph, congestion, pairs) -> list[dict]:
    rows = []
    day, depart = YEN_DEPARTURE
    for k in (3, 5):
        print(f"  diverse routes K={k} (planner defaults, overlap threshold {config.DIVERSITY_THRESHOLD})", flush=True)
        runtimes, searches, settled, found, enumerated, rejected = [], [], [], [], [], []
        started = time.perf_counter()
        for i, (s, t) in enumerate(pairs, 1):
            request = RouteRequest(source=s, target=t, day="Monday", depart_s=depart, k=k)
            res, ms = timed(plan_routes, graph, congestion, request)
            runtimes.append(res.compute_ms)
            searches.append(res.spur_searches)
            settled.append(res.settled)
            found.append(len(res.routes))
            enumerated.append(res.enumerated)
            rejected.append(res.rejected_as_similar)
            progress(f"diverse K={k}", i, len(pairs), started)
        rows.append(
            {
                "k": k,
                "diversity": True,
                "weight": "time_dependent_simulated",
                "threshold": config.DIVERSITY_THRESHOLD,
                "n": len(pairs),
                "runtime_ms": stats(runtimes),
                "spur_searches": stats(searches),
                "settled": stats(settled),
                "paths_found": stats(found),
                "enumerated": stats(enumerated),
                "rejected_as_similar": stats(rejected),
                "share_reaching_k": float(np.mean(np.array(found) >= k)),
            }
        )
    return rows


def sub_area(graph: CSRGraph, centre, radius_m: float):
    lat0, lon0 = centre
    dy = (graph.lat - lat0) * 111194.9
    dx = (graph.lon - lon0) * 111194.9 * math.cos(math.radians(lat0))
    mask = (np.abs(dx) <= radius_m) & (np.abs(dy) <= radius_m)
    if mask.sum() < 50:
        return None
    sub = graph.subgraph(mask)
    return sub.subgraph(largest_scc_mask(sub))


def bench_scaling(graph, sources_per_size: int, seed: int) -> dict:
    centre = (float(np.median(graph.lat)), float(np.median(graph.lon)))
    radii = [1500, 2500, 3500, 5000, 7000, 9500, 13000, 18000, 26000]
    points = []
    last_nodes = 0
    for radius in radii:
        sub = sub_area(graph, centre, radius)
        if sub is None or sub.n == last_nodes:
            continue
        last_nodes = sub.n
        weight = free_flow_weight(sub)
        sub.in_edges(0)
        rng = random.Random(seed)
        runtimes = []
        for _ in range(sources_per_size):
            s = rng.randrange(sub.n)
            res, ms = timed(dijkstra, sub, s, None, weight)
            assert res.settled == sub.n
            runtimes.append(ms)
        e_log_v = sub.m * math.log2(sub.n)
        points.append(
            {
                "radius_m": radius,
                "nodes": sub.n,
                "edges": sub.m,
                "e_log_v": e_log_v,
                "runtime_ms_median": float(np.median(runtimes)),
                "runtime_ms_p95": float(np.percentile(runtimes, 95)),
            }
        )
        print(
            f"    radius {radius} m: {sub.n:,} nodes, {sub.m:,} edges, median {points[-1]['runtime_ms_median']:.1f} ms",
            flush=True,
        )
        if sub.n >= graph.n:
            break
    x = np.log10([p["e_log_v"] for p in points])
    y = np.log10([p["runtime_ms_median"] for p in points])
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "search": "full single-source Dijkstra (no early exit), free-flow time",
        "sources_per_size": sources_per_size,
        "points": points,
        "fit": {"slope": float(slope), "intercept": float(intercept), "r2": 1.0 - ss_res / ss_tot if ss_tot else 1.0},
    }


def bench_memory(graph: CSRGraph, path) -> dict:
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    adjacency = graph.to_adjacency()
    adjacency_bytes = tracemalloc.get_traced_memory()[0] - before
    del adjacency
    gc.collect()
    before = tracemalloc.get_traced_memory()[0]
    fresh = CSRGraph.load(path)
    csr_bytes = tracemalloc.get_traced_memory()[0] - before
    before = tracemalloc.get_traced_memory()[0]
    fresh.weight_list("length")
    fresh.weight_list("time")
    fresh.class_list()
    fresh.coords_lists()
    fresh.out_edges(0)
    fresh.in_edges(0)
    mirrors = tracemalloc.get_traced_memory()[0] - before
    tracemalloc.stop()
    return {
        "nodes": graph.n,
        "edges": graph.m,
        "adjacency_list_bytes": int(adjacency_bytes),
        "csr_bytes": int(csr_bytes),
        "csr_array_nbytes": graph.array_bytes(),
        "csr_python_lists_bytes": int(csr_bytes + mirrors),
        "python_list_mirrors_bytes": int(mirrors),
        "ratio_adjacency_to_csr": adjacency_bytes / max(csr_bytes, 1),
        "adjacency_bytes_per_edge": adjacency_bytes / graph.m,
        "csr_bytes_per_edge": csr_bytes / graph.m,
    }


def library_versions() -> dict:
    import importlib.metadata as md

    return {name: md.version(name) for name in ("numpy", "networkx")}


def git_revision() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=config.ROOT, check=True)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def load_existing(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure the routing algorithms")
    parser.add_argument("--sections", nargs="+", default=list(SECTIONS), choices=SECTIONS)
    parser.add_argument("--pairs", type=int, default=config.BENCH_PAIRS)
    parser.add_argument("--yen-pairs", type=int, default=None, help="defaults to --pairs")
    parser.add_argument("--engine-pairs", type=int, default=5)
    parser.add_argument("--diverse-pairs", type=int, default=60)
    parser.add_argument("--scaling-sources", type=int, default=25)
    parser.add_argument("--seed", type=int, default=config.BENCH_SEED)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    out = config.reports_dir() / "benchmarks.json" if args.output is None else __import__("pathlib").Path(args.output)
    path = config.graph_path()
    if not path.exists():
        sys.exit(f"Graph not built ({path}). Run: python -m scripts.build_graph")
    graph = CSRGraph.load(path)
    graph.weight_list("length")
    graph.weight_list("time")
    graph.in_edges(0)
    congestion = CongestionModel(graph)
    yen_pairs = args.yen_pairs or args.pairs
    all_pairs = pick_pairs(graph.n, max(args.pairs, yen_pairs), args.seed)
    pairs = all_pairs[: args.pairs]
    print(f"Graph: {graph.n:,} nodes, {graph.m:,} edges; sections: {', '.join(args.sections)}", flush=True)

    data = load_existing(out)
    data["meta"] = {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "git_revision": git_revision(),
        "versions": library_versions(),
        "seed": args.seed,
        "pairs": args.pairs,
        "yen_pairs": yen_pairs,
        "engine_pairs": args.engine_pairs,
        "diverse_pairs": args.diverse_pairs,
        "yen_departure": {"day_type": YEN_DEPARTURE[0], "seconds": YEN_DEPARTURE[1]},
        "congestion": "simulated",
        "graph": {
            "area_key": config.area_key(),
            "area_label": graph.meta.get("area_label", config.area_key()),
            "nodes": graph.n,
            "edges": graph.m,
        },
    }

    def save() -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=1), encoding="utf-8")

    for section in args.sections:
        print(f"[{section}]", flush=True)
        started = time.perf_counter()
        if section == "shortest":
            data["shortest_path"], data["correctness"] = bench_shortest(graph, pairs)
        elif section == "heap":
            data["heap_strategy"] = bench_heap(graph, pairs, sample=min(100, len(pairs)))
        elif section == "yen":
            plain = bench_yen(graph, all_pairs[:yen_pairs])
            data["yen"] = [r for r in data.get("yen", []) if r.get("diversity")] + plain
        elif section == "engines":
            data["yen_engines"] = bench_engines(graph, all_pairs[: args.engine_pairs], k=3)
        elif section == "diverse":
            diverse = bench_diverse(graph, congestion, all_pairs[: args.diverse_pairs])
            data["yen"] = [r for r in data.get("yen", []) if not r.get("diversity")] + diverse
        elif section == "scaling":
            data["scaling"] = bench_scaling(graph, args.scaling_sources, args.seed)
        elif section == "memory":
            data["memory"] = bench_memory(graph, path)
        save()
        print(f"[{section}] finished in {time.perf_counter() - started:.0f}s", flush=True)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

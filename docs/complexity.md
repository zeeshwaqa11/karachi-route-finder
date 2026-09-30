# Complexity analysis and measured results

**How to read this page.** Each section states the theoretical complexity and then links it to a measurement. Every number on
this page sits inside a generated block (between `BEGIN`/`END` markers) that `python -m scripts.render_reports` fills from
`reports/benchmarks.json` or from the graph build report. Nothing measured is typed by hand. Prose outside the blocks only
describes what the tables show.

Notation: `V` nodes, `E` directed edges, `K` routes. All algorithms are pure Python, so the constants are large compared with
compiled libraries; the *shape* of the results is what matters.

<!-- BEGIN:bench_meta -->
Measured on 64,420 nodes / 180,594 edges (Central Karachi (Saddar, Clifton, PECHS, Gulshan, Airport corridor)); 500 random origin-destination pairs, seed 20240611; Python 3.12.10 on Windows-11-10.0.26200-SP0 (12 logical CPUs), numpy 2.4.6, networkx 3.6.1; code revision `92ad54a`; run at 2026-09-30T12:29:04+00:00. Every number in the tables below is generated from `reports/benchmarks.json`.
<!-- END:bench_meta -->

## The graph that was measured

<!-- BEGIN:graph_stats -->
| Item | Value |
|---|---|
| Area | Central Karachi (Saddar, Clifton, PECHS, Gulshan, Airport corridor) |
| Nodes (intersections) after cleaning | 64,420 |
| Directed edges after cleaning | 180,594 |
| Downloaded from OpenStreetMap | 65,035 nodes / 182,493 edges |
| Dropped to keep the largest strongly connected component | 615 nodes / 1,577 edges |
| Self-loops dropped | 37 |
| Parallel edges merged into the cheapest | 285 |
| Edges with an imputed (default) speed | 115,453 (63.9%) |
| Edges by road class | motorway 71, trunk 782, primary 3,814, secondary 6,488, tertiary 21,117, residential 148,322 |
| Edges matched to a named busy corridor | Shahrah-e-Faisal 273, M.A. Jinnah Road 186, University Road 188, I.I. Chundrigar Road 30 |
<!-- END:graph_stats -->

## Summary of the theory

| Algorithm | Time | Space | Notes |
|---|---|---|---|
| Binary heap push / pop / `decrease_key` | O(log n) each | O(n) (lazy: O(pushes)) | `decrease_key` needs a position map |
| Dijkstra, binary heap | O((V + E) log V) | O(V) | with lazy deletion the heap holds up to O(E) entries, so the bound is O(E log E) = O(E log V) |
| A* | worst case the same as Dijkstra; with a good heuristic it settles far fewer nodes | O(V) | consistent heuristic: never settles a node Dijkstra would not |
| Bidirectional Dijkstra | worst case O((V + E) log V) | O(V) | two searches each covering roughly half the radius |
| Yen's K shortest paths | O(K · V · (E + V log V)) with a Fibonacci heap; O(K · V · (E + V) log V) with a binary heap | O(K · V) | K rounds, up to V spur searches per round |
| Time-dependent Dijkstra | same as Dijkstra, one interpolation per relaxation | O(V) | valid because the edge functions are FIFO |
| KD-tree build / query | O(n log² n) with per-level sorting / O(log n) average | O(n) | |
| Adjacency list / CSR | O(V + E) space | O(V + E) | different constants, measured below |

## Priority queue: `decrease_key` against lazy deletion

Both variants give O((V + E) log V) Dijkstra. Lazy deletion pushes a duplicate instead of updating an entry, so the heap is larger
and some pops are stale, but no position map has to be maintained. With `decrease_key` the heap stays at most V entries, at the
price of writing the position map on every swap.

<!-- BEGIN:bench_heap -->
| Strategy | Median ms | p95 ms | Heap pushes* | Heap pops* | decrease_key calls* | Stale pops* |
|---|---|---|---|---|---|---|
| lazy | 248.0 | 538.6 | 3,833,732 | 3,788,743 | 0.0 | 618,852 |
| decrease key | 262.9 | 585.9 | 3,206,871 | 3,169,891 | 626,861 | 0.0 |

*Operation counts are totals over the first 100 pairs. Both strategies ran on the same pairs, interleaved and alternating which goes first; the median per-pair ratio of `decrease_key` runtime to lazy runtime is **1.09**.
<!-- END:bench_heap -->

**What this shows.** `decrease_key` performs fewer pushes and pops and never pops a stale entry, yet it is not faster in Python.
Each of its sift steps also writes the position map (a dictionary write), and that extra work per swap outweighs the saving
from a smaller heap. Lazy deletion pushes more entries, but its push and pop are the simplest possible loops. The paired ratio
above is the trustworthy number: absolute times drift between runs on a shared desktop machine (the same code measured
noticeably differently on different occasions), while a ratio taken on interleaved runs cancels most of that drift. In a
compiled language, where the position map is cheap, the balance can tip the other way.


## Single-pair shortest paths: Dijkstra, bidirectional Dijkstra, A*

Dijkstra settles every node closer than the target: on a road network that is a disc of radius `d(s, t)`, so the work grows with
the *area*, roughly quadratically in the trip length. Bidirectional Dijkstra runs two discs of radius about `d/2`, so in the ideal
case it explores about half of the area. A* with a consistent heuristic explores an ellipse elongated towards the target; the
better the heuristic matches the true remaining cost, the thinner the ellipse. The haversine heuristic is a *straight-line*
bound, so it is tight for distance and looser for travel time (the maximum speed in the graph is well above the typical speed).

<!-- BEGIN:bench_shortest -->
| Algorithm | Weight | Median ms | p95 ms | Median nodes settled | p95 nodes settled | Median edges relaxed |
|---|---|---|---|---|---|---|
| Dijkstra | distance | 170.5 | 341.1 | 31,966 | 61,675 | 88,956 |
| Bidirectional Dijkstra | distance | 121.4 | 266.8 | 20,636 | 42,853 | 58,374 |
| A* (haversine) | distance | 43.8 | 156.6 | 6,054 | 20,338 | 17,290 |
| NetworkX Dijkstra (reference) | distance | 95.2 | 280.7 | - | - | - |
| NetworkX bidirectional (reference) | distance | 67.0 | 138.7 | - | - | - |
| Dijkstra | free-flow time | 175.6 | 334.6 | 31,824 | 62,183 | 89,736 |
| Bidirectional Dijkstra | free-flow time | 161.5 | 464.8 | 17,421 | 40,371 | 48,540 |
| A* (haversine) | free-flow time | 174.0 | 549.2 | 15,010 | 43,749 | 42,469 |
| NetworkX Dijkstra (reference) | free-flow time | 136.9 | 264.5 | - | - | - |
| NetworkX bidirectional (reference) | free-flow time | 93.4 | 216.2 | - | - | - |
<!-- END:bench_shortest -->

Relative to plain Dijkstra, and against the NetworkX reference (a C-accelerated `heapq` under the hood):

<!-- BEGIN:bench_ratios -->
| Comparison | Weight | Nodes settled vs Dijkstra (median) | Runtime vs Dijkstra (median) |
|---|---|---|---|
| Bidirectional Dijkstra | distance | 65% | 71% |
| A* (haversine) | distance | 19% | 26% |
| This project's Dijkstra vs NetworkX Dijkstra (runtime) | distance | - | 1.79x |
| Bidirectional Dijkstra | free-flow time | 55% | 92% |
| A* (haversine) | free-flow time | 47% | 99% |
| This project's Dijkstra vs NetworkX Dijkstra (runtime) | free-flow time | - | 1.28x |
<!-- END:bench_ratios -->

**What this shows.** Both improvements cut the number of settled nodes as theory predicts, and A* with the haversine heuristic
cuts it most for the *distance* weight, where the heuristic is exact for a straight road. For *travel time* the heuristic divides
by the fastest speed anywhere in the graph, so it is a looser bound and A* prunes less. Settling fewer nodes does not turn
into the same runtime saving in pure Python, because each settled node under A* also pays for a haversine evaluation and
bidirectional search pays for two heaps and for iterating in-edges; the runtime column is the honest end-to-end picture. The
NetworkX reference uses a C implementation of the heap; the ratio shows how much of this project's cost is interpreter
overhead rather than the algorithm. The path costs of all implementations are identical (line below), so these are pure
speed and effort differences.


<!-- BEGIN:bench_correctness -->
On the 500 benchmark pairs, every implementation returned the same path cost as NetworkX (largest relative difference 1.8e-15; all agree: True).
<!-- END:bench_correctness -->

## Yen's K-shortest paths

Yen's algorithm runs up to one spur search for every node of the previous path in each of the `K - 1` rounds. Each spur search is a
shortest-path search, so the bound is `K · V · (cost of one search)`. Two things make the practical cost far smaller than the
bound: the path has far fewer than `V` nodes, and Lawler's improvement skips spur nodes that would only regenerate known
candidates. The choice of search inside Yen's matters a lot: plain Dijkstra restarts from scratch each time, A* with the
haversine heuristic prunes a little, and A* with the exact reverse-distance heuristic (one backward search per query) prunes
almost everything when the weight is static.

Plain Yen's with static free-flow time:

<!-- BEGIN:bench_yen -->
| K | Pairs | Median ms | p95 ms | Median searches | Median nodes settled |
|---|---|---|---|---|---|
| 1 | 500 | 296.9 | 358.5 | 1 | 121 |
| 3 | 500 | 377.8 | 1,239 | 176 | 14,010 |
| 5 | 500 | 389.3 | 1,997 | 269 | 19,732 |

| Search inside Yen's (K = 3) | Pairs | Median ms | Median searches | Median nodes settled |
|---|---|---|---|---|
| dijkstra | 3 | 23,117 | 251 | 2,368,447 |
| astar/haversine | 3 | 10,131 | 251 | 875,330 |
| astar/reverse | 3 | 836.8 | 251 | 35,572 |
<!-- END:bench_yen -->

**What this shows.** The search used inside Yen's decides whether the algorithm is usable. Plain Dijkstra restarts a search from
scratch for every spur node and settles millions of nodes per query. A* with the haversine heuristic helps, but the exact
reverse-distance heuristic (one backward search, then every spur search is guided by exact distances) settles orders of
magnitude fewer nodes for the same number of spur searches. That is why the application uses it. The runtime of plain Yen's
grows slowly with K for the median pair because the single backward search dominates, while the 95th percentile grows with K
because long paths have many spur nodes. With the *time-dependent* weight the reverse heuristic is only a lower bound (it
ignores congestion), so it prunes far less; the application-level table below is measured with that weight.


The application's diverse-route search (time-dependent simulated congestion, diversity filter with rejoin window, spur stride and
cost bound, `K` routes at overlap threshold 0.7):

<!-- BEGIN:bench_diverse -->
| K | Pairs | Median ms | p95 ms | Median routes found | Pairs reaching K routes | Median candidate paths enumerated | Median rejected as too similar |
|---|---|---|---|---|---|---|---|
| 3 | 60 | 1,430 | 4,913 | 3 | 100% | 4 | 2 |
| 5 | 60 | 1,248 | 7,610 | 5 | 100% | 12 | 8 |
<!-- END:bench_diverse -->

**What this shows.** With the rejoin window, spur stride and cost bound switched on, the diversity search reached the requested
number of diverse routes on every sampled pair, each within the cost bound of the fastest, in a couple of seconds at the median.
This is a heuristic candidate generator (see `docs/algorithms.md`, section 6): it does not prove that no other diverse route
exists.


## Scaling with graph size

If the measured cost is `Θ(E log V)`, then plotting runtime against `E log₂ V` on log-log axes gives a straight line with slope
about 1. The measurement uses full single-source Dijkstra (no early exit, so every node is settled and the work is exactly the
theoretical quantity) on nested square sub-areas of the city, each reduced to its largest strongly connected component.

<!-- BEGIN:bench_scaling -->
| Half-width km | Nodes V | Edges E | E log2 V | Median full-search ms |
|---|---|---|---|---|
| 1.5 | 1,480 | 3,852 | 40,567 | 4.3 |
| 2.5 | 4,394 | 11,679 | 141,331 | 15.5 |
| 3.5 | 8,492 | 22,905 | 298,954 | 29.8 |
| 5.0 | 17,541 | 48,320 | 681,237 | 65.3 |
| 7.0 | 33,859 | 93,852 | 1,412,215 | 136.2 |
| 9.5 | 61,423 | 172,220 | 2,739,416 | 293.9 |
| 13.0 | 64,420 | 180,594 | 2,885,029 | 295.9 |

Log-log least-squares fit of runtime against E log2 V over 7 graph sizes (25 random sources each): slope **0.99**, R² 0.999.
<!-- END:bench_scaling -->

**What this shows.** The fitted slope is close to 1, which is what `Θ(E log V)` predicts when runtime is plotted against
`E log₂ V`. The two largest rows are almost the same graph (the box already covers the whole area), so they mainly show the
measurement noise floor. Small graphs fit in CPU caches, which is why the smallest points can sit slightly below the line.


![Runtime against E log V](../reports/figures/scaling_loglog.png)

## Space: adjacency list against CSR

An adjacency list stores one Python object per edge (object header, boxed floats, a tuple in the per-node list). CSR stores
`V + 1` offsets, `E` targets and one flat numpy array per attribute, so its size is the sum of the array sizes. The pure-Python
search reads Python-list mirrors of the CSR arrays because element access on a numpy array is slow, and those mirrors are counted
in the third row.

<!-- BEGIN:bench_memory -->
| Representation | MiB | Bytes per edge |
|---|---|---|
| Adjacency list (one Python object per edge) | 92.2 | 535 |
| CSR, numpy arrays only (what is stored on disk and kept in memory) | 8.6 | 50 |
| CSR plus the Python-list mirrors the pure-Python search reads | 50.5 | 293 |

The adjacency list needs **10.7x** the memory of the numpy CSR arrays on the same 64,420-node, 180,594-edge graph (measured with `tracemalloc`).
<!-- END:bench_memory -->

**What this shows.** Storing one Python object per edge costs roughly an order of magnitude more memory than flat numpy
arrays. The pure-Python search needs list mirrors of the arrays (the third row), which gives back part of the saving, but the
mirrors are built once, are read-only, and the compact form is what is stored on disk and loaded in a fraction of a second.


## Time-dependent search and the FIFO check

A time-dependent search evaluates one interpolation per relaxed edge, so its asymptotic cost is that of Dijkstra. FIFO is
verified when the congestion model is built (see `docs/algorithms.md`, section 8):

<!-- BEGIN:fifo -->
| Profile | Worst slope ratio (must be at most 1) |
|---|---|
| weekday | 0.0343 |
| weekend | 0.0140 |

The ratio is the largest, over all edges and road classes, of `free-flow time x corridor factor x largest per-slot multiplier drop / 900 s`.
<!-- END:fifo -->

The worst slope ratio is far below the limit of 1, so the shipped profile satisfies FIFO with a wide margin even on the
longest edge in the graph. `tests/test_congestion.py` also shows the check firing for a deliberately steep profile.


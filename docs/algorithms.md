# Algorithms and correctness arguments

Everything in `src/` is written from scratch. NetworkX and OSMnx are used only to download or convert map data
(`src/osm_download.py`) and, inside `tests/` and `scripts/benchmark.py`, as a reference oracle. A test
(`tests/test_purity.py`) fails if anything under `src/routing/` imports NetworkX.

## 1. The graph

* **Nodes** are OSM intersections with latitude and longitude. **Edges** are directed (one-way streets are respected) and carry
  `length` (metres), `time` (free-flow seconds, `length / speed`), a road class, an optional road name and the interior geometry
  used for drawing.
* **One edge per ordered node pair.** OSM often has several parallel edges between the same two intersections. They are merged:
  the merged edge takes the *lowest length* and the *lowest free-flow time* among the parallels (the "cheapest for each weight
  type"), and the attributes and geometry of the fastest one. Because both minima are kept, a route optimised for distance and a
  route optimised for time each see the cheapest option. The number of merged edges is reported by `scripts/build_graph.py`.
* **Edge length is clamped** so that it is never shorter than the great-circle distance between the edge's endpoints. Real OSM
  lengths already satisfy this; the clamp removes floating-point and data-error exceptions and is what makes the A* heuristic
  provably consistent (section 4).
* **Strong connectivity.** Only the largest strongly connected component is kept (own iterative Tarjan in `src/scc.py`, checked
  against NetworkX in the tests), so every node can reach every other node.
* **Speeds.** `maxspeed` is used when it parses to a sane value; otherwise a default speed for the road class from
  `src/config.py` is used and the edge is flagged as imputed.

### Adjacency list versus CSR

| | Adjacency list (`AdjacencyGraph`) | CSR (`CSRGraph`) |
|---|---|---|
| Layout | one Python `Edge` object per edge plus a list of `(edge id, head)` pairs per node | `offsets[V+1]`, `targets[E]` and one numpy array per attribute |
| Adding an edge | O(1) | needs a rebuild (arrays are immutable in practice) |
| Iterating out-edges of *u* | O(deg u) | O(deg u), a contiguous slice |
| Memory | one object header, several boxed floats and a tuple per edge | 4 to 8 bytes per attribute per edge |
| Disk | needs pickling | `np.savez_compressed`, loads in well under a second |

CSR is the canonical storage. The pure-Python searches read plain Python lists (`tolist()` mirrors created lazily) because
indexing a numpy array element by element is slower than indexing a list; the memory cost of those mirrors is measured
separately in `docs/complexity.md`. Both classes expose the same interface (`out_edges`, `in_edges`, `weight_list`, ...) and the
tests run the algorithms on both.

## 2. Priority queues (`src/heap.py`)

Two binary min-heaps, both written from scratch:

* `IndexedMinHeap` keeps a position map (`item -> array index`) so that `decrease_key(item, p)` finds the item in O(1) and sifts
  it up in O(log n). Each item is in the heap at most once.
* `LazyMinHeap` allows duplicates. Dijkstra pushes a new entry whenever it improves a label and skips stale entries when they
  are popped (`if d > dist[u]: continue`). The heap can grow to O(E) entries instead of O(V).

Both are tested against `heapq` and a reference model with Hypothesis on random operation sequences. Which is faster inside
Dijkstra in Python is a *measured* question, answered in `docs/complexity.md`; the reasoning is that the indexed heap does extra
dictionary writes on every sift step, while lazy deletion only pays for the extra pushes and pops.

## 3. Dijkstra

Single pair with early exit: stop when the target is popped (settled). Correctness is the usual argument: with non-negative
weights the first time a node is popped its label is final. The result carries the path, the cost, the number of **nodes
settled** (non-stale pops) and the number of **edges relaxed** (edges examined). `target=None` runs to exhaustion (used for the
scaling benchmark). Removed nodes and edges (`banned_nodes`, `banned_edges`), an initial label (`init`) and a cost limit
(`cost_limit`) are supported because Yen's algorithm needs them.

All searches take a weight function `weight(edge_id, label) -> cost`, so the same code handles distance, free-flow time,
time-dependent time and a linear combination of static costs.

## 4. A*

**Heuristic.** `h(u) = haversine(u, target) * c` where `c` is a lower bound on cost per metre of straight-line distance:

* distance weight: `c = 1`,
* free-flow time weight: `c = 1 / v_max`, where `v_max` is the **maximum** edge speed in the graph,
* time-dependent time: the same `c` as free-flow, because every multiplier is at least 1.

**Admissible.** Let `P` be any path from `u` to the target with edges `e_1..e_m`. Its length is at least the great-circle
distance: `sum len(e_i) >= haversine(u, t)` by the triangle inequality on the sphere, applied edge by edge, and each edge length
is clamped to be at least the great-circle distance of its endpoints. Its time is `sum len(e_i)/v_i >= sum len(e_i)/v_max >=
haversine(u, t)/v_max = h(u)`. So `h(u)` never exceeds the true remaining cost. With multipliers `>= 1` the same holds for the
time-dependent cost.

**Consistent.** For an edge `(u, v)`: `h(u) = c * hav(u, t) <= c * (hav(u, v) + hav(v, t))` (triangle inequality) `<= c *
len(u, v) + h(v) <= w(u, v) + h(v)`, because `c * len(u, v)` is a lower bound of the edge cost by the same argument as above. A
consistent heuristic means a node is final the first time it is settled and f-values never decrease along a path, so A* settles a
subset of the nodes Dijkstra settles.

**Why admissibility matters.** `tests/test_shortest_paths.py::test_inadmissible_heuristic_can_return_a_worse_path` builds a
small map with a slow direct road and a longer fast road. Dividing the haversine distance by a *slow* speed (10 km/h)
overestimates the remaining time on the fast road, A* pops the direct road's target first and returns the slow path, while
Dijkstra and the correct heuristic return the fast one. A second test shows the same effect on a city-like grid: the biased
search is never better and is sometimes strictly worse.

The implementation uses lazy deletion and re-pushes a node whenever a strictly better label is found, so it stays correct even
for admissible-but-inconsistent heuristics. A search can also be bounded with `cost_limit`.

### The reverse-distance heuristic used inside Yen's

Yen's algorithm runs many searches to the *same* target. Before the first search, one backward Dijkstra from the target computes
`d_lb(u)`, the exact distance to the target under the weight's **static lower bound** (the weight itself for static weights, the
free-flow time for the time-dependent weight). `h(u) = d_lb(u)` is admissible because the real cost of any path is at least its
lower-bound cost. It is consistent because `d_lb` is a shortest-path distance for a weight that is at most the real weight.
Removing nodes and edges in later spur searches can only increase true distances, so the heuristic stays admissible and
consistent for every spur search. For static weights it is exact, which is why Yen's is so much cheaper with it (measured).

## 5. Bidirectional Dijkstra

Two searches run at once, forward from the source on out-edges and backward from the target on in-edges (which is why the
graph classes expose `in_edges`). Let `mu` be the cost of the best source-to-target path seen so far: every time either side
relaxes an edge into a node the other side has a label for, `mu = min(mu, d_f + w + d_b)`.

**Stopping condition:** stop when `top_f + top_b >= mu`, where `top_f` and `top_b` are the smallest keys in the two frontiers.
Proof sketch: any path not yet discovered has a node `x` on the "unsettled boundary"; the path's cost is at least
`d_f(x) + d_b(x)` for some node with `d_f >= top_f` on the forward part and `d_b >= top_b` on the backward part, hence at least
`top_f + top_b >= mu`, so it cannot beat `mu`.

**Why stopping at the first meeting node is wrong.** The first node reached by both searches is a meeting point, not
necessarily on the shortest path. `tests/test_shortest_paths.py::test_stopping_at_the_first_meeting_node_is_wrong` builds a
five-node graph where the two searches first meet on a path of cost 10 while a path of cost 3 exists through nodes that the
frontiers have not reached yet. A naive implementation returns 10; the implementation here returns 3.

Bidirectional search needs a static weight: the backward search does not know the clock time at which the target will be
reached, so a time-dependent weight is rejected with a `ValueError`.

## 6. Yen's K shortest loopless paths (`src/routing/yen.py`)

1. Find the shortest path `A_1`.
2. To get `A_k`, take `A_{k-1}` and, for every node `i` on it except the target, treat `A_{k-1}[0..i]` as the **root path** and
   node `i` as the **spur node**. Remove (a) the next edge of every already found path that shares this root and (b) every
   node of the root path except the spur node, then find the shortest **spur path** from the spur node to the target. The root
   plus the spur path is a candidate. Removing the root nodes guarantees the result has no loop.
3. The cheapest candidate becomes `A_k`.

With a time-dependent weight the spur search starts with the label `init = cost(root)`, i.e. the clock time at which the spur node
is reached. Under FIFO (section 8) the best spur path for a fixed root is well defined, so the argument that the cheapest
candidate is the next shortest path still holds. `tests/test_congestion.py` checks this against brute-force enumeration of all
simple paths under time-dependent costs, and `tests/test_yen.py` checks the first K costs against
`networkx.shortest_simple_paths` on random graphs.

**Lawler's improvement.** A candidate remembers the spur index where it left its parent. Spur nodes before that index would
regenerate candidates that are already queued, so only spur nodes from that index onward are searched. This is exact.

### Diversity filter

Road networks are full of near-identical alternatives: the same route with one block detoured. The similarity of two routes is
the **length-weighted Jaccard** index of their edge sets: `sum(len(shared edges)) / sum(len(edges in either route))`. A candidate
is rejected if its similarity with an *already accepted* route exceeds `DIVERSITY_THRESHOLD` (0.7 by default, adjustable in the
app). Rejected paths are still used as parents for further spur searches, otherwise the enumeration would stop being complete.
The loop ends when `K` diverse routes are accepted or a limit on enumerated paths is reached.

**What happens on a real road network.** A filter alone is not enough: the number of near-duplicates of the fastest route is
combinatorial (every junction offers a small detour, and detours combine), so plain Yen's enumerates a huge number of paths that
are all rejected before it reaches a genuinely different corridor. `tests/test_yen_diverse.py` compares the two approaches on a
city-like grid. To make the diversity search practical, three additions are switched on when the filter is active, all of them
only ever *restricting* which candidates are generated:

1. **Rejoin window.** A spur path may not touch the next `f` fraction (by length) of its parent route. If a candidate replaces
   a stretch of `f` of the parent and is about as long as it, its similarity to the parent is `(1 - f) / (1 + f)`; choosing
   `f = (1 - theta) / (1 + theta)` makes that at most `theta`, so every generated candidate is already diverse from its parent.
2. **Spur stride.** Spur nodes are sampled every `f / 4` of the parent's length instead of at every node; neighbouring spur
   nodes would find almost the same candidate.
3. **Cost bound.** Candidates costing more than `ALTERNATIVE_COST_RATIO` times the best are never worth showing, so searches
   stop at that bound (this also stops failed spur searches from exhausting the whole graph).

With the window, stride and bound switched off (the defaults of `yen_k_shortest`) the function is exact Yen's, which is what the
correctness tests use. The window/stride/bound variant is a heuristic *candidate generator*: it can miss some diverse routes, and
it is described as such in the README.

## 7. Ranking

Each candidate route gets distance, estimated time at the chosen departure and a congestion level. The combined cost is
`w_time * t/t_best + w_distance * d/d_best + w_congestion * m/m_best`, where each measure is divided by the best value among
the candidates (so each term is at least 1 and dimensionless) and `m` is the length-weighted average congestion multiplier. The
weights are normalised to sum to 1. Labels "Fastest", "Shortest" and "Least congested" are attached to whichever route is best
on that single measure.

## 8. Time-dependent congestion and the FIFO property

Congestion is **simulated**. The multiplier for road class `c` at clock time `tau` is

`m_c(tau) = 1 + s_c * (base(tau) - 1)`

where `base` is a piecewise-linear daily curve (different for weekdays and weekends, anchor points in `src/config.py`) sampled
at the start of each 15-minute slot, and `s_c` is a per-class sensitivity. Between slot starts the multiplier is linearly
interpolated (with wrap-around at midnight). Edges on named corridors are multiplied by an extra assumed factor. The cost of
edge `e` entered at clock time `tau` is `T_e * corridor_e * m_c(tau)`, where `T_e` is the free-flow time.

**FIFO (first in, first out).** Leaving later must never get you there earlier. Arrival time at the end of an edge is
`A(tau) = tau + c(tau)`. FIFO holds iff `A` is non-decreasing. On a slot, `c` is linear with slope
`T_e * corridor_e * (m_{k+1} - m_k) / 900 s`, so `A'(tau) = 1 + T_e * corridor_e * (m_{k+1} - m_k) / 900`. This is at least 0 if
and only if `T_e * corridor_e * (m_k - m_{k+1}) <= 900` for every slot, i.e. the largest per-slot *drop* of the multiplier times
the edge's worst-case free-flow time must not exceed one slot length. `CongestionModel` evaluates exactly this ratio for the worst
edge and every road class when it is built and raises an error if it exceeds 1 (the measured value for the shipped profile is in
`docs/complexity.md`). Piecewise-linear interpolation keeps `A` continuous, so a non-negative slope on every piece is enough.
Because `A` is non-decreasing on each edge and a composition of non-decreasing functions is non-decreasing, the earliest
arrival at a node is monotone in the departure time, and Dijkstra with labels equal to elapsed time is exact.
`tests/test_congestion.py` tests the property on sampled edges and departure times, checks that a profile that violates it is
rejected, and compares the search with an independent label-correcting oracle.

**Consequences of simulated numbers.** Multipliers below 1 are rejected (free-flow time is then a lower bound, which A* needs),
and the profile, sensitivities and corridor factors are assumptions, not measurements.

## 9. Nearest-node search (`src/spatial.py`)

A KD-tree over locally projected coordinates (equirectangular around the mean latitude, accurate to well under a metre at city
scale). Leaves hold up to eight points; the split axis is the one with the larger spread; the query descends to the nearer side
first and visits the far side only if the splitting plane is closer than the best point so far. The test suite checks it against
brute force on random points and on graph nodes. Points farther than 300 m from the nearest node trigger a warning in the app;
points farther than 2 km are refused.

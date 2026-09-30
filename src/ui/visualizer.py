import time

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import config
from src.routing.astar import astar
from src.routing.bidirectional import bidirectional_dijkstra
from src.routing.dijkstra import dijkstra
from src.routing.weights import distance_weight, free_flow_weight, haversine_heuristic
from src.ui.common import Resources, add_endpoint_markers, add_legend, bounds_of, new_map
from src.ui.points import PLACE_NAMES, place_point, snap_or_report

WEIGHT_CHOICES = {"Free-flow travel time": "time", "Distance": "distance"}
FORWARD = "#0072B2"
BACKWARD = "#E69F00"
DIJKSTRA = "#D55E00"
ASTAR = "#009E73"


def _timed(fn):
    started = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - started) * 1000.0


def _points_layer(graph, nodes, colour: str) -> folium.GeoJson | None:
    if not nodes:
        return None
    step = max(1, -(-len(nodes) // config.MAX_MAP_EXPLORED_POINTS))
    lat, lon = graph.lat_list(), graph.lon_list()
    feature = {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "MultiPoint", "coordinates": [[lon[n], lat[n]] for n in nodes[::step]]},
    }
    marker = folium.CircleMarker(radius=2, color=colour, weight=0, fill=True, fill_color=colour, fill_opacity=0.75)
    return folium.GeoJson(feature, marker=marker)


def _map(res: Resources, runs: dict, key: str, bounds) -> folium.Map:
    run = runs[key]
    graph = res.graph
    fmap = new_map(graph, bounds)
    if key == "bidirectional":
        layers = [(run["explored"], FORWARD), (run["explored_backward"], BACKWARD)]
        legend = [(FORWARD, "settled from the pickup"), (BACKWARD, "settled from the destination")]
    else:
        colour = DIJKSTRA if key == "dijkstra" else ASTAR
        layers = [(run["explored"], colour)]
        legend = [(colour, "settled nodes")]
    for nodes, colour in layers:
        layer = _points_layer(graph, nodes, colour)
        if layer is not None:
            layer.add_to(fmap)
    folium.PolyLine(graph.path_polyline(run["edges"]), color="#111111", weight=4, opacity=0.9).add_to(fmap)
    add_endpoint_markers(fmap, runs["start"], runs["end"])
    add_legend(fmap, [*legend, ("#111111", "shortest path")])
    return fmap


def _run(res: Resources, source: int, target: int, weight_key: str) -> dict:
    graph = res.graph
    weight = free_flow_weight(graph) if weight_key == "time" else distance_weight(graph)
    heuristic = haversine_heuristic(graph, target, weight.per_metre)
    d, d_ms = _timed(lambda: dijkstra(graph, source, target, weight, record=True))
    b, b_ms = _timed(lambda: bidirectional_dijkstra(graph, source, target, weight, record=True))
    a, a_ms = _timed(lambda: astar(graph, source, target, weight, heuristic, record=True))
    lat, lon = graph.lat_list(), graph.lon_list()
    runs = {"start": (lat[source], lon[source]), "end": (lat[target], lon[target]), "weight": weight_key}
    for key, result, ms in (("dijkstra", d, d_ms), ("bidirectional", b, b_ms), ("astar", a, a_ms)):
        runs[key] = {
            "found": result.found,
            "cost": result.cost,
            "settled": result.settled,
            "relaxed": result.relaxed,
            "ms": ms,
            "edges": result.edges,
            "explored": result.explored or [],
            "explored_backward": result.explored_backward or [],
        }
    return runs


def _summary(runs: dict) -> pd.DataFrame:
    labels = {"dijkstra": "Dijkstra", "bidirectional": "Bidirectional Dijkstra", "astar": "A*"}
    base = max(runs["dijkstra"]["settled"], 1)
    is_time = runs["weight"] == "time"
    rows = []
    for key, label in labels.items():
        run = runs[key]
        rows.append(
            {
                "Algorithm": label,
                "Nodes settled": run["settled"],
                "Edges relaxed": run["relaxed"],
                "Settled vs Dijkstra": f"{run['settled'] / base:.0%}",
                "Time (ms)": round(run["ms"], 1),
                "Path cost": f"{run['cost'] / 60:.2f} min" if is_time else f"{run['cost'] / 1000:.3f} km",
            }
        )
    return pd.DataFrame(rows)


def render(res: Resources) -> None:
    st.header("Algorithm visualizer")
    st.write(
        "The same trip solved by three algorithms. Each dot is a road-network node the algorithm had to settle "
        "(finalise) before it could prove the path optimal. All three return the same cost; they differ in how much of the map they explore."
    )
    shared = st.session_state.get("shared_points")
    use_shared = False
    if shared and shared[0] and shared[1]:
        use_shared = st.checkbox("Use the points chosen on the Find routes page", value=True, key="viz_use_shared")
    if use_shared:
        pickup, dest = shared
        st.caption(f"{pickup[2]} → {dest[2]}")
    else:
        c1, c2 = st.columns(2)
        a = c1.selectbox("Pickup", PLACE_NAMES, index=1, key="viz_pickup")
        b = c2.selectbox("Destination", PLACE_NAMES, index=5, key="viz_dest")
        pickup, dest = place_point(a), place_point(b)
    weight_label = st.radio("Edge cost", list(WEIGHT_CHOICES), horizontal=True, key="viz_weight")
    st.caption(
        "Static costs are used here because bidirectional search needs the arrival time at the destination, "
        "which time-dependent congestion makes unknown."
    )
    if st.button("Run the three algorithms", type="primary", key="viz_go"):
        source = snap_or_report(res, pickup, "pickup")
        target = snap_or_report(res, dest, "destination")
        if source is not None and target is not None:
            with st.spinner("Running Dijkstra, bidirectional Dijkstra and A*..."):
                st.session_state["viz_runs"] = _run(res, source.node, target.node, WEIGHT_CHOICES[weight_label])
    runs = st.session_state.get("viz_runs")
    if not runs:
        return
    if not runs["dijkstra"]["found"]:
        st.error("No route exists between these two points.")
        return
    st.dataframe(_summary(runs), hide_index=True, use_container_width=True)
    lat, lon = res.graph.lat_list(), res.graph.lon_list()
    every = runs["dijkstra"]["explored"] + runs["bidirectional"]["explored"] + runs["bidirectional"]["explored_backward"]
    bounds = bounds_of([(lat[n], lon[n]) for n in every[:: max(1, len(every) // 400)]] + [runs["start"], runs["end"]])
    columns = st.columns(3)
    for column, (key, title) in zip(
        columns,
        (("dijkstra", "Dijkstra"), ("bidirectional", "Bidirectional Dijkstra"), ("astar", "A*")),
    ):
        with column:
            run = runs[key]
            shown = run["settled"]
            st.markdown(f"**{title}** · {shown:,} nodes settled")
            st_folium(
                _map(res, runs, key, bounds), key=f"viz_map_{key}", height=420, use_container_width=True, returned_objects=[]
            )
    st.caption(f"At most {config.MAX_MAP_EXPLORED_POINTS:,} dots are drawn per map (evenly thinned); the counts above are exact.")

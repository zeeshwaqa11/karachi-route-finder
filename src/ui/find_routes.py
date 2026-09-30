import datetime as dt

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src import config
from src.planner import RouteRequest, plan_routes
from src.ranking import rank_routes
from src.ui.common import (
    ROUTE_COLOURS,
    Resources,
    add_endpoint_markers,
    add_legend,
    bounds_of,
    new_map,
)
from src.ui.points import choose_points, snap_or_report

ALGORITHMS = {
    "A* (reverse-distance heuristic)": ("astar", "reverse"),
    "A* (haversine heuristic)": ("astar", "haversine"),
    "Dijkstra": ("dijkstra", "haversine"),
}
RESULT_KEY = "fr_result"


def _weights_ui() -> dict:
    st.markdown("**Ranking weights**")
    defaults = config.DEFAULT_ROUTE_WEIGHTS
    return {
        "time": st.slider("Estimated time", 0.0, 1.0, defaults["time"], 0.05, key="fr_w_time"),
        "distance": st.slider("Distance", 0.0, 1.0, defaults["distance"], 0.05, key="fr_w_distance"),
        "congestion": st.slider("Congestion", 0.0, 1.0, defaults["congestion"], 0.05, key="fr_w_congestion"),
    }


def _departure_ui() -> tuple[str, float]:
    day = st.selectbox("Departure day", config.DAYS, index=0, key="fr_day")
    when = st.time_input("Departure time", value=dt.time(8, 30), step=900, key="fr_time")
    return day, when.hour * 3600.0 + when.minute * 60.0 + when.second


def _route_map(res: Resources, routes, start, end) -> folium.Map:
    polylines = [res.graph.path_polyline(r.path.edges) for r in routes]
    points = [pt for line in polylines for pt in line]
    fmap = new_map(res.graph, bounds_of(points))
    order = sorted(range(len(routes)), key=lambda i: -routes[i].rank)
    for i in order:
        route = routes[i]
        colour = ROUTE_COLOURS[(route.rank - 1) % len(ROUTE_COLOURS)]
        best = route.rank == 1
        tip = f"#{route.rank} {route.label_text}: {route.distance_km:.1f} km, {route.time_min:.0f} min, {route.metrics.level} congestion"
        if best:
            folium.PolyLine(polylines[i], color="#111111", weight=11, opacity=0.55).add_to(fmap)
        folium.PolyLine(polylines[i], color=colour, weight=7 if best else 5, opacity=1.0 if best else 0.8, tooltip=tip).add_to(
            fmap
        )
    add_endpoint_markers(fmap, start, end)
    entries = [
        (
            ROUTE_COLOURS[(r.rank - 1) % len(ROUTE_COLOURS)],
            f"#{r.rank} {r.label_text}" + (" (best)" if r.rank == 1 else ""),
        )
        for r in routes
    ]
    add_legend(fmap, entries, "Routes (simulated traffic)")
    return fmap


def _table(routes) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Rank": [r.rank for r in routes],
            "Route": [r.label_text for r in routes],
            "Distance (km)": [round(r.distance_km, 2) for r in routes],
            "Est. time (min)": [round(r.time_min, 1) for r in routes],
            "Free-flow (min)": [round(r.metrics.free_flow_s / 60.0, 1) for r in routes],
            "Congestion": [r.metrics.level for r in routes],
            "Avg. multiplier": [round(r.metrics.avg_multiplier, 2) for r in routes],
            "Score (lower is better)": [round(r.score, 3) for r in routes],
        }
    )


def _render_result(res: Resources, result: dict, weights: dict) -> None:
    response = result["response"]
    routes = rank_routes(response.candidates, weights)
    if not routes:
        st.error("No route exists between these two points in the loaded road network.")
        return
    st.subheader("Routes")
    if not response.found_all:
        st.warning(
            f"Only {len(routes)} sufficiently different route(s) were found out of the {response.requested_k} requested "
            f"(search stopped after {response.enumerated} candidate paths; {response.rejected_as_similar} were too similar to an accepted route)."
        )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Computation time", f"{response.compute_ms:.0f} ms")
    m2.metric("Nodes settled", f"{response.settled:,}", help=result["algorithm_label"])
    m3.metric("Search runs (Yen)", f"{response.spur_searches:,}")
    m4.metric("Rejected as too similar", f"{response.rejected_as_similar:,}")
    st.dataframe(_table(routes), hide_index=True, use_container_width=True)
    fmap = _route_map(res, routes, result["start"], result["end"])
    st_folium(fmap, key="fr_result_map", height=560, use_container_width=True, returned_objects=[])
    st.caption(
        f"Departure {result['day']} {result['depart_label']} ({result['day_type']} profile). "
        "Congestion level = length-weighted average multiplier over the route. Estimates from simulated traffic."
    )


def render(res: Resources) -> None:
    st.header("Find routes")
    pickup, dest = choose_points(res, "fr")
    with st.expander("Trip settings", expanded=True):
        left, right = st.columns(2)
        with left:
            day, depart_s = _departure_ui()
            k = st.slider("Number of routes (K)", 1, 5, 3, key="fr_k")
            algo_label = st.radio("Search algorithm inside Yen's", list(ALGORITHMS), horizontal=True, key="fr_algo")
        with right:
            weights = _weights_ui()
        similarity = st.slider(
            "Diversity: reject a route if it shares more than this fraction of its length with a better route",
            0.3,
            1.0,
            config.DIVERSITY_THRESHOLD,
            0.05,
            key="fr_diversity",
        )
    if st.button("Find routes", type="primary", key="fr_go"):
        source = snap_or_report(res, pickup, "pickup")
        target = snap_or_report(res, dest, "destination")
        if source is not None and target is not None:
            request = RouteRequest(
                source=source.node,
                target=target.node,
                day=day,
                depart_s=depart_s,
                k=k,
                algorithm=ALGORITHMS[algo_label][0],
                heuristic=ALGORITHMS[algo_label][1],
                weights=weights,
                diversity_threshold=similarity if similarity < 1.0 else None,
            )
            with st.spinner("Searching for routes..."):
                response = plan_routes(res.graph, res.congestion, request)
            lat, lon = res.graph.lat_list(), res.graph.lon_list()
            st.session_state[RESULT_KEY] = {
                "response": response,
                "start": (lat[source.node], lon[source.node]),
                "end": (lat[target.node], lon[target.node]),
                "algorithm_label": algo_label,
                "day": day,
                "day_type": "weekend" if day in config.WEEKEND_DAYS else "weekday",
                "depart_label": f"{int(depart_s // 3600):02d}:{int(depart_s % 3600 // 60):02d}",
                "pickup": (pickup, source.node),
                "dest": (dest, target.node),
            }
            st.session_state["shared_points"] = (pickup, dest)
    result = st.session_state.get(RESULT_KEY)
    if result:
        _render_result(res, result, weights)

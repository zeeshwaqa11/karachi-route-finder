import json
from dataclasses import dataclass

import folium
import streamlit as st

from src import config
from src.congestion import CongestionModel
from src.graph import CSRGraph
from src.spatial import KDTree

ROUTE_COLOURS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00"]


@dataclass
class Resources:
    graph: CSRGraph
    congestion: CongestionModel
    tree: KDTree


@st.cache_resource(show_spinner="Loading the Karachi road graph...")
def _load_resources(path: str, mtime: float) -> Resources:
    graph = CSRGraph.load(path)
    graph.weight_list("length")
    graph.weight_list("time")
    graph.class_list()
    graph.in_edges(0)
    graph.coords_lists()
    return Resources(graph, CongestionModel(graph), KDTree(graph.lat, graph.lon))


def get_resources() -> Resources:
    path = config.graph_path()
    if not path.exists():
        st.error(
            f"The road graph has not been built yet (expected at `{path}`). "
            "Run this once from the project folder, then reload the page:"
        )
        st.code("python -m scripts.build_graph", language="bash")
        st.stop()
    return _load_resources(str(path), path.stat().st_mtime)


def simulation_banner() -> None:
    st.info(config.SIMULATION_NOTICE, icon="ℹ️")


def attribution_footer() -> None:
    st.divider()
    st.caption(
        f"Map data {config.ATTRIBUTION} (ODbL). Congestion is simulated and every time is an estimate, "
        "not a live or guaranteed travel time."
    )


def map_center(graph: CSRGraph) -> tuple[float, float]:
    return float(graph.lat.mean()), float(graph.lon.mean())


def graph_bounds(graph: CSRGraph) -> list[list[float]]:
    return [
        [float(graph.lat.min()), float(graph.lon.min())],
        [float(graph.lat.max()), float(graph.lon.max())],
    ]


def new_map(graph: CSRGraph, bounds=None, zoom: int = 12) -> folium.Map:
    lat, lon = map_center(graph)
    fmap = folium.Map(location=[lat, lon], zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    if bounds:
        fmap.fit_bounds(bounds)
    return fmap


def bounds_of(points: list[tuple[float, float]], pad: float = 0.002) -> list[list[float]]:
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return [[min(lats) - pad, min(lons) - pad], [max(lats) + pad, max(lons) + pad]]


def add_endpoint_markers(fmap: folium.Map, start, end) -> None:
    folium.Marker(start, tooltip="Pickup", icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fmap)
    folium.Marker(end, tooltip="Destination", icon=folium.Icon(color="red", icon="flag", prefix="fa")).add_to(fmap)


def legend_html(entries: list[tuple[str, str]], title: str | None = None) -> str:
    rows = "".join(
        f"<div style='margin:2px 0'><span style='display:inline-block;width:22px;height:5px;background:{colour};"
        f"margin-right:8px;vertical-align:middle;border-radius:2px'></span>{text}</div>"
        for colour, text in entries
    )
    head = f"<div style='font-weight:600;margin-bottom:4px'>{title}</div>" if title else ""
    return (
        "<div style='position:fixed;bottom:26px;left:12px;z-index:9999;background:rgba(255,255,255,0.94);"
        "color:#222;padding:8px 12px;border:1px solid #999;border-radius:6px;font-size:12.5px;"
        f"font-family:sans-serif;box-shadow:0 1px 4px rgba(0,0,0,0.3)'>{head}{rows}</div>"
    )


def add_legend(fmap: folium.Map, entries, title=None) -> None:
    fmap.get_root().html.add_child(folium.Element(legend_html(entries, title)))


def load_benchmarks() -> dict | None:
    path = config.reports_dir() / "benchmarks.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

import altair as alt
import pandas as pd
import streamlit as st

from src import config
from src.ui.common import load_benchmarks

ALGORITHM_LABELS = {
    "dijkstra": "Dijkstra",
    "bidirectional": "Bidirectional Dijkstra",
    "astar": "A*",
    "networkx_dijkstra": "NetworkX (reference)",
}
WEIGHT_LABELS = {"distance": "Distance", "time": "Free-flow time"}
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]


def _stat(row: dict, field: str, which: str):
    value = row.get(field)
    if isinstance(value, dict):
        return value.get(which)
    return None


def _shortest_frame(rows: list[dict]) -> pd.DataFrame:
    records = []
    for row in rows:
        records.append(
            {
                "Algorithm": ALGORITHM_LABELS.get(row["algorithm"], row["algorithm"]),
                "Weight": WEIGHT_LABELS.get(row["weight"], row["weight"]),
                "Median runtime (ms)": _stat(row, "runtime_ms", "median"),
                "95th percentile runtime (ms)": _stat(row, "runtime_ms", "p95"),
                "Median nodes settled": _stat(row, "settled", "median"),
                "95th percentile nodes settled": _stat(row, "settled", "p95"),
                "Median edges relaxed": _stat(row, "relaxed", "median"),
                "Pairs": row.get("n"),
            }
        )
    return pd.DataFrame(records)


def _grouped_bar(frame: pd.DataFrame, value: str, title: str, log: bool = False) -> alt.Chart:
    scale = alt.Scale(type="log") if log else alt.Scale(zero=True)
    return (
        alt.Chart(frame, title=title)
        .mark_bar()
        .encode(
            x=alt.X("Algorithm:N", title=None, sort=None, axis=alt.Axis(labelAngle=-20)),
            xOffset="Weight:N",
            y=alt.Y(f"{value}:Q", scale=scale, title=value),
            color=alt.Color("Weight:N", scale=alt.Scale(range=PALETTE[:2])),
            tooltip=["Algorithm", "Weight", value],
        )
        .properties(height=300)
    )


def _scaling_chart(scaling: dict) -> alt.Chart | None:
    points = scaling.get("points") or []
    if not points:
        return None
    frame = pd.DataFrame(points)
    fit = scaling.get("fit") or {}
    base = (
        alt.Chart(frame)
        .mark_point(size=90, filled=True, color=PALETTE[0])
        .encode(
            x=alt.X("e_log_v:Q", scale=alt.Scale(type="log"), title="E · log2(V)"),
            y=alt.Y("runtime_ms_median:Q", scale=alt.Scale(type="log"), title="Median full-search runtime (ms)"),
            tooltip=["nodes", "edges", "e_log_v", "runtime_ms_median"],
        )
    )
    layers = [base]
    if "slope" in fit and "intercept" in fit:
        line = frame.assign(
            fitted=lambda d: 10 ** (fit["intercept"] + fit["slope"] * d["e_log_v"].apply(lambda v: __import__("math").log10(v)))
        )
        layers.append(
            alt.Chart(line).mark_line(color=PALETTE[1]).encode(x="e_log_v:Q", y=alt.Y("fitted:Q", scale=alt.Scale(type="log")))
        )
    return alt.layer(*layers).properties(height=320, title="Runtime against E log V (log-log)")


def render() -> None:
    st.header("Benchmarks")
    data = load_benchmarks()
    if not data:
        st.warning("No benchmark results found yet. Generate them once (this takes a while on the full graph):")
        st.code("python -m scripts.benchmark", language="bash")
        st.caption(f"Expected file: {config.reports_dir() / 'benchmarks.json'}")
        return
    meta = data.get("meta", {})
    graph = meta.get("graph", {})
    st.caption(
        f"{meta.get('pairs', '?')} random origin-destination pairs (seed {meta.get('seed', '?')}) on "
        f"{graph.get('nodes', '?'):,} nodes / {graph.get('edges', '?'):,} edges · Python {meta.get('python', '?')} · {meta.get('processor', '')}. "
        "Pure-Python implementations, so absolute times are far slower than compiled libraries; compare the shapes, not the seconds."
    )
    rows = data.get("shortest_path", [])
    if rows:
        frame = _shortest_frame(rows)
        st.subheader("Single-pair shortest paths")
        left, right = st.columns(2)
        own = frame[frame["Algorithm"] != ALGORITHM_LABELS["networkx_dijkstra"]]
        left.altair_chart(_grouped_bar(frame, "Median runtime (ms)", "Median runtime"), use_container_width=True)
        right.altair_chart(_grouped_bar(own, "Median nodes settled", "Median nodes settled"), use_container_width=True)
        st.dataframe(frame, hide_index=True, use_container_width=True)
    heap_rows = data.get("heap_strategy", [])
    if heap_rows:
        st.subheader("decrease_key against lazy deletion inside Dijkstra")
        heap = pd.DataFrame(
            [
                {
                    "Strategy": r["strategy"].replace("_", " "),
                    "Median runtime (ms)": _stat(r, "runtime_ms", "median"),
                    "95th percentile runtime (ms)": _stat(r, "runtime_ms", "p95"),
                    "Median heap pushes": _stat(r, "pushes", "median"),
                }
                for r in heap_rows
            ]
        )
        st.altair_chart(
            alt.Chart(heap)
            .mark_bar()
            .encode(x="Strategy:N", y="Median runtime (ms):Q", color=alt.Color("Strategy:N", scale=alt.Scale(range=PALETTE)))
            .properties(height=240),
            use_container_width=True,
        )
        st.dataframe(heap, hide_index=True, use_container_width=True)
    yen_rows = data.get("yen", [])
    if yen_rows:
        st.subheader("Yen's K-shortest paths")
        yen = pd.DataFrame(
            [
                {
                    "K": r["k"],
                    "Variant": "with diversity filter" if r.get("diversity") else "plain",
                    "Median runtime (ms)": _stat(r, "runtime_ms", "median"),
                    "95th percentile runtime (ms)": _stat(r, "runtime_ms", "p95"),
                    "Median search runs": _stat(r, "spur_searches", "median"),
                    "Median nodes settled": _stat(r, "settled", "median"),
                }
                for r in yen_rows
            ]
        )
        st.altair_chart(
            alt.Chart(yen)
            .mark_bar()
            .encode(
                x=alt.X("K:O"),
                xOffset="Variant:N",
                y="Median runtime (ms):Q",
                color=alt.Color("Variant:N", scale=alt.Scale(range=PALETTE)),
            )
            .properties(height=260),
            use_container_width=True,
        )
        st.dataframe(yen, hide_index=True, use_container_width=True)
    scaling = data.get("scaling")
    if scaling:
        st.subheader("Scaling with graph size")
        chart = _scaling_chart(scaling)
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        fit = scaling.get("fit", {})
        if fit:
            st.caption(
                f"Log-log fit: slope {fit.get('slope', float('nan')):.2f}, R² {fit.get('r2', float('nan')):.3f}. A slope near 1 matches O(E log V)."
            )
    memory = data.get("memory")
    if memory:
        st.subheader("Memory: adjacency list against CSR")
        mem = pd.DataFrame(
            [
                {"Structure": "Adjacency list (edge objects)", "MiB": memory["adjacency_list_bytes"] / 2**20},
                {"Structure": "CSR (numpy arrays)", "MiB": memory["csr_bytes"] / 2**20},
                {"Structure": "CSR + Python-list mirrors used by the search", "MiB": memory["csr_python_lists_bytes"] / 2**20},
            ]
        )
        st.altair_chart(
            alt.Chart(mem)
            .mark_bar()
            .encode(
                y=alt.Y("Structure:N", sort=None, title=None),
                x=alt.X("MiB:Q"),
                color=alt.Color("Structure:N", legend=None, scale=alt.Scale(range=PALETTE)),
            )
            .properties(height=170),
            use_container_width=True,
        )
        st.dataframe(mem.round(1), hide_index=True, use_container_width=True)

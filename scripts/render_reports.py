import json
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src import config
from src.congestion import CongestionModel
from src.graph import CSRGraph
from src.report_inject import inject, markdown_table

BLUE = "#0072B2"
ORANGE = "#D55E00"
GREEN = "#009E73"
PURPLE = "#CC79A7"
GREY = "#6b7280"
ALGO_ORDER = ["dijkstra", "bidirectional", "astar", "networkx_dijkstra", "networkx_bidirectional"]
ALGO_LABEL = {
    "dijkstra": "Dijkstra",
    "bidirectional": "Bidirectional Dijkstra",
    "astar": "A* (haversine)",
    "networkx_dijkstra": "NetworkX Dijkstra (reference)",
    "networkx_bidirectional": "NetworkX bidirectional (reference)",
}
WEIGHT_LABEL = {"distance": "distance", "time": "free-flow time"}
TARGETS = [config.ROOT / "README.md", config.ROOT / "docs" / "complexity.md"]


def fmt(value, digits=1) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def graph_stats() -> dict | None:
    path = config.reports_dir() / "graph_stats.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    graph_file = config.graph_path()
    if graph_file.exists():
        meta = CSRGraph.load(graph_file).meta
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        return meta
    return None


def block_graph_stats(stats: dict) -> str:
    rows = [
        ["Area", stats["area_label"]],
        ["Nodes (intersections) after cleaning", f"{stats['nodes']:,}"],
        ["Directed edges after cleaning", f"{stats['edges']:,}"],
        ["Downloaded from OpenStreetMap", f"{stats['osm_nodes_downloaded']:,} nodes / {stats['osm_edges_downloaded']:,} edges"],
        [
            "Dropped to keep the largest strongly connected component",
            f"{stats['nodes_dropped_by_scc']:,} nodes / {stats['edges_dropped_by_scc']:,} edges",
        ],
        ["Self-loops dropped", f"{stats['self_loops_dropped']:,}"],
        ["Parallel edges merged into the cheapest", f"{stats['parallel_edges_merged']:,}"],
        [
            "Edges with an imputed (default) speed",
            f"{stats['edges_with_imputed_speed']:,} ({stats['imputed_share']:.1%})",
        ],
    ]
    classes = ", ".join(f"{k} {v:,}" for k, v in stats["edges_by_class"].items() if v)
    rows.append(["Edges by road class", classes])
    corridors = stats.get("corridor_edges")
    if corridors:
        rows.append(["Edges matched to a named busy corridor", ", ".join(f"{k} {v}" for k, v in corridors.items())])
    return markdown_table(["Item", "Value"], rows)


def block_meta(data: dict) -> str:
    m = data["meta"]
    g = m["graph"]
    versions = ", " + ", ".join(f"{k} {v}" for k, v in m["versions"].items()) if m.get("versions") else ""
    return (
        f"Measured on {g['nodes']:,} nodes / {g['edges']:,} edges ({g['area_label']}); {m['pairs']} random origin-destination pairs, "
        f"seed {m['seed']}; Python {m['python']} on {m['platform']} ({m['cpu_count']} logical CPUs)"
        f"{versions}; "
        f"code revision `{m['git_revision']}`; run at {m['created_utc']}. Every number in the tables below is generated from "
        "`reports/benchmarks.json`."
    )


def shortest_rows(data: dict) -> list[dict]:
    rows = data.get("shortest_path", [])
    return sorted(rows, key=lambda r: (r["weight"], ALGO_ORDER.index(r["algorithm"])))


def block_shortest(data: dict) -> str:
    rows = []
    for r in shortest_rows(data):
        rows.append(
            [
                ALGO_LABEL[r["algorithm"]],
                WEIGHT_LABEL[r["weight"]],
                fmt(r["runtime_ms"]["median"]),
                fmt(r["runtime_ms"]["p95"]),
                fmt(r.get("settled", {}).get("median"), 0) if "settled" in r else "-",
                fmt(r.get("settled", {}).get("p95"), 0) if "settled" in r else "-",
                fmt(r.get("relaxed", {}).get("median"), 0) if "relaxed" in r else "-",
            ]
        )
    return markdown_table(
        ["Algorithm", "Weight", "Median ms", "p95 ms", "Median nodes settled", "p95 nodes settled", "Median edges relaxed"], rows
    )


def block_ratios(data: dict) -> str:
    by = {(r["algorithm"], r["weight"]): r for r in data.get("shortest_path", [])}
    rows = []
    for weight in ("distance", "time"):
        base = by.get(("dijkstra", weight))
        if not base:
            continue
        for algo in ("bidirectional", "astar"):
            r = by[(algo, weight)]
            rows.append(
                [
                    ALGO_LABEL[algo],
                    WEIGHT_LABEL[weight],
                    f"{r['settled']['median'] / base['settled']['median']:.0%}",
                    f"{r['runtime_ms']['median'] / base['runtime_ms']['median']:.0%}",
                ]
            )
        ref = by.get(("networkx_dijkstra", weight))
        if ref:
            rows.append(
                [
                    "This project's Dijkstra vs NetworkX Dijkstra (runtime)",
                    WEIGHT_LABEL[weight],
                    "-",
                    f"{base['runtime_ms']['median'] / ref['runtime_ms']['median']:.2f}x",
                ]
            )
    return markdown_table(["Comparison", "Weight", "Nodes settled vs Dijkstra (median)", "Runtime vs Dijkstra (median)"], rows)


def block_correctness(data: dict) -> str:
    c = data.get("correctness")
    if not c:
        return "_Not measured yet._"
    return (
        f"On the {c['pairs']} benchmark pairs, every implementation returned the same path cost as NetworkX "
        f"(largest relative difference {c['max_relative_cost_difference_vs_networkx']:.1e}; all agree: {c['all_costs_agree']})."
    )


def block_heap(data: dict) -> str:
    rows = []
    for r in data.get("heap_strategy", []):
        ops = r.get("operations", {})
        rows.append(
            [
                r["strategy"].replace("_", " "),
                fmt(r["runtime_ms"]["median"]),
                fmt(r["runtime_ms"]["p95"]),
                fmt(ops.get("pushes")),
                fmt(ops.get("pops")),
                fmt(ops.get("decrease_keys")),
                fmt(ops.get("stale_pops")),
            ]
        )
    table = markdown_table(
        ["Strategy", "Median ms", "p95 ms", "Heap pushes*", "Heap pops*", "decrease_key calls*", "Stale pops*"], rows
    )
    sample = next((r["operations"]["sample_pairs"] for r in data.get("heap_strategy", []) if "operations" in r), "?")
    ratio = next(
        (r["paired_runtime_ratio_median"] for r in data.get("heap_strategy", []) if "paired_runtime_ratio_median" in r), None
    )
    text = table + f"\n\n*Operation counts are totals over the first {sample} pairs."
    if ratio is not None:
        text += (
            " Both strategies ran on the same pairs, interleaved and alternating which goes first; the median per-pair "
            f"ratio of `decrease_key` runtime to lazy runtime is **{ratio:.2f}**."
        )
    return text


def block_yen(data: dict) -> str:
    plain = [r for r in data.get("yen", []) if not r.get("diversity")]
    rows = [
        [
            r["k"],
            r["n"],
            fmt(r["runtime_ms"]["median"]),
            fmt(r["runtime_ms"]["p95"]),
            fmt(r["spur_searches"]["median"], 0),
            fmt(r["settled"]["median"], 0),
        ]
        for r in sorted(plain, key=lambda r: r["k"])
    ]
    text = markdown_table(["K", "Pairs", "Median ms", "p95 ms", "Median searches", "Median nodes settled"], rows)
    engines = data.get("yen_engines", [])
    if engines:
        rows = [
            [
                r["engine"],
                r["n"],
                fmt(r["runtime_ms"]["median"]),
                fmt(r["spur_searches"]["median"], 0),
                fmt(r["settled"]["median"], 0),
            ]
            for r in engines
        ]
        text += "\n\n" + markdown_table(
            ["Search inside Yen's (K = 3)", "Pairs", "Median ms", "Median searches", "Median nodes settled"], rows
        )
    return text


def block_diverse(data: dict) -> str:
    rows = []
    for r in sorted((r for r in data.get("yen", []) if r.get("diversity")), key=lambda r: r["k"]):
        rows.append(
            [
                r["k"],
                r["n"],
                fmt(r["runtime_ms"]["median"], 0),
                fmt(r["runtime_ms"]["p95"], 0),
                fmt(r["paths_found"]["median"], 0),
                f"{r['share_reaching_k']:.0%}",
                fmt(r["enumerated"]["median"], 0),
                fmt(r["rejected_as_similar"]["median"], 0),
            ]
        )
    if not rows:
        return "_Not measured yet._"
    return markdown_table(
        [
            "K",
            "Pairs",
            "Median ms",
            "p95 ms",
            "Median routes found",
            "Pairs reaching K routes",
            "Median candidate paths enumerated",
            "Median rejected as too similar",
        ],
        rows,
    )


def block_scaling(data: dict) -> str:
    s = data.get("scaling")
    if not s:
        return "_Not measured yet._"
    rows = [
        [f"{p['radius_m'] / 1000:.1f}", f"{p['nodes']:,}", f"{p['edges']:,}", fmt(p["e_log_v"], 0), fmt(p["runtime_ms_median"])]
        for p in s["points"]
    ]
    fit = s["fit"]
    table = markdown_table(["Half-width km", "Nodes V", "Edges E", "E log2 V", "Median full-search ms"], rows)
    return (
        table + f"\n\nLog-log least-squares fit of runtime against E log2 V over {len(s['points'])} graph sizes "
        f"({s['sources_per_size']} random sources each): slope **{fit['slope']:.2f}**, R² {fit['r2']:.3f}."
    )


def block_memory(data: dict) -> str:
    m = data.get("memory")
    if not m:
        return "_Not measured yet._"
    mib = 2**20
    rows = [
        [
            "Adjacency list (one Python object per edge)",
            fmt(m["adjacency_list_bytes"] / mib),
            fmt(m["adjacency_bytes_per_edge"], 0),
        ],
        [
            "CSR, numpy arrays only (what is stored on disk and kept in memory)",
            fmt(m["csr_bytes"] / mib),
            fmt(m["csr_bytes_per_edge"], 0),
        ],
        [
            "CSR plus the Python-list mirrors the pure-Python search reads",
            fmt(m["csr_python_lists_bytes"] / mib),
            fmt(m["csr_python_lists_bytes"] / m["edges"], 0),
        ],
    ]
    return (
        markdown_table(["Representation", "MiB", "Bytes per edge"], rows)
        + f"\n\nThe adjacency list needs **{m['ratio_adjacency_to_csr']:.1f}x** the memory of the numpy CSR arrays "
        f"on the same {m['nodes']:,}-node, {m['edges']:,}-edge graph (measured with `tracemalloc`)."
    )


def block_fifo() -> str | None:
    path = config.graph_path()
    if not path.exists():
        return None
    model = CongestionModel(CSRGraph.load(path))
    rows = [[day, f"{ratio:.4f}"] for day, ratio in model.fifo_ratio.items()]
    return (
        markdown_table(["Profile", "Worst slope ratio (must be at most 1)"], rows)
        + "\n\nThe ratio is the largest, over all edges and road classes, of "
        "`free-flow time x corridor factor x largest per-slot multiplier drop / 900 s`."
    )


def figure_dir():
    path = config.reports_dir() / "figures"
    path.mkdir(parents=True, exist_ok=True)
    return path


def style(ax, title, ylabel=None, xlabel=None):
    ax.set_title(title, fontsize=11, loc="left")
    if ylabel:
        ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)


def grouped_bars(data, field, title, ylabel, name, include_reference=True):
    rows = shortest_rows(data)
    algos = [a for a in ALGO_ORDER if include_reference or not a.startswith("networkx")]
    weights = ["distance", "time"]
    by = {(r["algorithm"], r["weight"]): r for r in rows}
    algos = [a for a in algos if any((a, w) in by and field in by[(a, w)] for w in weights)]
    fig, ax = plt.subplots(figsize=(8.6, 4.2))
    width = 0.38
    for j, (w, colour) in enumerate(zip(weights, (BLUE, ORANGE))):
        xs, med, p95 = [], [], []
        for i, a in enumerate(algos):
            if (a, w) in by:
                xs.append(i + (j - 0.5) * width)
                med.append(by[(a, w)][field]["median"])
                p95.append(by[(a, w)][field]["p95"])
        ax.bar(xs, med, width * 0.92, color=colour, label=f"median, {WEIGHT_LABEL[w]}")
        ax.errorbar(
            xs,
            med,
            yerr=[np.zeros(len(xs)), np.array(p95) - np.array(med)],
            fmt="none",
            ecolor="#111827",
            elinewidth=1,
            capsize=3,
        )
        for x, m in zip(xs, med):
            ax.text(x, m, f"{m:,.0f}", ha="center", va="bottom", fontsize=8, color="#111827")
    ax.set_xticks(range(len(algos)))
    ax.set_xticklabels([textwrap.fill(ALGO_LABEL[a], 15) for a in algos], fontsize=8)
    style(ax, title, ylabel)
    ax.legend(frameon=False, fontsize=8)
    ax.text(1.0, -0.2, "whiskers reach the 95th percentile", transform=ax.transAxes, ha="right", fontsize=7, color=GREY)
    fig.tight_layout()
    fig.savefig(figure_dir() / name, dpi=150)
    plt.close(fig)


def figure_heap(data):
    rows = data.get("heap_strategy", [])
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    labels = [r["strategy"].replace("_", " ") for r in rows]
    med = [r["runtime_ms"]["median"] for r in rows]
    p95 = [r["runtime_ms"]["p95"] for r in rows]
    ax.bar(labels, med, 0.5, color=[BLUE, ORANGE][: len(rows)])
    ax.errorbar(
        range(len(rows)), med, yerr=[np.zeros(len(rows)), np.array(p95) - np.array(med)], fmt="none", ecolor="#111827", capsize=4
    )
    for i, m in enumerate(med):
        ax.text(i, m, f"{m:,.0f} ms", ha="center", va="bottom", fontsize=9)
    style(ax, "Dijkstra: lazy deletion vs decrease_key", "median runtime (ms)")
    fig.tight_layout()
    fig.savefig(figure_dir() / "heap_strategies.png", dpi=150)
    plt.close(fig)


def figure_yen(data):
    plain = sorted((r for r in data.get("yen", []) if not r.get("diversity")), key=lambda r: r["k"])
    if not plain:
        return
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ks = [r["k"] for r in plain]
    med = [r["runtime_ms"]["median"] for r in plain]
    p95 = [r["runtime_ms"]["p95"] for r in plain]
    ax.bar([str(k) for k in ks], med, 0.5, color=BLUE)
    ax.errorbar(
        range(len(ks)), med, yerr=[np.zeros(len(ks)), np.array(p95) - np.array(med)], fmt="none", ecolor="#111827", capsize=4
    )
    for i, m in enumerate(med):
        ax.text(i, m, f"{m:,.0f} ms", ha="center", va="bottom", fontsize=9)
    style(ax, "Yen's K-shortest paths (A*, free-flow time)", "median runtime (ms)", "K")
    fig.tight_layout()
    fig.savefig(figure_dir() / "yen_runtime.png", dpi=150)
    plt.close(fig)


def figure_scaling(data):
    s = data.get("scaling")
    if not s:
        return
    x = np.array([p["e_log_v"] for p in s["points"]])
    y = np.array([p["runtime_ms_median"] for p in s["points"]])
    fit = s["fit"]
    fig, ax = plt.subplots(figsize=(5.8, 4.0))
    ax.loglog(x, y, "o", color=BLUE, markersize=7, label="measured (median of full searches)")
    line_x = np.array([x.min(), x.max()])
    ax.loglog(
        line_x,
        10 ** (fit["intercept"] + fit["slope"] * np.log10(line_x)),
        "-",
        color=ORANGE,
        linewidth=2,
        label=f"fit, slope {fit['slope']:.2f}",
    )
    style(ax, "Runtime against E log2 V (log-log)", "milliseconds", "E · log2(V)")
    ax.grid(axis="both", color="#e5e7eb", linewidth=0.8, which="major")
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_dir() / "scaling_loglog.png", dpi=150)
    plt.close(fig)


def figure_memory(data):
    m = data.get("memory")
    if not m:
        return
    labels = ["Adjacency list", "CSR (numpy)", "CSR + list mirrors"]
    values = [m["adjacency_list_bytes"], m["csr_bytes"], m["csr_python_lists_bytes"]]
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    ax.barh(labels, [v / 2**20 for v in values], 0.5, color=[ORANGE, BLUE, GREEN])
    for i, v in enumerate(values):
        ax.text(v / 2**20, i, f" {v / 2**20:,.0f} MiB", va="center", fontsize=9)
    ax.invert_yaxis()
    style(ax, "Memory for the same graph", None, "MiB")
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(values) / 2**20 * 1.25)
    fig.tight_layout()
    fig.savefig(figure_dir() / "memory.png", dpi=150)
    plt.close(fig)


def main() -> None:
    path = config.reports_dir() / "benchmarks.json"
    stats = graph_stats()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    blocks = {}
    if stats:
        blocks["graph_stats"] = block_graph_stats(stats)
    fifo = block_fifo()
    if fifo:
        blocks["fifo"] = fifo
    if data:
        blocks.update(
            {
                "bench_meta": block_meta(data),
                "bench_shortest": block_shortest(data),
                "bench_ratios": block_ratios(data),
                "bench_correctness": block_correctness(data),
                "bench_heap": block_heap(data),
                "bench_yen": block_yen(data),
                "bench_diverse": block_diverse(data),
                "bench_scaling": block_scaling(data),
                "bench_memory": block_memory(data),
            }
        )
        grouped_bars(data, "runtime_ms", "Single-pair query runtime", "median runtime (ms)", "runtime_by_algorithm.png")
        grouped_bars(
            data, "settled", "Nodes settled per query", "median nodes settled", "nodes_settled.png", include_reference=False
        )
        figure_heap(data)
        figure_yen(data)
        figure_scaling(data)
        figure_memory(data)
    for target in TARGETS:
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        for name, content in blocks.items():
            if f"<!-- BEGIN:{name} -->" in text:
                inject(target, name, content)
    print(f"Rendered {len(blocks)} blocks and figures into {figure_dir()}")


if __name__ == "__main__":
    main()

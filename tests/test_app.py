import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.ui.points import apply_click
from tests.helpers import synthetic_city

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    graph = synthetic_city(26, 26, seed=3).to_csr()
    graph.meta = {"area_label": "Synthetic test city", "imputed_share": 0.5}
    path = tmp_path / "synthetic.npz"
    graph.save(path)
    monkeypatch.setenv("KRF_GRAPH_PATH", str(path))
    monkeypatch.setenv("KRF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("KRF_REPORTS_DIR", str(tmp_path / "reports"))
    return tmp_path


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    return at


def text_of(elements) -> str:
    return " ".join(getattr(e, "value", "") or "" for e in elements)


def test_find_routes_page_loads_with_simulation_notice(env):
    at = run_app()
    assert not at.exception
    assert "Find routes" in text_of(at.header)
    assert "SIMULATED" in text_of(at.info)
    assert "OpenStreetMap contributors" in text_of(at.caption)


def test_finding_routes_between_two_builtin_places(env):
    at = run_app()
    at.selectbox(key="fr_pickup_place").select("Mazar-e-Quaid")
    at.selectbox(key="fr_dest_place").select("PECHS (Tariq Road)")
    at.slider(key="fr_k").set_value(3)
    at.button(key="fr_go").click()
    at.run()
    assert not at.exception
    assert len(at.dataframe) == 1
    frame = at.dataframe[0].value
    assert 1 <= len(frame) <= 3
    assert list(frame["Rank"]) == list(range(1, len(frame) + 1))
    assert (frame["Distance (km)"] > 0).all()
    assert any("Computation time" in m.label for m in at.metric)


def test_changing_ranking_weights_reranks_without_recomputing(env):
    at = run_app()
    at.selectbox(key="fr_pickup_place").select("Mazar-e-Quaid")
    at.selectbox(key="fr_dest_place").select("PECHS (Tariq Road)")
    at.button(key="fr_go").click()
    at.run()
    first = at.dataframe[0].value
    at.slider(key="fr_w_time").set_value(0.0)
    at.slider(key="fr_w_distance").set_value(1.0)
    at.slider(key="fr_w_congestion").set_value(0.0)
    at.run()
    assert not at.exception
    second = at.dataframe[0].value
    assert sorted(first["Distance (km)"]) == sorted(second["Distance (km)"])
    assert second["Distance (km)"].iloc[0] == second["Distance (km)"].min()


def test_point_outside_the_loaded_map_is_reported(env):
    at = run_app()
    at.selectbox(key="fr_pickup_place").select("Port Grand")
    at.selectbox(key="fr_dest_place").select("PECHS (Tariq Road)")
    at.button(key="fr_go").click()
    at.run()
    assert not at.exception
    assert any("outside the area" in e.value for e in at.error)


def test_visualizer_page_runs_three_algorithms(env):
    at = run_app()
    at.sidebar.radio(key="page").set_value("Algorithm visualizer")
    at.run()
    at.selectbox(key="viz_pickup").select("Mazar-e-Quaid")
    at.selectbox(key="viz_dest").select("PECHS (Tariq Road)")
    at.button(key="viz_go").click()
    at.run()
    assert not at.exception
    frame = at.dataframe[0].value
    assert list(frame["Algorithm"]) == ["Dijkstra", "Bidirectional Dijkstra", "A*"]
    assert frame["Nodes settled"].min() > 0
    assert "SIMULATED" in text_of(at.info)


def test_benchmarks_page_without_results_explains_how_to_generate_them(env):
    at = run_app()
    at.sidebar.radio(key="page").set_value("Benchmarks")
    at.run()
    assert not at.exception
    assert "scripts.benchmark" in text_of(at.code)
    assert "SIMULATED" in text_of(at.info)


def test_benchmarks_page_renders_results_file(env):
    reports = env / "reports"
    reports.mkdir()
    stat = {"median": 10.0, "p95": 20.0}
    payload = {
        "meta": {"pairs": 5, "seed": 1, "python": "3.12", "processor": "test", "graph": {"nodes": 100, "edges": 300}},
        "shortest_path": [
            {"algorithm": a, "weight": w, "n": 5, "runtime_ms": stat, "settled": stat, "relaxed": stat}
            for a in ("dijkstra", "astar")
            for w in ("distance", "time")
        ],
        "heap_strategy": [{"strategy": "lazy", "runtime_ms": stat, "pushes": stat}],
        "yen": [{"k": 3, "diversity": False, "runtime_ms": stat, "spur_searches": stat, "settled": stat}],
        "scaling": {
            "points": [{"nodes": 10, "edges": 30, "e_log_v": 100.0, "runtime_ms_median": 1.0}],
            "fit": {"slope": 1.0, "intercept": 0.0, "r2": 1.0},
        },
        "memory": {"adjacency_list_bytes": 3e6, "csr_bytes": 1e6, "csr_python_lists_bytes": 2e6},
    }
    (reports / "benchmarks.json").write_text(json.dumps(payload), encoding="utf-8")
    at = run_app()
    at.sidebar.radio(key="page").set_value("Benchmarks")
    at.run()
    assert not at.exception
    assert len(at.dataframe) >= 3


def test_about_page(env):
    at = run_app()
    at.sidebar.radio(key="page").set_value("About & limitations")
    at.run()
    assert not at.exception
    assert "Limitations" in text_of(at.subheader)
    assert "SIMULATED" in text_of(at.info)


def test_missing_graph_shows_the_build_command(tmp_path, monkeypatch):
    monkeypatch.setenv("KRF_GRAPH_PATH", str(tmp_path / "absent.npz"))
    monkeypatch.setenv("KRF_REPORTS_DIR", str(tmp_path))
    at = run_app()
    assert not at.exception
    assert "not been built" in text_of(at.error)
    assert "python -m scripts.build_graph" in text_of(at.code)


def test_apply_click_assigns_to_the_selected_role_and_ignores_repeats():
    state = {}
    click = {"lat": 24.87, "lng": 67.03}
    assert apply_click(state, "Pickup", click, None)
    assert state["click_pickup"][:2] == (24.87, 67.03)
    assert not apply_click(state, "Destination", click, click)
    assert "click_dest" not in state
    assert apply_click(state, "Destination", {"lat": 24.9, "lng": 67.1}, click)
    assert state["click_dest"][:2] == (24.9, 67.1)
    assert not apply_click(state, "Pickup", None, None)

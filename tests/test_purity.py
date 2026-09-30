import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
FORBIDDEN = {"networkx", "osmnx"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_routing_package_never_imports_networkx():
    files = list((SRC / "routing").glob("*.py"))
    assert files
    for path in files:
        assert "networkx" not in imported_modules(path), path.name


def test_no_string_based_imports_of_networkx_in_routing():
    for path in (SRC / "routing").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "networkx" not in text, path.name
        assert "importlib" not in text and "__import__" not in text, path.name


def test_only_the_osm_modules_may_use_osmnx_or_networkx():
    allowed = {"osm_download.py"}
    for path in SRC.rglob("*.py"):
        if path.name in allowed:
            continue
        assert not (imported_modules(path) & FORBIDDEN), path.relative_to(SRC)


def test_osm_conversion_module_is_free_of_osmnx_and_networkx_imports():
    assert not (imported_modules(SRC / "osm_convert.py") & FORBIDDEN)


def test_detector_catches_a_forbidden_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import networkx as nx\nfrom networkx.algorithms import shortest_paths\n", encoding="utf-8")
    assert "networkx" in imported_modules(bad)
    good = tmp_path / "good.py"
    good.write_text("import heapq\nfrom src.graph import CSRGraph\n", encoding="utf-8")
    assert "networkx" not in imported_modules(good)


def test_routing_modules_import_cleanly_without_networkx_loaded():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import src.routing.dijkstra, src.routing.astar, src.routing.bidirectional\n"
        "import src.routing.yen, src.congestion, src.planner\n"
        "sys.exit(1 if 'networkx' in sys.modules else 0)\n"
    )
    root = SRC.parent
    proc = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", ["dijkstra", "astar", "bidirectional", "yen", "weights", "result"])
def test_routing_modules_exist(name):
    assert (SRC / "routing" / f"{name}.py").exists()

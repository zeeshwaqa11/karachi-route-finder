import time
from pathlib import Path

from src import config

MAX_ATTEMPTS = 5


def download_raw_graph(force: bool = False):
    import osmnx as ox

    path = config.raw_graphml_path()
    if path.exists() and not force:
        print(f"Loading cached OpenStreetMap graph from {path}")
        started = time.perf_counter()
        graph = ox.load_graphml(path)
        print(f"  loaded in {time.perf_counter() - started:.1f}s")
        return graph

    area = config.AREAS[config.area_key()]
    print(f"Downloading the drivable road network for: {area['label']}")
    print("  this is done once and cached; the first download can take several minutes")
    ox.settings.use_cache = True
    ox.settings.log_console = False
    started = time.perf_counter()
    graph = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if area["kind"] == "bbox":
                bbox = (area["west"], area["south"], area["east"], area["north"])
                graph = ox.graph_from_bbox(bbox, network_type=config.NETWORK_TYPE)
            else:
                graph = ox.graph_from_place(area["query"], network_type=config.NETWORK_TYPE)
            break
        except Exception as exc:
            print(f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {type(exc).__name__}")
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(10 * attempt)
    print(
        f"  downloaded {graph.number_of_nodes():,} nodes and {graph.number_of_edges():,} edges "
        f"in {time.perf_counter() - started:.0f}s"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, path)
    print(f"  cached at {Path(path)}")
    return graph

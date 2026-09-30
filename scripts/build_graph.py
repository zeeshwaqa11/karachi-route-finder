import argparse
import time

from src import config
from src.congestion import CongestionModel
from src.graph import CSRGraph
from src.osm_convert import convert_osmnx_graph
from src.osm_download import download_raw_graph


def print_report(report: dict) -> None:
    print(f"Area: {report['area_label']}")
    print(f"  OSM download:           {report['osm_nodes_downloaded']:,} nodes, {report['osm_edges_downloaded']:,} edges")
    print(f"  self-loops dropped:     {report['self_loops_dropped']:,}")
    print(f"  parallel edges merged:  {report['parallel_edges_merged']:,}")
    print(
        f"  strongly connected:     kept {report['nodes']:,} nodes and {report['edges']:,} edges; "
        f"dropped {report['nodes_dropped_by_scc']:,} nodes and {report['edges_dropped_by_scc']:,} edges"
    )
    print(
        f"  imputed speeds:         {report['edges_with_imputed_speed']:,} edges ({report['imputed_share']:.1%}) "
        "use the default speed for their road class"
    )
    print(f"  edges by class:         {report['edges_by_class']}")
    print(f"  named corridor edges:   {report.get('corridor_edges')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download (once) and convert the Karachi road network")
    parser.add_argument("--redownload", action="store_true", help="ignore the cached OpenStreetMap download")
    parser.add_argument("--rebuild", action="store_true", help="re-run the conversion from the cached download")
    args = parser.parse_args()

    target = config.graph_path()
    if target.exists() and not args.rebuild and not args.redownload:
        print(f"Compact graph already built at {target}; nothing to do (use --rebuild to convert again)")
        started = time.perf_counter()
        graph = CSRGraph.load(target)
        print(f"  loaded in {time.perf_counter() - started:.2f}s")
        print_report(graph.meta)
        return

    print(f"Area: {config.area_key()}")
    osm_graph = download_raw_graph(force=args.redownload)
    print("Converting to the compact graph structure")
    started = time.perf_counter()
    graph, report = convert_osmnx_graph(osm_graph)
    report["corridor_edges"] = CongestionModel(graph).corridor_edges
    graph.meta = report
    graph.save(target)
    print(f"  converted and saved to {target} in {time.perf_counter() - started:.1f}s")
    print_report(report)


if __name__ == "__main__":
    main()

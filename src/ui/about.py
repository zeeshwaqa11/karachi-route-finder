import streamlit as st

from src import config
from src.ui.common import Resources


def render(res: Resources) -> None:
    st.header("About & limitations")
    meta = res.graph.meta or {}
    st.subheader("What this is")
    st.write(
        "A portfolio project that models Karachi's road network as a weighted directed graph and returns several ranked routes. "
        "The graph, priority queue, Dijkstra, A*, bidirectional Dijkstra, Yen's K-shortest paths, the time-dependent search and the "
        "nearest-node index are all written from scratch in `src/`. NetworkX is used only inside the tests and benchmarks as a reference."
    )
    st.subheader("The loaded graph")
    if meta:
        c1, c2, c3 = st.columns(3)
        c1.metric("Nodes", f"{res.graph.n:,}")
        c2.metric("Directed edges", f"{res.graph.m:,}")
        c3.metric("Edges with imputed speed", f"{meta.get('imputed_share', 0.0):.0%}")
        st.caption(f"Area: {meta.get('area_label', config.area_key())}")
    else:
        c1, c2 = st.columns(2)
        c1.metric("Nodes", f"{res.graph.n:,}")
        c2.metric("Directed edges", f"{res.graph.m:,}")
    st.subheader("How congestion is simulated")
    st.write(
        "There is no free live traffic feed for Karachi, so every free-flow travel time is multiplied by an assumed "
        "time-of-day factor for each 15-minute slot, by road class, with separate weekday and weekend profiles "
        "(morning peak around 08:00-10:00, evening peak around 17:00-20:00 on weekdays). A few named corridors "
        "(Shahrah-e-Faisal, M.A. Jinnah Road, University Road, I.I. Chundrigar Road) carry an extra assumed multiplier. "
        "All numbers live in `src/config.py`. They are assumptions, not measurements."
    )
    st.subheader("Limitations")
    st.markdown(
        """
- **Simulated congestion.** Nothing here reflects real traffic, incidents, weather or events.
- **Imputed speeds.** Most OpenStreetMap roads in Karachi have no speed limit, so a default speed per road class is used. These are free-flow speeds, not observed ones.
- **OpenStreetMap gaps.** Some areas have missing roads, missing names or wrong one-way tags. Private and restricted roads (for example inside the airport) are absent.
- **No turn restrictions or traffic signals.** Turning costs and red lights are not modelled, so times are optimistic at busy junctions.
- **Estimates only.** Do not use these times for real trip planning.
- **Nearest-node snapping.** Points are snapped to the nearest graph node, so a route can start a short walk away from the exact point you chose.
"""
    )
    st.subheader("Data licence")
    st.write(f"Road data {config.ATTRIBUTION}, available under the Open Database Licence (ODbL). Map tiles by OpenStreetMap.")
    st.write(
        "Optional place-name search uses the public Nominatim service under its usage policy: opt-in only, at most one request "
        "per second, an identifying user agent, and local caching of results."
    )

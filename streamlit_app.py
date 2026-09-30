import streamlit as st

from src.ui import about, benchmarks_page, find_routes, visualizer
from src.ui.common import attribution_footer, get_resources, simulation_banner

PAGES = ("Find routes", "Algorithm visualizer", "Benchmarks", "About & limitations")

st.set_page_config(page_title="Karachi Route Finder", page_icon="🗺️", layout="wide")

st.sidebar.title("Karachi Route Finder")
page = st.sidebar.radio("Page", PAGES, key="page")
st.sidebar.caption("Hand-written Dijkstra, A*, Yen's K-shortest paths and simulated time-dependent congestion.")

simulation_banner()

if page == "Benchmarks":
    benchmarks_page.render()
else:
    resources = get_resources()
    if page == "Find routes":
        find_routes.render(resources)
    elif page == "Algorithm visualizer":
        visualizer.render(resources)
    else:
        about.render(resources)

attribution_footer()

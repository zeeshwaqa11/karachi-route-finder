import folium
import streamlit as st
from streamlit_folium import st_folium

from src import config
from src.geocode import GeocodeError, Geocoder
from src.places import PLACES, PLACES_BY_NAME
from src.spatial import Snap, snap_point
from src.ui.common import Resources, graph_bounds, new_map

MODES = ("Built-in places", "Click on the map", "Type a place name")
PLACE_NAMES = [p.name for p in PLACES]


def place_point(name: str):
    place = PLACES_BY_NAME[name]
    return place.lat, place.lon, place.name


def apply_click(state, target: str, click: dict | None, last_seen: dict | None):
    if not click or click == last_seen:
        return False
    key = "click_pickup" if target == "Pickup" else "click_dest"
    state[key] = (float(click["lat"]), float(click["lng"]), f"{target} (map click)")
    return True


def _click_picker(res: Resources, prefix: str):
    target = st.radio("The next map click sets the", ("Pickup", "Destination"), horizontal=True, key=f"{prefix}_click_target")
    fmap = new_map(res.graph, graph_bounds(res.graph))
    for key, colour in (("click_pickup", "green"), ("click_dest", "red")):
        point = st.session_state.get(key)
        if point:
            folium.Marker(
                [point[0], point[1]], tooltip=point[2], icon=folium.Icon(color=colour, icon="map-pin", prefix="fa")
            ).add_to(fmap)
    output = st_folium(fmap, key=f"{prefix}_click_map", height=420, use_container_width=True, returned_objects=["last_clicked"])
    click = output.get("last_clicked") if output else None
    if apply_click(st.session_state, target, click, st.session_state.get(f"{prefix}_last_click")):
        st.session_state[f"{prefix}_last_click"] = click
        st.rerun()
    pickup = st.session_state.get("click_pickup")
    dest = st.session_state.get("click_dest")
    if st.button("Clear clicked points", key=f"{prefix}_click_clear"):
        st.session_state.pop("click_pickup", None)
        st.session_state.pop("click_dest", None)
        st.rerun()
    return pickup, dest


def _geocoder(enabled: bool) -> Geocoder:
    geocoder = st.session_state.get("geocoder")
    if geocoder is None:
        geocoder = Geocoder(enabled=enabled)
        st.session_state["geocoder"] = geocoder
    geocoder.enabled = enabled
    return geocoder


def _geocode_picker(prefix: str):
    enabled = st.checkbox(
        "Enable place-name search (sends the text you type to the free Nominatim service, at most 1 request per second, "
        "results are cached on this computer)",
        key=f"{prefix}_geocode_on",
    )
    geocoder = _geocoder(enabled)
    c1, c2 = st.columns(2)
    q_pickup = c1.text_input("Pickup place name", key=f"{prefix}_q_pickup", placeholder="e.g. Dolmen Mall Clifton")
    q_dest = c2.text_input("Destination place name", key=f"{prefix}_q_dest", placeholder="e.g. Karachi University")
    if st.button("Search places", key=f"{prefix}_geocode_go"):
        for slot, query in (("pickup", q_pickup), ("dest", q_dest)):
            try:
                st.session_state[f"{prefix}_geo_{slot}"] = geocoder.search(query) if query.strip() else []
            except GeocodeError as exc:
                st.session_state[f"{prefix}_geo_{slot}"] = []
                st.error(f"{slot.capitalize()}: {exc}")
    picks = []
    for slot, column in (("pickup", c1), ("dest", c2)):
        results = st.session_state.get(f"{prefix}_geo_{slot}", [])
        if results:
            labels = [r.name for r in results]
            choice = column.selectbox(f"Matches for {slot}", labels, key=f"{prefix}_pick_{slot}")
            chosen = results[labels.index(choice)]
            picks.append((chosen.lat, chosen.lon, chosen.name))
        else:
            picks.append(None)
    if not enabled and not any(picks):
        st.caption("Search is off. Cached searches still work; switch it on to look up new names.")
    return picks[0], picks[1]


def choose_points(res: Resources, prefix: str, default_pickup: int = 1, default_dest: int = 5):
    mode = st.radio("How do you want to choose the points?", MODES, horizontal=True, key=f"{prefix}_mode")
    if mode == MODES[0]:
        c1, c2 = st.columns(2)
        a = c1.selectbox("Pickup", PLACE_NAMES, index=default_pickup, key=f"{prefix}_pickup_place")
        b = c2.selectbox("Destination", PLACE_NAMES, index=default_dest, key=f"{prefix}_dest_place")
        return place_point(a), place_point(b)
    if mode == MODES[1]:
        return _click_picker(res, prefix)
    return _geocode_picker(prefix)


def snap_or_report(res: Resources, point, role: str) -> Snap | None:
    if point is None:
        st.warning(f"Choose a {role} first.")
        return None
    snap = snap_point(res.tree, point[0], point[1])
    if snap.distance_m > config.SNAP_REJECT_METRES:
        st.error(
            f"The {role} '{point[2]}' is {snap.distance_m / 1000:.1f} km from the nearest road in the loaded map. "
            "It is outside the area that was downloaded, so it cannot be routed."
        )
        return None
    if snap.far:
        st.warning(
            f"The {role} '{point[2]}' is {snap.distance_m:.0f} m from the nearest road node "
            f"(more than {config.SNAP_WARNING_METRES:.0f} m). The route starts from that node, not from your exact point."
        )
    return snap

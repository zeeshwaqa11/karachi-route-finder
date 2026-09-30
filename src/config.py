import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AREA = "central"

AREAS = {
    "central": {
        "kind": "bbox",
        "north": 24.96,
        "south": 24.79,
        "east": 67.17,
        "west": 66.98,
        "label": "Central Karachi (Saddar, Clifton, PECHS, Gulshan, Airport corridor)",
    },
    "full": {
        "kind": "place",
        "query": "Karachi, Sindh, Pakistan",
        "label": "Full Karachi",
    },
}

NETWORK_TYPE = "drive"

ROAD_CLASSES = [
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "residential",
    "service",
]

HIGHWAY_TO_CLASS = {
    "motorway": "motorway",
    "motorway_link": "motorway",
    "trunk": "trunk",
    "trunk_link": "trunk",
    "primary": "primary",
    "primary_link": "primary",
    "secondary": "secondary",
    "secondary_link": "secondary",
    "tertiary": "tertiary",
    "tertiary_link": "tertiary",
    "unclassified": "tertiary",
    "residential": "residential",
    "living_street": "residential",
    "road": "residential",
    "service": "service",
}

FALLBACK_CLASS = "residential"

DEFAULT_SPEEDS_KMH = {
    "motorway": 80.0,
    "trunk": 65.0,
    "primary": 55.0,
    "secondary": 45.0,
    "tertiary": 40.0,
    "residential": 30.0,
    "service": 20.0,
}

MIN_VALID_SPEED_KMH = 5.0
MAX_VALID_SPEED_KMH = 130.0

DEFAULT_ROUTE_WEIGHTS = {"time": 0.5, "distance": 0.2, "congestion": 0.3}

SNAP_WARNING_METRES = 300.0

DIVERSITY_THRESHOLD = 0.7
YEN_MAX_CANDIDATES_FACTOR = 12
YEN_MAX_PATHS_ABSOLUTE = 80

SLOT_MINUTES = 15
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES

WEEKEND_DAYS = ("Saturday", "Sunday")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

WEEKDAY_ANCHORS_HOURS = [
    (0.0, 1.00),
    (5.0, 1.00),
    (6.5, 1.15),
    (8.0, 1.70),
    (9.0, 2.00),
    (10.0, 1.65),
    (11.5, 1.25),
    (14.0, 1.30),
    (16.0, 1.45),
    (17.0, 1.75),
    (18.5, 2.10),
    (20.0, 1.80),
    (21.5, 1.25),
    (23.0, 1.05),
    (24.0, 1.00),
]

WEEKEND_ANCHORS_HOURS = [
    (0.0, 1.00),
    (7.0, 1.00),
    (10.0, 1.10),
    (13.0, 1.25),
    (17.0, 1.40),
    (20.0, 1.55),
    (22.0, 1.25),
    (24.0, 1.00),
]

CLASS_SENSITIVITY = {
    "motorway": 0.55,
    "trunk": 0.90,
    "primary": 1.00,
    "secondary": 0.90,
    "tertiary": 0.70,
    "residential": 0.40,
    "service": 0.25,
}

CORRIDOR_MULTIPLIERS = {
    "Shahrah-e-Faisal": {
        "multiplier": 1.25,
        "aliases": ["Shahrah-e-Faisal", "Shara-e-Faisal", "Sharea Faisal", "Shahra-e-Faisal", "Sharah-e-Faisal", "Sharae Faisal"],
    },
    "M.A. Jinnah Road": {
        "multiplier": 1.30,
        "aliases": ["M.A. Jinnah Road", "M. A. Jinnah Road", "MA Jinnah Road", "Muhammad Ali Jinnah Road"],
    },
    "University Road": {
        "multiplier": 1.25,
        "aliases": ["University Road", "Shahrah-e-Jamia", "Shahrah-e-Jamia Karachi"],
    },
    "I.I. Chundrigar Road": {
        "multiplier": 1.30,
        "aliases": ["I.I. Chundrigar Road", "I. I. Chundrigar Road", "II Chundrigar Road", "Chundrigar Road"],
    },
}

CONGESTION_THRESHOLDS = {"low_below": 1.25, "heavy_from": 1.60}

FIFO_SLACK = 0.5

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_MIN_INTERVAL_S = 1.0
NOMINATIM_USER_AGENT = "KarachiRouteFinder/1.0 (portfolio project; https://github.com/your-username/karachi-route-finder)"
GEOCODE_VIEWBOX = None

ATTRIBUTION = "© OpenStreetMap contributors"
SIMULATION_NOTICE = "Congestion is SIMULATED from assumed time-of-day profiles, not live traffic. All travel times are estimates."

BENCH_SEED = 20240611
BENCH_PAIRS = 500


def area_key() -> str:
    key = os.environ.get("KRF_AREA", AREA)
    if key not in AREAS:
        raise ValueError(f"Unknown area {key!r}; choose one of {sorted(AREAS)}")
    return key


def data_dir() -> Path:
    return Path(os.environ.get("KRF_DATA_DIR", ROOT / "data"))


def reports_dir() -> Path:
    return Path(os.environ.get("KRF_REPORTS_DIR", ROOT / "reports"))


def raw_graphml_path() -> Path:
    return data_dir() / f"karachi_drive_{area_key()}.graphml"


def graph_path() -> Path:
    override = os.environ.get("KRF_GRAPH_PATH")
    if override:
        return Path(override)
    return data_dir() / f"karachi_drive_{area_key()}.npz"


def geocode_cache_path() -> Path:
    return data_dir() / "geocode_cache.json"

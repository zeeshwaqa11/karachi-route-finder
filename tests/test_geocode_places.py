import io
import json

import pytest

from src import config
from src.geocode import GeocodeError, Geocoder
from src.places import PLACES, PLACES_BY_NAME


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(json.dumps(self.payload).encode("utf-8"))


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


PAYLOAD = [{"display_name": "Dolmen Mall, Clifton, Karachi", "lat": "24.80", "lon": "67.03"}]


def make(tmp_path, **kwargs):
    clock = FakeClock()
    opener = FakeOpener(PAYLOAD)
    geocoder = Geocoder(tmp_path / "cache.json", opener=opener, clock=clock, sleep=clock.sleep, **kwargs)
    return geocoder, opener, clock


def test_disabled_geocoder_never_touches_the_network(tmp_path):
    geocoder, opener, _ = make(tmp_path, enabled=False)
    with pytest.raises(GeocodeError):
        geocoder.search("dolmen mall")
    assert opener.requests == []


def test_request_carries_user_agent_and_bounds(tmp_path):
    geocoder, opener, _ = make(tmp_path, enabled=True, user_agent="TestApp/1.0 (contact@example.org)")
    results = geocoder.search("Dolmen Mall")
    assert results[0].lat == 24.80 and results[0].lon == 67.03
    request = opener.requests[0]
    assert request.get_header("User-agent") == "TestApp/1.0 (contact@example.org)"
    assert "bounded=1" in request.full_url and "countrycodes=pk" in request.full_url


def test_results_are_cached_in_memory_and_on_disk(tmp_path):
    geocoder, opener, _ = make(tmp_path, enabled=True)
    geocoder.search("Dolmen Mall")
    geocoder.search("  dolmen   MALL ")
    assert len(opener.requests) == 1
    reloaded = Geocoder(tmp_path / "cache.json", enabled=False)
    assert reloaded.search("dolmen mall")[0].name.startswith("Dolmen")


def test_at_most_one_request_per_second(tmp_path):
    geocoder, opener, clock = make(tmp_path, enabled=True)
    geocoder.search("first place")
    geocoder.search("second place")
    geocoder.search("third place")
    assert len(opener.requests) == 3
    assert len(clock.sleeps) == 2
    assert all(s >= config.NOMINATIM_MIN_INTERVAL_S - 1e-9 for s in clock.sleeps)


def test_network_failure_becomes_geocode_error(tmp_path):
    def broken(request, timeout=None):
        raise OSError("offline")

    geocoder = Geocoder(tmp_path / "c.json", enabled=True, opener=broken)
    with pytest.raises(GeocodeError):
        geocoder.search("anywhere")


def test_empty_query_returns_nothing(tmp_path):
    geocoder, opener, _ = make(tmp_path, enabled=True)
    assert geocoder.search("   ") == []
    assert opener.requests == []


def test_place_list_is_about_25_unique_karachi_points():
    assert 24 <= len(PLACES) <= 26
    assert len(PLACES_BY_NAME) == len(PLACES)
    for p in PLACES:
        assert 24.7 < p.lat < 25.1 and 66.9 < p.lon < 67.3
    names = " ".join(p.name for p in PLACES)
    for required in (
        "Airport",
        "Saddar",
        "Clifton",
        "Dolmen",
        "University",
        "Gulshan",
        "North Nazimabad",
        "Korangi",
        "Port Grand",
    ):
        assert required in names

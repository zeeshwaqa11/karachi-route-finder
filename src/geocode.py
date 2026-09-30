import json
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from src import config

KARACHI_VIEWBOX = (66.60, 25.45, 67.60, 24.70)


class GeocodeError(RuntimeError):
    pass


@dataclass
class GeocodeResult:
    name: str
    lat: float
    lon: float


class Geocoder:
    def __init__(
        self,
        cache_path=None,
        *,
        enabled: bool = False,
        user_agent: str | None = None,
        min_interval_s: float | None = None,
        opener=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.cache_path = Path(cache_path) if cache_path else config.geocode_cache_path()
        self.enabled = enabled
        self.user_agent = user_agent or config.NOMINATIM_USER_AGENT
        self.min_interval_s = config.NOMINATIM_MIN_INTERVAL_S if min_interval_s is None else min_interval_s
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None
        self.requests_made = 0
        self._cache = self._load_cache()

    def _load_cache(self) -> dict:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=1), encoding="utf-8")

    @staticmethod
    def _key(query: str) -> str:
        return " ".join(query.casefold().split())

    def cached(self, query: str) -> list[GeocodeResult] | None:
        hit = self._cache.get(self._key(query))
        return None if hit is None else [GeocodeResult(**item) for item in hit]

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval_s - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)

    def search(self, query: str, limit: int = 5) -> list[GeocodeResult]:
        query = query.strip()
        if not query:
            return []
        hit = self.cached(query)
        if hit is not None:
            return hit
        if not self.enabled:
            raise GeocodeError("Place-name search is switched off; enable it to contact Nominatim")
        params = {
            "q": query,
            "format": "jsonv2",
            "limit": str(limit),
            "countrycodes": "pk",
            "viewbox": ",".join(str(v) for v in KARACHI_VIEWBOX),
            "bounded": "1",
        }
        url = f"{config.NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
        self._throttle()
        try:
            self._last_request = self._clock()
            self.requests_made += 1
            with self._opener(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise GeocodeError(f"Nominatim request failed: {type(exc).__name__}") from exc
        results = [
            GeocodeResult(item.get("display_name", query), float(item["lat"]), float(item["lon"]))
            for item in payload
            if "lat" in item and "lon" in item
        ]
        self._cache[self._key(query)] = [asdict(r) for r in results]
        self._save_cache()
        return results

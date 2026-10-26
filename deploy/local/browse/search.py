import json
import os
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class SearchResult:
    query: str
    engine: str
    hits: list[SearchHit]


@dataclass(frozen=True)
class SearxngResponse:
    hits: list[SearchHit]
    unresponsive: list[str]


class SearchError(RuntimeError):
    pass


class TTLCache:
    def __init__(self, ttl: float, max_entries: int = 128):
        self._ttl = ttl
        self._max_entries = max_entries
        self._data: dict[object, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def get(self, key: object) -> object | None:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            stored_at, value = item
            if time.monotonic() - stored_at > self._ttl:
                del self._data[key]
                return None
            return value

    def set(self, key: object, value: object) -> None:
        with self._lock:
            now = time.monotonic()
            expired = [
                stored_key
                for stored_key, (stored_at, _) in self._data.items()
                if now - stored_at > self._ttl
            ]
            for stored_key in expired:
                del self._data[stored_key]
            while len(self._data) >= self._max_entries:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (now, value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_CACHE = TTLCache(300, max_entries=128)


def parse_searxng(payload: str) -> SearxngResponse:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SearchError(f"searxng json parse failed: {error}") from error
    if not isinstance(data, dict):
        raise SearchError("searxng response is not an object")

    unresponsive: list[str] = []
    for entry in data.get("unresponsive_engines", []):
        if isinstance(entry, (list, tuple)) and entry:
            name = str(entry[0])
            reason = str(entry[1]) if len(entry) > 1 and entry[1] else ""
            unresponsive.append(f"{name}: {reason}" if reason else name)
        elif isinstance(entry, str):
            unresponsive.append(entry)

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        if len(url) > 2000:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=(item.get("title") or "").strip()[:300],
                url=url,
                snippet=(item.get("content") or "").strip()[:500],
            )
        )
    return SearxngResponse(hits=hits, unresponsive=unresponsive)


def _searxng_url(query: str, time_range: str | None) -> str:
    params = {"q": query, "format": "json"}
    if time_range:
        params["time_range"] = time_range
    return f"{SEARXNG_URL}/search?{urlencode(params)}"


def _fetch_searxng(url: str) -> str:
    try:
        response = httpx.get(url, timeout=6.0, trust_env=False)
    except httpx.TimeoutException as error:
        raise SearchError("searxng timed out") from error
    if response.status_code != 200:
        raise SearchError(f"searxng returned {response.status_code}")
    return response.text


def search_web(
    query: str,
    *,
    count: int = 5,
    time_range: str | None = None,
) -> SearchResult:
    query = query.strip()
    if not query:
        raise SearchError("query is empty")
    if len(query) > 500:
        raise SearchError("query is too long")
    count = max(1, min(8, int(count)))
    key = (query.lower(), count, time_range)
    cached = _CACHE.get(key)
    if isinstance(cached, SearchResult):
        return cached

    try:
        parsed = parse_searxng(_fetch_searxng(_searxng_url(query, time_range)))
    except SearchError:
        raise
    except Exception as error:
        raise SearchError(f"searxng {error}") from error

    if not parsed.hits and parsed.unresponsive:
        raise SearchError(
            "searxng engines failed: " + "; ".join(parsed.unresponsive)
        )

    result = SearchResult(
        query=query,
        engine="searxng",
        hits=parsed.hits[:count],
    )
    _CACHE.set(key, result)
    return result

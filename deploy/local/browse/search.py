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


class SearchError(RuntimeError):
    pass


class TTLCache:
    def __init__(self, ttl: float):
        self._ttl = ttl
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
            self._data[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_CACHE = TTLCache(300)


def parse_searxng(payload: str) -> list[SearchHit]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SearchError(f"searxng json parse failed: {error}") from error
    if not isinstance(data, dict):
        raise SearchError("searxng response is not an object")

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=(item.get("title") or "").strip(),
                url=url,
                snippet=(item.get("content") or "").strip(),
            )
        )
    return hits


def _searxng_url(query: str, time_range: str | None) -> str:
    params = {"q": query, "format": "json"}
    if time_range:
        params["time_range"] = time_range
    return f"{SEARXNG_URL}/search?{urlencode(params)}"


def _fetch_searxng(url: str) -> str:
    response = httpx.get(url, timeout=6.0)
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
    count = max(1, min(8, int(count)))
    key = (query.lower(), count, time_range)
    cached = _CACHE.get(key)
    if isinstance(cached, SearchResult):
        return cached

    try:
        hits = parse_searxng(_fetch_searxng(_searxng_url(query, time_range)))[:count]
    except SearchError:
        raise
    except Exception as error:
        raise SearchError(f"searxng {error}") from error

    result = SearchResult(query=query, engine="searxng", hits=hits)
    _CACHE.set(key, result)
    return result

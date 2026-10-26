import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from primp import Client as PrimpClient

from fetch import USER_AGENT


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


SEARCH_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
_BRAVE_TF = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
_BING_FILTER = {"day": "ez1", "week": "ez2", "month": "ez3"}
_BRAVE_LOCK = threading.Lock()
_LAST_BRAVE = 0.0
_CACHE = TTLCache(300)


def _plain_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_brave(html: str) -> list[SearchHit]:
    soup = BeautifulSoup(html, "lxml")
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for block in soup.select("div.snippet"):
        title_element = block.select_one(".search-snippet-title")
        anchor = block.find("a", href=True)
        if not title_element or not anchor:
            continue
        url = anchor["href"]
        if not url.startswith(("http://", "https://")):
            continue
        if "search.brave.com" in url or url in seen:
            continue
        seen.add(url)
        title = (
            title_element.get("title") or title_element.get_text(" ", strip=True)
        ).strip()
        snippet_element = block.select_one(
            ".generic-snippet .content"
        ) or block.select_one(".generic-snippet")
        snippet = (
            snippet_element.get_text(" ", strip=True) if snippet_element else ""
        )
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
    return hits


def parse_bing_rss(xml: str) -> list[SearchHit]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise SearchError(f"bing rss parse failed: {error}") from error

    hits: list[SearchHit] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        url = (item.findtext("link") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=_plain_text(item.findtext("title") or ""),
                url=url,
                snippet=_plain_text(item.findtext("description") or ""),
            )
        )
    return hits


def _brave_url(query: str, time_range: str | None) -> str:
    params = {"q": query}
    value = _BRAVE_TF.get(time_range or "")
    if value:
        params["tf"] = value
    return f"https://search.brave.com/search?{urlencode(params)}"


def _bing_url(query: str, time_range: str | None) -> str:
    params = {"format": "rss", "setlang": "en", "q": query}
    value = _BING_FILTER.get(time_range or "")
    if value:
        params["filters"] = f'ex1:"{value}"'
    return f"https://www.bing.com/search?{urlencode(params)}"


def _fetch_brave(url: str) -> str:
    response = httpx.get(
        url,
        headers=SEARCH_HEADERS,
        timeout=3.5,
        follow_redirects=True,
    )
    if response.status_code != 200:
        raise SearchError(f"brave returned {response.status_code}")
    return response.text


def _fetch_bing(url: str) -> str:
    with PrimpClient(impersonate="chrome", timeout=5) as client:
        response = client.get(url)
    if response.status_code != 200:
        raise SearchError(f"bing returned {response.status_code}")
    return response.text


def _throttle() -> None:
    global _LAST_BRAVE
    with _BRAVE_LOCK:
        wait = 1.0 - (time.monotonic() - _LAST_BRAVE)
        if wait > 0:
            time.sleep(wait)
        _LAST_BRAVE = time.monotonic()


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

    errors: list[str] = []
    try:
        _throttle()
        hits = parse_brave(_fetch_brave(_brave_url(query, time_range)))[:count]
        if hits:
            result = SearchResult(query=query, engine="brave", hits=hits)
            _CACHE.set(key, result)
            return result
    except Exception as error:
        errors.append(f"brave {error}")

    try:
        hits = parse_bing_rss(_fetch_bing(_bing_url(query, time_range)))[:count]
        if hits:
            result = SearchResult(query=query, engine="bing", hits=hits)
            _CACHE.set(key, result)
            return result
    except Exception as error:
        errors.append(f"bing {error}")

    if errors:
        raise SearchError("; ".join(errors))
    result = SearchResult(query=query, engine="none", hits=[])
    _CACHE.set(key, result)
    return result

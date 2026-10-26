import base64
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup


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


def decode_bing_url(href: str) -> str:
    parts = urlsplit(href)
    if "bing.com" not in parts.netloc or not parts.path.startswith("/ck/a"):
        return href
    values = parse_qs(parts.query).get("u")
    if not values:
        return href
    value = values[0]
    if not value.startswith("a1"):
        return href
    raw = value[2:]
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding).decode("utf-8")
    except Exception:
        return href


def parse_bing(html: str) -> list[SearchHit]:
    soup = BeautifulSoup(html, "lxml")
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for block in soup.select("li.b_algo"):
        anchor = block.select_one("h2 a")
        if not anchor:
            continue
        url = decode_bing_url(anchor.get("href", ""))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        title = anchor.get_text(" ", strip=True)
        snippet_element = block.select_one(".b_caption p") or block.select_one("p")
        snippet = (
            snippet_element.get_text(" ", strip=True) if snippet_element else ""
        )
        hits.append(SearchHit(title=title, url=url, snippet=snippet))
    return hits

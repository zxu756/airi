import ipaddress
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura
from bs4 import BeautifulSoup, UnicodeDammit

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="browse-dns")


class UrlBlocked(ValueError):
    pass


class UnsupportedContent(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedPage:
    title: str
    text: str
    fallback: bool


@dataclass(frozen=True)
class FetchedPage:
    status: int
    final_url: str
    content_type: str
    html: str
    truncated: bool


def _title_from_html(html: str, url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    if soup.title:
        title = soup.title.get_text(" ", strip=True)
        if title:
            return title
    try:
        metadata = trafilatura.extract_metadata(html, default_url=url)
        if metadata and metadata.title:
            title = metadata.title.strip()
            if title:
                return title
    except Exception:
        pass
    return urlsplit(url).hostname or ""


def extract_page(html: str, url: str) -> ExtractedPage:
    try:
        text = trafilatura.extract(
            html,
            url=url,
            include_tables=True,
            include_comments=False,
            favor_recall=True,
        )
    except Exception:
        text = None

    if text:
        text = text.strip()
    fallback = not text
    if fallback:
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return ExtractedPage(
        title=_title_from_html(html, url),
        text=text or "",
        fallback=fallback,
    )


def is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global and not address.is_multicast


def _decode_body(body: bytes, content_type_header: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type_header, re.I)
    if match:
        try:
            return body.decode(match.group(1), errors="replace")
        except LookupError:
            pass
    detector = UnicodeDammit(body, is_html=True)
    return detector.unicode_markup or body.decode("utf-8", errors="replace")


def validate_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UrlBlocked("URL must use http or https")
    if not parts.hostname:
        raise UrlBlocked("URL must include a host")
    if parts.username or parts.password:
        raise UrlBlocked("URL must not include credentials")

    try:
        port = parts.port
    except ValueError as error:
        raise UrlBlocked("URL port is invalid") from error

    if port is None:
        port = 443 if parts.scheme == "https" else 80
    if port < 1024 and port not in (80, 443):
        raise UrlBlocked("URL port is not allowed")

    try:
        future = _DNS_POOL.submit(
            socket.getaddrinfo,
            parts.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
        addresses = future.result(timeout=2.0)
    except FutureTimeout as error:
        raise UrlBlocked("URL host lookup timed out") from error
    except socket.gaierror as error:
        raise UrlBlocked(f"URL host cannot be resolved: {parts.hostname}") from error

    if not addresses:
        raise UrlBlocked("URL host has no addresses")
    for address in addresses:
        if not is_public_ip(address[4][0]):
            raise UrlBlocked("URL resolves to a non-public address")
    return url


def fetch_page(
    url: str,
    *,
    max_bytes: int = 2_097_152,
    timeout: float = 6.0,
    max_redirects: int = 3,
) -> FetchedPage:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    current = url
    deadline = time.monotonic() + timeout
    with httpx.Client(follow_redirects=False, trust_env=False) as client:
        for _ in range(max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpx.TimeoutException("total deadline")
            validate_url(current)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpx.TimeoutException("total deadline")
            with client.stream(
                "GET",
                current,
                headers=headers,
                timeout=remaining,
            ) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise UrlBlocked("Redirect without Location")
                    current = urljoin(current, location)
                    continue

                content_type_header = response.headers.get("content-type", "")
                content_type = (
                    content_type_header
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise UnsupportedContent(
                        f"Unsupported content type: {content_type or 'unknown'}"
                    )

                chunks: list[bytes] = []
                total = 0
                truncated = False
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise httpx.TimeoutException("total deadline")
                    if not chunk:
                        continue
                    remaining = max_bytes - total
                    if remaining <= 0:
                        truncated = True
                        break
                    if len(chunk) > remaining:
                        chunks.append(chunk[:remaining])
                        total += remaining
                        truncated = True
                        break
                    chunks.append(chunk)
                    total += len(chunk)

                body = b"".join(chunks)
                return FetchedPage(
                    status=response.status_code,
                    final_url=str(response.url),
                    content_type=content_type,
                    html=_decode_body(body, content_type_header),
                    truncated=truncated,
                )

    raise UrlBlocked("Too many redirects")

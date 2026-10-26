import ipaddress
import socket
from urllib.parse import urlsplit


class UrlBlocked(ValueError):
    pass


def is_public_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


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
        addresses = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise UrlBlocked(f"URL host cannot be resolved: {parts.hostname}") from error

    if not addresses:
        raise UrlBlocked("URL host has no addresses")
    for address in addresses:
        if not is_public_ip(address[4][0]):
            raise UrlBlocked("URL resolves to a non-public address")
    return url

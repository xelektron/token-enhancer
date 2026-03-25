"""
url_validator.py — SSRF protection for token-enhancer
Rejects anything that isn't a public HTTPS URL.
"""

import ipaddress
import socket
from urllib.parse import urlparse


# RFC 1918 + loopback + link-local + other reserved ranges
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),    # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),   # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),    # Tailscale / CGNAT
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
]

# Batch hard limit
MAX_BATCH_URLS = 10


class URLValidationError(ValueError):
    pass


def validate_url(url: str) -> str:
    """
    Validate that a URL is a public HTTPS target.
    Returns the URL unchanged if valid, raises URLValidationError otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        raise URLValidationError("URL must be a non-empty string.")

    parsed = urlparse(url)

    # Schema must be https
    if parsed.scheme != "https":
        raise URLValidationError(
            f"Only HTTPS URLs are allowed (got scheme: '{parsed.scheme}')."
        )

    hostname = parsed.hostname
    if not hostname:
        raise URLValidationError("URL has no hostname.")

    # Resolve hostname to IP and check against blocked ranges
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise URLValidationError(f"Cannot resolve hostname '{hostname}': {e}")

    for info in infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for network in _BLOCKED_NETWORKS:
            if addr in network:
                raise URLValidationError(
                    f"URL resolves to a private/reserved address ({addr_str}). "
                    "SSRF protection rejected this request."
                )

    return url


def validate_batch(urls: list) -> list:
    """
    Validate a list of URLs. Raises URLValidationError on the first
    invalid entry or if the batch exceeds MAX_BATCH_URLS.
    """
    if not isinstance(urls, list):
        raise URLValidationError("'urls' must be a list.")
    if len(urls) > MAX_BATCH_URLS:
        raise URLValidationError(
            f"Batch size {len(urls)} exceeds maximum of {MAX_BATCH_URLS}."
        )
    for url in urls:
        validate_url(url)
    return urls

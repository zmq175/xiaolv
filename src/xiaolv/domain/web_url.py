"""Syntactic URL eligibility; provider DNS and redirect checks are separate."""

import ipaddress

import httpx


def eligible_page_url(source: str) -> bool:
    if not source or len(source) > 8192 or any(ord(char) < 33 for char in source) or "\\" in source:
        return False
    try:
        url = httpx.URL(source)
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.port not in (None, 80 if url.scheme == "http" else 443)
            or "%" in url.host
        ):
            return False
        host = url.host.rstrip(".").lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return (
                "." in host
                and not all(part.isdigit() for part in host.split("."))
                and not host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))
            )
        return address.is_global and not address.is_multicast and not address.is_reserved
    except (httpx.InvalidURL, ValueError):
        return False

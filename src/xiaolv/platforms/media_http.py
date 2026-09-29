"""Bounded public media downloads with address pinning and original TLS identity."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from xiaolv.application.inbound_speech import MediaUnavailable


@dataclass(frozen=True)
class ImageBytes:
    data: bytes
    content_type: str


async def resolve_public_candidate(host: str, port: int) -> tuple[str, ...]:
    rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(row[4][0]) for row in rows))


class MediaDownloader:
    def __init__(
        self,
        *,
        resolver: Callable[[str, int], Awaitable[tuple[str, ...]]] = resolve_public_candidate,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._max_bytes = max_bytes

    async def fetch(self, source: str, expires_at: datetime) -> ImageBytes:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError()
        async with asyncio.timeout(min(5, remaining)):
            if any(char.isspace() or ord(char) < 32 for char in source):
                raise MediaUnavailable()
            url = httpx.URL(source)
            if (
                url.scheme != "https"
                or not url.host
                or url.port not in (None, 443)
                or url.username
                or url.password
                or url.fragment
                or "%" in url.host
            ):
                raise MediaUnavailable()
            addresses = await self._resolver(url.host, url.port or 443)
            if not addresses:
                raise MediaUnavailable()
            for raw in addresses:
                ip = ipaddress.ip_address(raw)
                if (
                    not ip.is_global
                    or ip.is_multicast
                    or ip.is_reserved
                    or (
                        isinstance(ip, ipaddress.IPv6Address)
                        and (
                            ip.ipv4_mapped is not None
                            or ip.sixtofour is not None
                            or ip.teredo is not None
                            or ip in ipaddress.ip_network("64:ff9b::/96")
                            or ip in ipaddress.ip_network("64:ff9b:1::/48")
                        )
                    )
                ):
                    raise MediaUnavailable()
            address = str(ipaddress.ip_address(addresses[0]))
            pinned = url.copy_with(host=address)
            async with self._transport or httpx.AsyncHTTPTransport(
                retries=0, trust_env=False
            ) as transport:
                request = httpx.Request(
                    "GET",
                    pinned,
                    headers={"Host": url.netloc.decode("ascii"), "Accept-Encoding": "identity"},
                    extensions={"sni_hostname": url.host},
                )
                # The public transport avoids the high-level client's INFO log of signed URLs.
                response = await transport.handle_async_request(request)
                try:
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise MediaUnavailable()
                    content_type = (
                        response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    )
                    if response.status_code != 200 or content_type not in {
                        "image/png",
                        "image/jpeg",
                        "image/webp",
                        "image/gif",
                    }:
                        raise MediaUnavailable()
                    declared = response.headers.get("content-length")
                    if declared is not None and not 0 <= int(declared) <= self._max_bytes:
                        raise MediaUnavailable()
                    data = bytearray()
                    if response.is_stream_consumed:
                        data.extend(response.content)
                    else:
                        async for chunk in response.aiter_raw():
                            if len(data) + len(chunk) > self._max_bytes:
                                raise MediaUnavailable()
                            data.extend(chunk)
                    if not data or len(data) > self._max_bytes:
                        raise MediaUnavailable()
                    return ImageBytes(bytes(data), content_type)
                finally:
                    await response.aclose()

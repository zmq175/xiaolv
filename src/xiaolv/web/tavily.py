"""Official Tavily SDK adapter; not wired online until persistent credits exist."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import TracebackType
from typing import Self
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tavily import AsyncTavilyClient  # type: ignore[import-untyped]

from xiaolv.domain.web import SearchHit, ToolUnavailable
from xiaolv.domain.web_credits import WebCredits


class _Hit(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    title: str = Field(max_length=4096)
    url: str = Field(min_length=1, max_length=8192)
    content: str = Field(max_length=100000)


class _SearchResponse(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    results: list[_Hit] = Field(max_length=5)


class TavilySearchProvider:
    def __init__(
        self,
        *,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        credits: WebCredits | None = None,
    ) -> None:
        self._credits = credits
        self._http = httpx.AsyncClient(
            base_url="https://api.tavily.com",
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},
            event_hooks={"response": [_bound_response]},
        )
        self._sdk = AsyncTavilyClient(api_key=api_key, client=self._http)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._http.aclose()

    async def search(self, query: str, count: int, expires_at: datetime) -> tuple[SearchHit, ...]:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError()
        call_id = uuid4().hex
        charged = None
        async with asyncio.timeout(remaining):
            if self._credits is not None:
                await self._credits.reserve(call_id, "search", expires_at)
            try:
                response = await self._sdk.search(
                    query=query,
                    max_results=count,
                    search_depth="basic",
                    auto_parameters=False,
                    include_usage=True,
                    include_answer=False,
                    include_raw_content=False,
                    include_images=False,
                    timeout=min(remaining, 8),
                )
                charged = _parse_credits(response.get("usage"))
                parsed = _SearchResponse.model_validate(response)
                return tuple(
                    SearchHit(hit.title, hit.url, hit.content) for hit in parsed.results[:count]
                )
            finally:
                if self._credits is not None:
                    await asyncio.shield(self._settle(call_id, charged))

    async def _settle(self, call_id: str, charged: Decimal | None) -> None:
        assert self._credits is not None
        async with asyncio.timeout(2):
            await self._credits.settle(call_id, charged)


def _parse_credits(usage: object) -> Decimal | None:
    if not isinstance(usage, dict) or type(usage.get("credits")) not in (int, float):
        return None
    try:
        value = Decimal(str(usage["credits"]))
        if (
            value.is_finite()
            and 0 <= value <= 1000000
            and value == value.quantize(Decimal("0.000001"))
        ):
            return value
    except InvalidOperation:
        pass
    return None


async def _bound_response(response: httpx.Response) -> None:
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        await response.aclose()
        raise ToolUnavailable()
    if response.is_stream_consumed:
        if len(response.content) > 1048576:
            await response.aclose()
            raise ToolUnavailable()
    elif isinstance(response.stream, httpx.AsyncByteStream):
        response.stream = _BoundedBody(response.stream)


class _BoundedBody(httpx.AsyncByteStream):
    def __init__(self, source: httpx.AsyncByteStream) -> None:
        self._source = source

    async def __aiter__(self) -> AsyncIterator[bytes]:
        size = 0
        try:
            async for chunk in self._source:
                size += len(chunk)
                if size > 1048576:
                    raise ToolUnavailable()
                yield chunk
        finally:
            await self._source.aclose()

    async def aclose(self) -> None:
        await self._source.aclose()

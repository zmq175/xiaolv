"""Persistent search credit constraints observed through the chat entrypoint."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from test_web_tools import run_tool_scenario, search_call


async def run_search(engine, *, credits, failure=None, started=None, release=None, limit=1):
    from xiaolv.storage.web_credits import PostgresWebCredits
    from xiaolv.web.tavily import TavilySearchProvider

    requests = []

    async def serve(request):
        requests.append(json.loads(request.content))
        if started is not None:
            started.set()
        if release is not None:
            await release.wait()
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if failure == "reject":
            return httpx.Response(429, json={"error": "synthetic rate limit"})
        result = {"results": []}
        if credits is not None:
            result["usage"] = {"credits": credits}
        return httpx.Response(200, json=result)

    def plan(body):
        return [] if any(m["role"] == "tool" for m in body["messages"]) else [search_call()]

    async with TavilySearchProvider(
        api_key="synthetic",
        transport=httpx.MockTransport(serve),
        credits=PostgresWebCredits(engine, monthly_limit=limit),
    ) as provider:
        outcome, sent, _ = await run_tool_scenario(search_api=provider, plan=plan)
    return outcome, sent, requests


@pytest.mark.parametrize("credits", [0, 1, None, False, -1, "0"])
async def test_search_credits_survive_rebuilding_service(database_url, credits):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_search(engine, credits=credits)
        assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
    finally:
        await engine.dispose()

    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_search(rebuilt, credits=1)
        if type(credits) is int and credits == 0:
            assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
        else:
            assert outcome == "budget_denied" and sent == [] and requests == []
    finally:
        await rebuilt.dispose()


@pytest.mark.parametrize("failure", ["timeout", "reject"])
async def test_failed_search_keeps_reserved_credits_after_restart(database_url, failure):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_search(engine, credits=1, failure=failure)
        assert outcome == "tool_error" and sent == [] and len(requests) == 1
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_search(rebuilt, credits=1)
        assert outcome == "budget_denied" and sent == [] and requests == []
    finally:
        await rebuilt.dispose()


async def test_two_services_cannot_spend_the_same_last_credit(database_url):
    first = create_async_engine(database_url, hide_parameters=True)
    second = create_async_engine(database_url, hide_parameters=True)
    started, release = asyncio.Event(), asyncio.Event()
    pending = asyncio.create_task(run_search(first, credits=1, started=started, release=release))
    try:
        await asyncio.wait_for(started.wait(), 3)
        outcome, sent, requests = await asyncio.wait_for(run_search(second, credits=1), 3)
        assert outcome == "budget_denied" and sent == [] and requests == []
        release.set()
        outcome, sent, requests = await asyncio.wait_for(pending, 3)
        assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await first.dispose()
        await second.dispose()


async def test_provider_charge_above_reservation_blocks_further_searches(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_search(engine, credits=2, limit=5)
        assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
        outcome, sent, requests = await run_search(engine, credits=1, limit=5)
        assert outcome == "budget_denied" and sent == [] and requests == []
    finally:
        await engine.dispose()


async def run_extract(engine, *, credits, limit=2, failed=False):
    from test_page_reader import public_dns, read_page

    from xiaolv.storage.web_credits import PostgresWebCredits
    from xiaolv.web.tavily import TavilySearchProvider

    requests = []

    async def serve(request):
        requests.append(request)
        response = {
            "results": []
            if failed
            else [{"url": "https://example.com/article", "raw_content": "合成正文。"}],
            "failed_results": [{"url": "https://example.com/article", "error": "synthetic failure"}]
            if failed
            else [],
        }
        if credits is not None:
            response["usage"] = {"credits": credits}
        return httpx.Response(200, json=response)

    async with TavilySearchProvider(
        api_key="synthetic",
        transport=httpx.MockTransport(serve),
        resolver=public_dns,
        credits=PostgresWebCredits(engine, monthly_limit=limit),
    ) as provider:
        outcome, sent, _ = await read_page(provider)
    return outcome, sent, requests


async def test_extract_and_search_share_pool_and_keep_fractional_credits(database_url):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_extract(engine, credits=0.2)
        assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
        outcome, sent, requests = await run_search(engine, credits=1, limit=2)
        assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
    finally:
        await engine.dispose()
    rebuilt = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_extract(rebuilt, credits=0.2)
        assert outcome == "budget_denied" and sent == [] and requests == []
    finally:
        await rebuilt.dispose()


@pytest.mark.parametrize("credits", [0, None])
async def test_failed_extraction_only_releases_explicitly_known_zero_charge(database_url, credits):
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        outcome, sent, requests = await run_extract(engine, credits=credits, limit=1, failed=True)
        assert outcome == "tool_error" and sent == [] and len(requests) == 1
        outcome, sent, requests = await run_search(engine, credits=1, limit=1)
        if credits == 0:
            assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
        else:
            assert outcome == "budget_denied" and sent == [] and requests == []
    finally:
        await engine.dispose()

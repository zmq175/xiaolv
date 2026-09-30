"""Hosted page extraction exercised through native chat tool use."""

import json

import httpx
import pytest
from test_web_tools import run_tool_scenario

from xiaolv.web.tavily import TavilySearchProvider


async def read_page(provider):
    def plan(body):
        if any(message["role"] == "tool" for message in body["messages"]):
            return []
        context = json.loads(body["messages"][1]["content"])
        return [
            {
                "id": "read-1",
                "type": "function",
                "function": {
                    "name": "read_page",
                    "arguments": json.dumps({"url_ref": context["available_urls"][0]["url_ref"]}),
                },
            }
        ]

    return await run_tool_scenario(
        search_api=provider,
        reader=provider,
        plan=plan,
        message="看看这个网页 https://example.com/article",
    )


async def test_native_page_read_uses_official_extract_sdk():
    requests = []

    async def serve(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"url": "https://example.com/article", "raw_content": "合成网页正文。"}
                ],
                "failed_results": [],
                "usage": {"credits": 0.2},
            },
        )

    async with TavilySearchProvider(
        api_key="synthetic", transport=httpx.MockTransport(serve), resolver=public_dns
    ) as provider:
        outcome, sent, model_requests = await read_page(provider)
    assert outcome == "confirmed" and len(sent) == 1 and len(requests) == 1
    assert str(requests[0].url) == "https://api.tavily.com/extract"
    body = json.loads(requests[0].content)
    assert body["urls"] == ["https://example.com/article"]
    assert body["extract_depth"] == "basic" and body["include_usage"] is True
    assert body["format"] == "markdown" and body["include_images"] is False
    result = json.loads(model_requests[-1]["messages"][1]["content"])["tool_results"][0]
    assert result["kind"] == "page_content" and result["text"] == "合成网页正文。"


async def public_dns(host, port):
    return ("93.184.215.14",)


async def test_page_dns_with_private_address_never_calls_extract():
    requests = []

    async def resolver(host, port):
        return ("93.184.215.14", "127.0.0.1")

    async def serve(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/article", "raw_content": "合成正文"}],
                "failed_results": [],
            },
        )

    async with TavilySearchProvider(
        api_key="synthetic",
        transport=httpx.MockTransport(serve),
        resolver=resolver,
    ) as provider:
        outcome, sent, _ = await read_page(provider)
    assert outcome == "tool_error" and sent == [] and requests == []


@pytest.mark.parametrize("mode", ["blank", "different_url", "failed", "redirect"])
async def test_invalid_extraction_does_not_become_a_successful_reply(mode):
    requests = []

    async def serve(request):
        requests.append(request)
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/other"
                        if mode == "different_url"
                        else "https://example.com/article",
                        "raw_content": "   " if mode == "blank" else "合成正文",
                    }
                ],
                "failed_results": [{"url": "https://example.com/article", "error": "failed"}]
                if mode == "failed"
                else [],
            },
        )

    async with TavilySearchProvider(
        api_key="synthetic",
        transport=httpx.MockTransport(serve),
        resolver=public_dns,
    ) as provider:
        outcome, sent, model_requests = await read_page(provider)
    assert outcome == "tool_error" and sent == []
    assert len(requests) == 1 and len(model_requests) == 2

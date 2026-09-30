import json
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from test_chat_model import Platform, stream_json

from xiaolv.application.delivery import DeliveryService
from xiaolv.models.chat_completions import ChatCompletionsGateway
from xiaolv.models.conversation import ChatCompletionsModel
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime


@pytest.mark.parametrize("oversized", [False, True])
async def test_chat_search_uses_native_tool_calls_and_reads_tool_result_before_reply(oversized):
    from xiaolv.application.web_tools import WebTools
    from xiaolv.domain.context_policy import ContextPolicy
    from xiaolv.domain.web import SearchHit

    requests, searches = [], []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append((query, count))
            return (
                SearchHit(
                    "合成公告",
                    "https://example.com/news",
                    "资料" * 1000 if oversized else "合成事件已经发布。",
                ),
            )

    async def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        if "tools" not in body:
            schema = body["response_format"]["json_schema"]["schema"]["properties"]
            return stream_json(
                {"action": "respond"} if "action" in schema else {"text": "查到公告了。"}
            )
        has_result = any(message["role"] == "tool" for message in body["messages"])
        message = {"role": "assistant", "content": "可以回答了。"}
        if not has_result:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query":"合成事件 最新公告","count":2}',
                        },
                    }
                ],
            }
        return httpx2.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "stop" if has_result else "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    clock = lambda: datetime.now(UTC)
    platform = Platform()
    async with ChatCompletionsGateway(
        base_url="https://model.example/v1",
        api_key="synthetic",
        model="synthetic",
        transport=httpx2.MockTransport(serve),
    ) as gateway:
        runtime = TextRuntime(
            ChatCompletionsModel(gateway),
            DeliveryService(platform, clock, lambda _: 1),
            clock,
            web_tools=WebTools(
                gateway,
                SearchAPI(),
                conversations=["chat-1"],
                context_policy=ContextPolicy(reply_tokens=1500),
            ),
        )
        outcome = await runtime.run(
            ConversationCandidate(
                "chat-1", "turn", "查一下合成事件的最新公告", clock() + timedelta(seconds=10), 1
            )
        )
    if oversized:
        assert outcome == "context_overflow"
        assert platform.sent == []
        assert len(requests) == 2
        assert searches == [("合成事件 最新公告", 2)]
        return
    assert outcome == "confirmed" and len(platform.sent) == 1
    assert searches == [("合成事件 最新公告", 2)]
    assert len(requests) == 4
    assert requests[1]["tools"][0]["type"] == "function"
    assert requests[1]["parallel_tool_calls"] is False
    assert requests[2]["messages"][-1]["role"] == "tool"
    assert requests[2]["messages"][-1]["tool_call_id"] == "search-1"
    final_context = json.loads(requests[-1]["messages"][1]["content"])
    assert final_context["tool_results"][0]["kind"] == "search_snippets"
    assert final_context["tool_results"][0]["hits"][0]["url"] == "https://example.com/news"


async def test_invalid_tool_batch_does_not_start_any_external_search():
    from xiaolv.application.web_tools import WebTools

    searches = []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append(query)
            return ()

    async def serve(request):
        body = json.loads(request.content)
        if "tools" not in body:
            return stream_json({"action": "respond"})
        return httpx2.Response(
            200,
            json={
                "id": "synthetic",
                "object": "chat.completion",
                "created": 0,
                "model": "synthetic",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "valid",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query":"合成公告","count":1}',
                                    },
                                },
                                {
                                    "id": "invalid",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": '{"query":"合成公告","count":true}',
                                    },
                                },
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
            },
        )

    clock = lambda: datetime.now(UTC)
    platform = Platform()
    async with ChatCompletionsGateway(
        base_url="https://model.example/v1",
        api_key="synthetic",
        model="synthetic",
        transport=httpx2.MockTransport(serve),
    ) as gateway:
        runtime = TextRuntime(
            ChatCompletionsModel(gateway),
            DeliveryService(platform, clock, lambda _: 1),
            clock,
            web_tools=WebTools(gateway, SearchAPI(), conversations=["chat-1"]),
        )
        outcome = await runtime.run(
            ConversationCandidate(
                "chat-1", "turn", "查一下合成公告", clock() + timedelta(seconds=10), 1
            )
        )
    assert searches == []
    assert outcome == "tool_error"
    assert platform.sent == []

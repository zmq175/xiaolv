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


async def run_tool_scenario(
    *,
    search_api,
    plan,
    decision="respond",
    conversations=("chat-1",),
    reader=None,
    message="查询合成资料",
):
    """Exercise the approved chat boundary with external model and search responses."""
    from xiaolv.application.web_tools import WebTools

    requests = []

    async def serve(request):
        body = json.loads(request.content)
        requests.append(body)
        if "tools" not in body:
            schema = body["response_format"]["json_schema"]["schema"]["properties"]
            return stream_json({"action": decision} if "action" in schema else {"text": "你好。"})
        calls = plan(body)
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
                        "finish_reason": "tool_calls" if calls else "stop",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": calls or None,
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
            web_tools=WebTools(gateway, search_api, conversations=conversations, reader=reader),
        )
        outcome = await runtime.run(
            ConversationCandidate("chat-1", "turn", message, clock() + timedelta(seconds=10), 1)
        )
    return outcome, platform.sent, requests


def search_call(query="合成公告", call_id="search-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "web_search",
            "arguments": json.dumps({"query": query, "count": 1}),
        },
    }


@pytest.mark.parametrize("failure", [RuntimeError("synthetic provider failure"), TimeoutError()])
async def test_search_failure_is_a_tool_failure_without_retry_or_reply(failure):
    searches = []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append(query)
            raise failure

    outcome, sent, requests = await run_tool_scenario(
        search_api=SearchAPI(),
        plan=lambda _: [search_call()],
    )
    assert outcome == "tool_error"
    assert searches == ["合成公告"]
    assert len(requests) == 2
    assert sent == []


async def test_reused_tool_call_id_in_later_round_does_not_search_again():
    searches = []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append(query)
            return ()

    def plan(body):
        has_result = any(message["role"] == "tool" for message in body["messages"])
        return [search_call("另一份合成资料" if has_result else "合成公告")]

    outcome, sent, requests = await run_tool_scenario(search_api=SearchAPI(), plan=plan)
    assert searches == ["合成公告"]
    assert outcome == "tool_error"
    assert len(requests) == 3
    assert sent == []


@pytest.mark.parametrize("mode", ["silence", "ungranted", "no_tool"])
async def test_chat_can_remain_silent_or_reply_without_external_search(mode):
    searches = []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append(query)
            return ()

    outcome, sent, requests = await run_tool_scenario(
        search_api=SearchAPI(),
        plan=lambda _: [],
        decision="silence" if mode == "silence" else "respond",
        conversations=() if mode == "ungranted" else ("chat-1",),
    )
    assert searches == []
    assert outcome == ("silence" if mode == "silence" else "confirmed")
    assert len(sent) == (0 if mode == "silence" else 1)
    assert len(requests) == {"silence": 1, "ungranted": 2, "no_tool": 3}[mode]
    assert sum("tools" in request for request in requests) == (mode == "no_tool")


async def test_chat_search_uses_official_tavily_sdk_with_explicit_basic_parameters():
    import httpx

    from xiaolv.web.tavily import TavilySearchProvider

    searches = []

    async def search_response(request):
        searches.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "合成公告", "url": "https://example.com/news", "content": "已发布。"}
                ],
                "usage": {"credits": 1},
                "request_id": "synthetic-search",
            },
        )

    def plan(body):
        return [] if any(m["role"] == "tool" for m in body["messages"]) else [search_call()]

    async with TavilySearchProvider(
        api_key="synthetic",
        transport=httpx.MockTransport(search_response),
    ) as provider:
        outcome, sent, requests = await run_tool_scenario(search_api=provider, plan=plan)
    assert outcome == "confirmed" and len(sent) == 1
    assert len(searches) == 1
    assert str(searches[0].url) == "https://api.tavily.com/search"
    payload = json.loads(searches[0].content)
    assert payload["query"] == "合成公告"
    assert payload["search_depth"] == "basic"
    assert payload["auto_parameters"] is False
    assert payload["include_usage"] is True
    assert payload["include_raw_content"] is False
    assert payload["include_answer"] is False
    assert payload["max_results"] == 1
    context = json.loads(requests[-1]["messages"][1]["content"])
    assert context["tool_results"][0]["hits"][0]["snippet"] == "已发布。"


async def test_oversized_tavily_response_stops_reading_before_json_decode():
    import httpx

    from xiaolv.web.tavily import TavilySearchProvider

    consumed, closed = [], []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"results": [], "padding": "'
            for i in range(64):
                consumed.append(i)
                yield b"x" * 65536
            yield b'"}'

        async def aclose(self):
            closed.append(True)

    async def serve(request):
        return httpx.Response(200, stream=Body())

    def plan(body):
        return [] if any(m["role"] == "tool" for m in body["messages"]) else [search_call()]

    async with TavilySearchProvider(
        api_key="synthetic", transport=httpx.MockTransport(serve)
    ) as provider:
        outcome, sent, requests = await run_tool_scenario(search_api=provider, plan=plan)
    assert outcome == "tool_error"
    assert len(consumed) <= 17
    assert closed
    assert sent == [] and len(requests) == 2


@pytest.mark.parametrize("long_page", [False, True])
async def test_chat_reads_a_message_url_by_reference_without_searching(long_page):
    reads, searches = [], []

    class SearchAPI:
        async def search(self, query, count, expires_at):
            searches.append(query)
            return ()

    class ReaderAPI:
        async def read(self, url, expires_at):
            reads.append(url)
            return "资料" * 10000 if long_page else "网页正文：合成公告已经发布。"

    def plan(body):
        if any(m["role"] == "tool" for m in body["messages"]):
            return []
        context = json.loads(body["messages"][1]["content"])
        refs = context["available_urls"]
        assert len(refs) == 1 and refs[0]["url"] == "https://example.com/news"
        return [
            {
                "id": "read-1",
                "type": "function",
                "function": {
                    "name": "read_page",
                    "arguments": json.dumps({"url_ref": refs[0]["url_ref"]}),
                },
            }
        ]

    outcome, sent, requests = await run_tool_scenario(
        search_api=SearchAPI(),
        reader=ReaderAPI(),
        plan=plan,
        message="看看这个公告 https://example.com/news",
    )
    assert outcome == "confirmed" and len(sent) == 1
    assert reads == ["https://example.com/news"] and searches == []
    result = json.loads(requests[-1]["messages"][1]["content"])["tool_results"][0]
    assert result["kind"] == "page_content"
    assert result["url"] == "https://example.com/news"
    if long_page:
        assert 0 < len(result["text"]) < 20000
    else:
        assert result["text"] == "网页正文：合成公告已经发布。"
    assert result["truncated"] is long_page
    assert result["retrieved_at"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://10.0.0.1/",
        "https://user:secret@example.com/private",
        "http://localhost/admin",
        "http://2130706433/admin",
        "https://example.com:8443/admin",
    ],
)
async def test_private_or_credential_urls_are_not_offered_to_page_reader(url):
    reads = []

    class APIs:
        async def search(self, query, count, expires_at):
            return ()

        async def read(self, url, expires_at):
            reads.append(url)
            return "should not read"

    def plan(body):
        if any(m["role"] == "tool" for m in body["messages"]):
            return []
        refs = json.loads(body["messages"][1]["content"]).get("available_urls", [])
        if not refs:
            return []
        return [
            {
                "id": "read-1",
                "type": "function",
                "function": {
                    "name": "read_page",
                    "arguments": json.dumps({"url_ref": refs[0]["url_ref"]}),
                },
            }
        ]

    api = APIs()
    outcome, _, _ = await run_tool_scenario(search_api=api, reader=api, plan=plan, message=url)
    assert outcome == "confirmed"
    assert reads == []


async def test_search_result_can_be_read_in_next_native_tool_round():
    from xiaolv.domain.web import SearchHit

    reads = []

    class APIs:
        async def search(self, query, count, expires_at):
            return (SearchHit("合成来源", "https://example.com/source", "这里只是摘要。"),)

        async def read(self, url, expires_at):
            reads.append(url)
            return "来源正文。"

    def plan(body):
        results = [json.loads(m["content"]) for m in body["messages"] if m["role"] == "tool"]
        if not results:
            return [search_call()]
        if len(results) == 1:
            return [
                {
                    "id": "read-1",
                    "type": "function",
                    "function": {
                        "name": "read_page",
                        "arguments": json.dumps({"url_ref": results[0]["hits"][0]["url_ref"]}),
                    },
                }
            ]
        return []

    api = APIs()
    outcome, sent, requests = await run_tool_scenario(search_api=api, reader=api, plan=plan)
    assert outcome == "confirmed" and len(sent) == 1
    assert reads == ["https://example.com/source"]
    evidence = json.loads(requests[-1]["messages"][1]["content"])["tool_results"]
    assert [item["kind"] for item in evidence] == ["search_snippets", "page_content"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"url_ref": "made-up-or-another-turn-ref"},
        {"url": "https://example.com/forged"},
    ],
)
async def test_read_page_rejects_unregistered_or_raw_model_urls(arguments):
    reads = []

    class APIs:
        async def search(self, query, count, expires_at):
            return ()

        async def read(self, url, expires_at):
            reads.append(url)
            return "should not read"

    def plan(body):
        return [
            {
                "id": "read-1",
                "type": "function",
                "function": {
                    "name": "read_page",
                    "arguments": json.dumps(arguments),
                },
            }
        ]

    api = APIs()
    outcome, sent, requests = await run_tool_scenario(search_api=api, reader=api, plan=plan)
    assert outcome == "tool_error" and reads == [] and sent == []
    assert len(requests) == 2

"""Chat Completions protocol adapter; streams stay inside the model boundary."""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from math import isfinite
from types import TracebackType
from typing import Any, Literal, Self, cast
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from xiaolv.domain.model_budget import ModelBudget, ModelCallIntent
from xiaolv.domain.model_usage import ModelCallReport, TokenUsage


class ChatCompletionsGateway:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
        first_token_seconds: float = 12,
        idle_seconds: float = 8,
        concurrency: int = 2,
        max_response_bytes: int = 65536,
        usage_sink: Callable[[ModelCallReport], Awaitable[None]] | None = None,
        budget: ModelBudget | None = None,
    ) -> None:
        if not all(
            isinstance(value, str) and value.strip() for value in (base_url, api_key, model)
        ):
            raise ValueError("invalid model configuration")
        try:
            parsed = urlsplit(base_url)
            valid_url = (
                parsed.hostname
                and parsed.port != 0
                and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
                and not any(char.isspace() for char in base_url)
                and (
                    parsed.scheme == "https"
                    or (
                        parsed.scheme == "http"
                        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                    )
                )
            )
        except ValueError:
            valid_url = False
        if not valid_url or not api_key.isascii() or any(char.isspace() for char in api_key):
            raise ValueError("invalid model configuration endpoint or credential")
        if (
            any(
                type(value) not in (int, float) or not isfinite(value) or value <= 0
                for value in (first_token_seconds, idle_seconds)
            )
            or type(concurrency) is not int
            or concurrency <= 0
            or type(max_response_bytes) is not int
            or max_response_bytes <= 0
        ):
            raise ValueError("invalid model configuration limits")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": "Bearer " + api_key},
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=None,  # Stage and absolute deadlines cover connect, headers and body.
        )
        self._model = model
        self._first_token_seconds = first_token_seconds
        self._idle_seconds = idle_seconds
        self._slots = asyncio.Semaphore(concurrency)
        self._max_response_bytes = max_response_bytes
        self._usage_sink = usage_sink
        self._budget = budget

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, traceback)

    async def generate(
        self, *, instructions: str, context: str, schema: dict[str, Any], expires_at: datetime
    ) -> str:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError("model deadline expired")
        async with asyncio.timeout(remaining), self._slots:
            started_at = datetime.now(UTC)
            call_id = uuid4().hex
            if self._budget is not None:
                encoded = json.dumps(
                    {"instructions": instructions, "context": context, "schema": schema},
                    ensure_ascii=False,
                ).encode("utf-8")
                await self._budget.reserve(
                    ModelCallIntent(call_id, self._model, started_at, len(encoded) + 1024, 512)
                )
            usage = None
            status: Literal["completed", "failed", "cancelled"] = "failed"
            try:
                output, usage = await self._generate(
                    instructions=instructions, context=context, schema=schema
                )
                status = "completed"
                return output
            except asyncio.CancelledError:
                status = "cancelled"
                raise
            finally:
                if self._usage_sink is not None or self._budget is not None:
                    await asyncio.shield(
                        self._record(
                            ModelCallReport(
                                call_id,
                                self._model,
                                started_at,
                                datetime.now(UTC),
                                status,
                                usage,
                            )
                        )
                    )

    async def _record(self, report: ModelCallReport) -> None:
        async with asyncio.timeout(2):
            if self._budget is not None:
                await self._budget.settle(report)
            if self._usage_sink is not None:
                await self._usage_sink(report)

    async def _generate(
        self, *, instructions: str, context: str, schema: dict[str, Any]
    ) -> tuple[str, TokenUsage | None]:
        body = {
            "model": self._model,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": 512,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": context},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "chat_output", "strict": True, "schema": schema},
            },
        }
        output = []
        finished = False
        done = False
        usage = None
        async with (
            asyncio.timeout(self._first_token_seconds) as stage,
            self._client.stream("POST", "chat/completions", json=body) as response,
        ):
            response.raise_for_status()
            async for data in self._events(response):
                if data == "[DONE]":
                    done = True
                    break
                chunk = json.loads(data)
                if finished and chunk.get("choices") == [] and chunk.get("usage") is not None:
                    usage = _parse_usage(chunk["usage"])
                if "error" in chunk:
                    raise ValueError("model stream reported failure")
                for choice in chunk.get("choices", []):
                    if choice.get("index") != 0 or finished:
                        raise ValueError("invalid model stream")
                    delta = choice.get("delta", {})
                    if any(delta.get(key) for key in ("refusal", "tool_calls", "function_call")):
                        raise ValueError("unsupported model output")
                    content = delta.get("content")
                    if content:
                        output.append(content)
                        stage.reschedule(asyncio.get_running_loop().time() + self._idle_seconds)
                    finish = choice.get("finish_reason")
                    if finish is not None:
                        if finish != "stop":
                            raise ValueError("incomplete model output")
                        finished = True
        if not done or not finished:
            raise ValueError("incomplete model stream")
        return "".join(output), usage

    async def _events(self, response: httpx.Response) -> AsyncIterator[str]:
        buffer = b""
        total = 0
        data_lines: list[str] = []
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_response_bytes:
                raise ValueError("model response exceeds byte limit")
            buffer += chunk
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                line = line.removesuffix(b"\r")
                if not line and data_lines:
                    yield "\n".join(data_lines)
                    data_lines.clear()
                elif line.startswith(b"data:"):
                    data_lines.append(line[5:].removeprefix(b" ").decode("utf-8"))


def _parse_usage(raw: object) -> TokenUsage | None:
    if not isinstance(raw, dict):
        return None
    counts = [raw.get(name) for name in ("prompt_tokens", "completion_tokens", "total_tokens")]
    if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in counts):
        return None
    prompt, completion, total = (cast(int, value) for value in counts)
    if total != prompt + completion:
        return None
    details = raw.get("prompt_tokens_details")
    if details is not None and not isinstance(details, dict):
        return None
    cached = details.get("cached_tokens") if details is not None else None
    if cached is not None and (type(cached) is not int or not 0 <= cached <= prompt):
        return None
    return TokenUsage(prompt, completion, total, cached)

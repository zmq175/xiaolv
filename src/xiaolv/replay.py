"""Local scripted demonstration: no live models or IM connections."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.orchestration.text_runtime import ConversationCandidate, TextRuntime


class ScriptedModel:
    async def decide(self, candidate: ConversationCandidate) -> Literal["respond", "silence"]:
        return "silence" if candidate.event_id == "demo-1" else "respond"

    async def reply(self, candidate: ConversationCandidate) -> str:
        return "我也在听，你们继续。"


class ReplayAdapter:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, request: DeliveryRequest) -> Literal["confirmed", "unknown"]:
        self.sent.append(request.text)
        return "confirmed"


async def main() -> None:
    now = datetime.now(UTC)
    platform = ReplayAdapter()
    delivery = DeliveryService(platform, lambda: datetime.now(UTC), lambda _: 1)
    runtime = TextRuntime(ScriptedModel(), delivery, lambda: datetime.now(UTC))
    first = ConversationCandidate("demo-chat", "demo-1", "合成示例", now + timedelta(seconds=45), 1)
    outcomes = [await runtime.run(first), await runtime.run(replace(first, event_id="demo-2"))]
    print(
        json.dumps(
            {"mode": "local_fake_replay", "outcomes": outcomes, "sent": platform.sent},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

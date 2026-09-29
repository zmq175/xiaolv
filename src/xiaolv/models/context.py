"""Bounded complete-message context assembly using an explicit local tokenizer."""

import json
import logging
from typing import Any

from xiaolv.domain.context_policy import ContextOverflow, ContextPolicy
from xiaolv.models.tokenizer import load_tokenizer
from xiaolv.orchestration.text_runtime import ConversationCandidate


class ContextAssembler:
    def __init__(self, policy: ContextPolicy) -> None:
        self.policy = policy
        self.encoding = load_tokenizer(policy.encoding)

    def assemble(
        self,
        candidate: ConversationCandidate,
        instructions: str,
        schema: dict[str, Any],
        stage: str,
        mentions: bool,
    ) -> str:
        events = tuple(reversed(candidate.context.messages))
        if any(event.conversation_id != candidate.conversation_id for event in events):
            raise ValueError("conversation context scope mismatch")
        counts: dict[str, int] = {}
        for event in events:
            counts[event.message_id] = counts.get(event.message_id, 0) + 1
        instruction_tokens = self.count(instructions)
        schema_tokens = self.count(json.dumps(schema, ensure_ascii=False))
        fixed = instruction_tokens + schema_tokens + self.policy.framing_tokens
        limit = self.policy.input_limit(stage)

        def serialize(selected: set[int]) -> str:
            refs = {events[i].message_id: f"message_{i + 1}" for i in selected}
            rows: list[dict[str, Any]] = []
            for i in sorted(selected, reverse=True):
                event = events[i]
                row: dict[str, Any] = {
                    "message_ref": f"message_{i + 1}",
                    "content_version": event.content_version,
                    "account": event.sender_account_id,
                    "name": event.display_name[:128],
                    "text": event.text,
                    "truncated": False,
                    "replies": [
                        {
                            "status": "ambiguous"
                            if counts.get(reference or "", 0) > 1
                            else "resolved"
                            if reference in refs
                            else "missing",
                            "target_ref": refs.get(reference or "")
                            if counts.get(reference or "", 0) == 1
                            else None,
                        }
                        for reference in dict.fromkeys(
                            part.reference for part in event.parts if part.kind == "reply"
                        )
                    ],
                }
                if mentions:
                    row["member_ref"] = f"member_{i + 1}"
                if any(
                    part.kind not in {"text", "mention", "mention_all", "reply"}
                    for part in event.parts
                ):
                    parts: list[dict[str, Any]] = []
                    for index, part in enumerate(event.parts):
                        if part.kind == "text":
                            parts.append({"kind": "text", "text": part.text or ""})
                            continue
                        if part.kind in {"mention", "mention_all", "reply"}:
                            parts.append({"kind": part.kind})
                            continue
                        kind = part.kind
                        if kind in {"face", "mface", "sticker"}:
                            kind = "sticker"
                        elif kind not in {"image", "audio"}:
                            kind = "unsupported"
                        parts.append(
                            {
                                "kind": kind,
                                "media_ref": f"media_{i + 1}_{index + 1}",
                                "status": "unsupported" if kind == "unsupported" else "unprocessed",
                            }
                        )
                        if part.interpretation is not None:
                            parts[-1]["status"] = "interpreted"
                            parts[-1]["interpretation"] = {
                                "kind": part.interpretation.kind,
                                "text": part.interpretation.text,
                                "processor": part.interpretation.processor,
                            }
                    row["parts"] = parts
                rows.append(row)
            return json.dumps(
                {"target_text": candidate.text, "target_truncated": False, "messages": rows},
                ensure_ascii=False,
            )

        source = (
            next(
                (
                    i
                    for i, event in enumerate(events)
                    if event.message_id == candidate.source_message_id
                ),
                None,
            )
            if candidate.source_message_id is not None
            else (0 if events else None)
        )
        if candidate.source_message_id is not None and source is None:
            raise ContextOverflow("trigger_not_loaded")
        selected = {source} if source is not None else set()
        references = (
            {
                part.reference
                for part in events[source].parts
                if part.kind == "reply" and part.reference
            }
            if source is not None
            else set()
        )
        if len(references) > 8:
            raise ContextOverflow("too_many_required_references")
        selected.update(
            i
            for i, event in enumerate(events)
            if event.message_id in references and counts[event.message_id] == 1
        )
        serialized = serialize(selected)
        if fixed + self.count(serialized) > limit:
            raise ContextOverflow("required_context_exceeds_budget")
        for i in range(min(len(events), self.policy.history_messages)):
            if i in selected:
                continue
            trial = serialize(selected | {i})
            if fixed + self.count(trial) <= limit:
                selected.add(i)
                serialized = trial
        context_tokens = self.count(serialized)
        logging.getLogger(__name__).info(
            "上下文已按预算组装",
            extra={
                "event": "context_assembled",
                "fields": {
                    "turn_id": candidate.event_id,
                    "encoding": self.policy.encoding,
                    "stage": stage,
                    "input_estimate": str(fixed + context_tokens),
                    "input_limit": str(limit),
                    "instruction_tokens": str(instruction_tokens),
                    "schema_tokens": str(schema_tokens),
                    "context_tokens": str(context_tokens),
                    "framing_tokens": str(self.policy.framing_tokens),
                    "selected_messages": str(len(selected)),
                    "dropped_messages": str(len(events) - len(selected)),
                },
            },
        )
        return serialized

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text, disallowed_special=()))

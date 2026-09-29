"""Conversation-bound audio reference, never a model-supplied path or URL."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioArtifact:
    conversation_id: str
    sha256: str
    size_bytes: int


class AudioArtifacts(Protocol):
    async def save(self, conversation_id: str, audio: bytes) -> AudioArtifact: ...

    async def read(self, artifact: AudioArtifact) -> bytes: ...

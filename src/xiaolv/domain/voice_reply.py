"""Provider-neutral spoken reply chosen explicitly by the conversation model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceReply:
    speech_text: str
    voice_profile: str

"""Persist synthesis output before entering the common guarded delivery path."""

from xiaolv.application.delivery import DeliveryRequest, DeliveryService
from xiaolv.domain.audio_artifact import AudioArtifacts
from xiaolv.domain.speech import SpeechResult
from xiaolv.domain.voice_reply import VoiceReply
from xiaolv.orchestration.text_runtime import ConversationCandidate


class VoiceDispatch:
    def __init__(self, artifacts: AudioArtifacts, delivery: DeliveryService) -> None:
        self._artifacts, self._delivery = artifacts, delivery

    async def __call__(
        self,
        candidate: ConversationCandidate,
        reply: VoiceReply,
        outgoing_id: str,
        result: SpeechResult,
    ) -> str:
        artifact = await self._artifacts.save(candidate.conversation_id, result.audio)
        return await self._delivery.deliver(
            DeliveryRequest(
                outgoing_id,
                candidate.conversation_id,
                candidate.expires_at,
                candidate.generation_epoch,
                "",
                audio=artifact,
            )
        )

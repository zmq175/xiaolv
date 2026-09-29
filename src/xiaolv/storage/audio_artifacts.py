"""Local bounded audio artifacts in an administrator-owned directory."""

import asyncio
import hashlib
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from xiaolv.domain.audio_artifact import AudioArtifact


class LocalAudioArtifacts:
    def __init__(self, root: Path, max_bytes: int = 4 * 1024 * 1024) -> None:
        self._root, self._max_bytes = root, max_bytes

    def _path(self, artifact: AudioArtifact) -> Path:
        if (
            re.fullmatch(r"[0-9a-f]{64}", artifact.sha256) is None
            or not 0 < artifact.size_bytes <= self._max_bytes
        ):
            raise ValueError("invalid audio artifact")
        scope = hashlib.sha256(artifact.conversation_id.encode()).hexdigest()
        return self._root / scope / (artifact.sha256 + ".wav")

    async def save(self, conversation_id: str, audio: bytes) -> AudioArtifact:
        artifact = AudioArtifact(conversation_id, hashlib.sha256(audio).hexdigest(), len(audio))
        path = self._path(artifact)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".audio-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(audio)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)

        await asyncio.to_thread(write)
        return artifact

    async def read(self, artifact: AudioArtifact) -> bytes:
        path = self._path(artifact)

        def read() -> bytes:
            with path.open("rb") as stream:
                audio = stream.read(self._max_bytes + 1)
            if (
                len(audio) != artifact.size_bytes
                or hashlib.sha256(audio).hexdigest() != artifact.sha256
            ):
                raise ValueError("audio artifact integrity failure")
            return audio

        return await asyncio.to_thread(read)

    async def cleanup(self, *, before: datetime) -> int:
        if before.tzinfo is None:
            raise ValueError("audio cleanup cutoff must be timezone-aware")
        cutoff = before.timestamp()

        def remove() -> int:
            removed = 0
            for directory in self._root.iterdir() if self._root.exists() else ():
                if not re.fullmatch(r"[0-9a-f]{64}", directory.name) or not directory.is_dir():
                    continue
                for path in directory.glob("*.wav"):
                    if not re.fullmatch(r"[0-9a-f]{64}\.wav", path.name):
                        continue
                    try:
                        if path.stat().st_mtime < cutoff:
                            path.unlink()
                            removed += 1
                    except FileNotFoundError:
                        continue
            return removed

        return await asyncio.to_thread(remove)

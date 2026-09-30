"""Image decoding in a short-lived process with bounded pipes and guaranteed cleanup."""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from xiaolv.application.inbound_speech import MediaUnavailable
from xiaolv.domain.image import PreparedImage
from xiaolv.platforms.media_http import ImageBytes


class ImageNormalizer:
    def __init__(self) -> None:
        self._slots = asyncio.Semaphore(2)

    async def prepare(self, image: ImageBytes, expires_at: datetime) -> PreparedImage:
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise TimeoutError()
        if sys.platform != "linux" or not 0 < len(image.data) <= 2 * 1024 * 1024:
            raise MediaUnavailable()
        async with asyncio.timeout(min(3, remaining)), self._slots:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("image_worker.py")),
                image.content_type,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={"LANG": "C.UTF-8"},
                limit=65536,
            )
            try:
                assert process.stdin is not None and process.stdout is not None
                async with asyncio.TaskGroup() as group:
                    result = group.create_task(self._read(process.stdout))
                    group.create_task(self._write(process.stdin, image.data))
                    group.create_task(process.wait())
                if process.returncode != 0:
                    raise MediaUnavailable()
                return result.result()
            finally:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    await asyncio.shield(process.wait())

    async def _write(self, writer: asyncio.StreamWriter, data: bytes) -> None:
        try:
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _read(self, reader: asyncio.StreamReader) -> PreparedImage:
        header = await reader.readline()
        if len(header) > 256:
            raise MediaUnavailable()
        meta = json.loads(header)
        if (
            not isinstance(meta, dict)
            or any(type(meta.get(key)) is not int for key in ("width", "height", "frames"))
            or not 1 <= meta["width"] <= 512
            or not 1 <= meta["height"] <= 512
            or meta["frames"] < 1
        ):
            raise MediaUnavailable()
        data = bytearray()
        while chunk := await reader.read(65536):
            if len(data) + len(chunk) > 1024 * 1024:
                raise MediaUnavailable()
            data.extend(chunk)
        if not data:
            raise MediaUnavailable()
        return PreparedImage(bytes(data), meta["width"], meta["height"], meta["frames"])

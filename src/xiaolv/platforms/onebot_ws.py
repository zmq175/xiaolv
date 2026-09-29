"""Native OneBot WebSocket transport."""

import asyncio
import json
from types import TracebackType
from typing import Self
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from xiaolv.application.delivery_contracts import NotSent


class OneBotWebSocket:
    def __init__(self, url: str, token: str, request_timeout: float = 5) -> None:
        self._url = url
        self._token = token
        self._timeout = request_timeout
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        self._closed = asyncio.Event()
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=128)

    async def __aenter__(self) -> Self:
        self._ws = await connect(
            self._url,
            additional_headers={"Authorization": f"Bearer {self._token}"},
            proxy=None,
            open_timeout=5,
            close_timeout=2,
            max_size=1048576,
        )
        self._reader = asyncio.create_task(self._read(self._ws))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._reader is not None:
            await self._reader

    async def call(self, action: str, params: dict[str, object]) -> dict[str, object]:
        if self._ws is None or self._reader is None or self._reader.done():
            raise NotSent("OneBot is not connected")
        echo = uuid4().hex
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        try:
            async with asyncio.timeout(self._timeout):
                await self._ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
                return await future
        finally:
            self._pending.pop(echo, None)
            if not future.done():
                future.cancel()

    async def _read(self, ws: ClientConnection) -> None:
        try:
            async for raw in ws:
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise TypeError("OneBot frame must be an object")
                echo = frame.get("echo")
                if isinstance(echo, str) and echo in self._pending:
                    future = self._pending[echo]
                    if not future.done():
                        future.set_result(frame)
                elif "post_type" in frame:
                    self._events.put_nowait(frame)
        except (ValueError, TypeError, asyncio.QueueFull):
            await ws.close(code=1002, reason="invalid OneBot frame")
        except ConnectionClosed:
            pass
        finally:
            self._closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("OneBot connection closed"))

    async def next_event(self) -> dict[str, object]:
        if not self._events.empty():
            return self._events.get_nowait()
        if self._closed.is_set():
            raise ConnectionError("OneBot connection closed")
        event = asyncio.create_task(self._events.get())
        closed = asyncio.create_task(self._closed.wait())
        try:
            await asyncio.wait({event, closed}, return_when=asyncio.FIRST_COMPLETED)
            if event.done():
                return event.result()
            raise ConnectionError("OneBot connection closed")
        finally:
            event.cancel()
            closed.cancel()
            await asyncio.gather(event, closed, return_exceptions=True)

"""In-process event bus: fans each event out to WebSocket clients and webhook subscribers."""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket

if TYPE_CHECKING:
    from .webhooks import WebhookDispatcher

log = logging.getLogger(__name__)


def topic_matches(event: str, patterns: set[str] | list[str]) -> bool:
    """"*" matches everything; "auction" or "auction.*" match every auction.* event."""
    if not patterns:
        return True
    for pattern in patterns:
        pattern = pattern.strip()
        if pattern in ("*", event):
            return True
        prefix = pattern[:-2] if pattern.endswith(".*") else pattern
        if event.startswith(prefix + "."):
            return True
    return False


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket, topics: set[str]) -> None:
        await ws.accept()
        self._clients[ws] = topics

    def set_topics(self, ws: WebSocket, topics: set[str]) -> None:
        if ws in self._clients:
            self._clients[ws] = topics

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.pop(ws, None)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict) -> None:
        for ws, topics in list(self._clients.items()):
            if not topic_matches(message["event"], topics):
                continue
            try:
                await ws.send_json(message)
            except Exception:  # client went away mid-send
                self.disconnect(ws)


class EventBus:
    def __init__(self) -> None:
        self.websockets = ConnectionManager()
        self.dispatcher: WebhookDispatcher | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def unbind(self) -> None:
        self._loop = None

    def emit(self, event: str, data: Any) -> Future | asyncio.Task | None:
        """Publish an event. Safe to call from the event loop or from worker threads.

        Returns a Task/Future that completes once WebSocket clients and webhooks were
        notified, or None when no event loop is bound (e.g. CLI runs).
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return None
        message = {"event": event, "data": data, "ts": datetime.now(timezone.utc).isoformat()}
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            task = loop.create_task(self._publish(message))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return task
        return asyncio.run_coroutine_threadsafe(self._publish(message), loop)

    def emit_all(self, events: list[tuple[str, Any]]) -> list:
        return [f for f in (self.emit(name, data) for name, data in events) if f is not None]

    async def _publish(self, message: dict) -> None:
        try:
            await self.websockets.broadcast(message)
            if self.dispatcher is not None:
                await self.dispatcher.dispatch(message)
        except Exception:
            log.exception("failed to publish %s", message.get("event"))

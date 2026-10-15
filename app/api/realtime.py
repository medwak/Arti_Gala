from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.events import EventBus

router = APIRouter(tags=["realtime"])


def _topics(raw) -> set[str]:
    if isinstance(raw, str):
        raw = raw.split(",")
    return {t.strip() for t in raw or [] if t and t.strip()}


@router.websocket("/ws")
async def live_feed(websocket: WebSocket, topics: str | None = None):
    """Live stream of events, e.g. ws://host/ws?topics=auction,case.

    Messages: {"event": "auction.created", "data": {...}, "ts": "..."}.
    Send {"action": "subscribe", "topics": ["artifact.*"]} to change topics,
    or {"action": "ping"} to get {"event": "pong"}.
    """
    bus: EventBus = websocket.app.state.bus
    manager = bus.websockets
    subscribed = _topics(topics)
    await manager.connect(websocket, subscribed)
    try:
        await websocket.send_json({"event": "welcome", "data": {"topics": sorted(subscribed) or ["*"]}})
        while True:
            message = await websocket.receive_json()
            action = message.get("action") if isinstance(message, dict) else None
            if action == "subscribe":
                subscribed = _topics(message.get("topics"))
                manager.set_topics(websocket, subscribed)
                await websocket.send_json({"event": "subscribed", "data": {"topics": sorted(subscribed) or ["*"]}})
            elif action == "ping":
                await websocket.send_json({"event": "pong", "data": {}})
            else:
                await websocket.send_json({"event": "error", "data": {"detail": "unknown action"}})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)

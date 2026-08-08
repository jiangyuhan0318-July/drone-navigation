"""Real-drone telemetry relay (WebSocket).

Mirrors the livestream video topology: the drone is tethered to a desktop,
so telemetry must travel desktop -> server -> browsers:

    motion_control_ws.py (owns the Crazyflie link, ws://:8765)
      -> extension/crazyflie_bridge/telemetry_relay.py  (WS client, publish)
        -> WS /api/drone/telemetry/publish              (this module, ingest)
          -> WS /api/drone/telemetry                    (this module, fan-out)
            -> SPA useDroneTelemetry -> HUD (Real Drone -> Livestream Host)

Both endpoints sit under ``/api`` so the existing Caddy reverse-proxy rule
(WebSocket upgrade is automatic) covers them — identical URLs in dev and
production.

Protocol (JSON text frames):
  publish -> server:  {"type": "telemetry", "category": "position"|"attitude"|"battery",
                       "timestamp": <drone ms>, "data": {...}}
  server -> browsers: the same frame plus server-side ``"ts"`` (epoch seconds);
                      on subscribe, a {"type": "snapshot", ...} frame with the
                      last known state of every category (or nulls).

Publish auth: if ``server/config.json`` -> ``"drone": {"telemetry_token": "..."}``
is set, publishers must pass ``?token=...``; empty/absent token means open
(fine for local dev). The subscribe endpoint is always public, same rationale
as ``GET /api/stream/config``.
"""

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import CONFIG

logger = logging.getLogger(__name__)

router = APIRouter(tags=["telemetry"])

# Last known value per category; None until the first frame arrives.
_latest: dict = {"position": None, "attitude": None, "battery": None}
_latest_ts: float = 0.0
_subscribers: set[WebSocket] = set()
_publisher: WebSocket | None = None
_LOCK = asyncio.Lock()


def _token() -> str:
    return CONFIG.get("drone", {}).get("telemetry_token", "") or ""


async def _broadcast(frame: dict) -> None:
    """Send one JSON frame to every subscriber; drop dead connections."""
    msg = json.dumps(frame)
    dead = set()
    for ws in list(_subscribers):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    _subscribers.difference_update(dead)


@router.websocket("/drone/telemetry/publish")
async def telemetry_publish(websocket: WebSocket) -> None:
    """Ingest endpoint for the desktop relay. One publisher at a time — a
    new publisher replaces the previous one."""
    global _publisher, _latest_ts

    token = _token()
    if token and websocket.query_params.get("token", "") != token:
        await websocket.close(code=4403)
        logger.warning("telemetry publish rejected: bad token from %s", websocket.client)
        return

    await websocket.accept()
    async with _LOCK:
        if _publisher is not None:
            try:
                await _publisher.close(code=4000)
            except Exception:
                pass
        _publisher = websocket
    logger.info("telemetry publisher connected: %s", websocket.client)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            category = frame.get("category")
            data = frame.get("data")
            if category not in _latest or not isinstance(data, dict):
                continue
            _latest[category] = data
            _latest_ts = time.time()
            await _broadcast(
                {"type": "telemetry", "category": category, "data": data, "ts": _latest_ts}
            )
    except WebSocketDisconnect:
        pass
    finally:
        async with _LOCK:
            if _publisher is websocket:
                _publisher = None
        logger.info("telemetry publisher disconnected: %s", websocket.client)


@router.websocket("/drone/telemetry")
async def telemetry_subscribe(websocket: WebSocket) -> None:
    """Fan-out endpoint for browsers. Sends a snapshot of the last known
    state immediately, then every live frame as it arrives."""
    await websocket.accept()
    _subscribers.add(websocket)
    try:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "snapshot",
                    "data": dict(_latest),
                    "ts": _latest_ts,
                }
            )
        )
        # No client -> server traffic; just hold the connection open.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.discard(websocket)


def publisher_connected() -> bool:
    """True when a desktop relay is publishing telemetry right now."""
    return _publisher is not None


def snapshot() -> dict:
    """Last known telemetry per category, for the AI copilot's status view."""
    return dict(_latest)


def last_updated() -> float:
    """Wall-clock time of the last telemetry frame received (0.0 if none)."""
    return _latest_ts

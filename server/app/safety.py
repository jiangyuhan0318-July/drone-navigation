"""Safety alert endpoints: fall detection from the client + fall-response takeoff.

The client (browser MediaPipe pose detection, or the extension fall
recognizer) posts confirmed fall events here. On a confirmed fall the
server does two things:

1. Webhook delivery — point ``safety.fall_alert_webhook`` at WeChat/WhatsApp
   or another messaging integration (delivery failure never breaks monitoring).
2. Fall response — takeoff, through the EXACT same validated + gated path
   as every other flight command (``drone_commands.forward_command``). The
   flight gate must be ON (a human armed autonomous flight), the battery must
   be above the 3.5 V floor (mirrors copilot_ctl.py), and the drone must not
   already be airborne. land/stop/estop are never gated, but a fall response
   is a takeoff, so the human's gate is the consent mechanism.

GET /api/safety/status gives the OpenClaw skill one-call visibility:
alert counters, last takeoff attempt, gate/link/battery/airborne.
"""

import logging
import time
from pathlib import Path

from fastapi import APIRouter
from httpx import AsyncClient
from pydantic import BaseModel, Field

from . import drone_commands, telemetry
from .config import CONFIG
from .copilot import _gate_enabled

router = APIRouter(tags=["safety"])
log = logging.getLogger(__name__)

# Below this battery voltage (V) the fall response refuses takeoff, mirroring
# copilot_ctl.py's pre-flight rule for human-initiated flight. Unknown
# telemetry (no bridge) -> allowed; the forward will report "no drone link".
BATTERY_FLOOR_V = 3.5

# Telemetry z (m) above which the drone is considered airborne — a second
# fall alert while already flying must not re-trigger takeoff.
AIRBORNE_Z_M = 0.15

# Server-side fall-response cooldown (s): both the browser SPA and the
# extension fall_control.py can report the same fall; whichever fires first
# wins, and repeat alerts within the window are deduped here.
FALL_RESPONSE_COOLDOWN_S = 30.0

# In-memory alert history for GET /api/safety/status (monitoring is
# stateless by design; a server restart simply clears the counters).
_STATE = {"alerts": 0, "last_alert": None, "last_takeoff": None}


class FallAlert(BaseModel):
    event: str = "fall"
    stream_id: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    detected_at: str = ""
    axis_angle_deg: float | None = None
    bbox_ratio: float | None = None


def _safety_cfg(key: str, default):
    return CONFIG.get("safety", {}).get(key, default)


def _snapshot() -> dict:
    snap = telemetry.snapshot()
    position = (snap.get("position") or {}) or {}
    battery = (snap.get("battery") or {}) or {}
    return {
        "z": float(position.get("z", 0.0) or 0.0),
        "voltage": battery.get("voltage"),
        "fresh": telemetry.last_updated(),
    }


def _battery_ok(voltage) -> bool:
    """None = no battery data (bridge down) -> allow, forward will fail."""
    return voltage is None or voltage >= BATTERY_FLOOR_V


async def _fall_takeoff() -> dict:
    """Send the fall-response takeoff through the gated copilot path.

    Returns {"fired": bool, "reason": str, "delivered": bool, ...} — fired is
    False with the reason when a guard refuses (gate off / low battery /
    already airborne / no link).
    """
    if not _gate_enabled():
        return {"fired": False, "reason": "flight_gate_off"}

    last = _STATE["last_takeoff"] or {}
    if last.get("fired") and time.time() - (last.get("ts") or 0) < FALL_RESPONSE_COOLDOWN_S:
        return {"fired": False, "reason": "fall_cooldown"}

    snap = _snapshot()
    if not _battery_ok(snap["voltage"]):
        return {
            "fired": False,
            "reason": "battery_low",
            "voltage": snap["voltage"],
        }
    if snap["z"] >= AIRBORNE_Z_M:
        return {"fired": False, "reason": "already_airborne", "z": snap["z"]}

    height = float(_safety_cfg("fall_takeoff_height", 0.5))
    cmd = {"action": "takeoff", "height": height}
    delivered = await drone_commands.forward_command(cmd)
    result = {
        "fired": True,
        "delivered": delivered,
        "action": "takeoff",
        "height": height,
        "reason": "ok" if delivered else "no drone link",
    }
    if delivered:
        log.warning("FALL RESPONSE: takeoff %.2f m forwarded to drone", height)
    else:
        log.warning("FALL RESPONSE: takeoff refused — %s", result["reason"])
    return result


@router.get("/safety/status")
async def safety_status() -> dict:
    """One-call summary for the OpenClaw skill / operators."""
    snap = _snapshot()
    return {
        "alerts": _STATE["alerts"],
        "last_alert": _STATE["last_alert"],
        "last_takeoff": _STATE["last_takeoff"],
        "gate": {"enabled": _gate_enabled()},
        "link": {
            "command_downlink": drone_commands.downlink_connected(),
            "telemetry_publisher": telemetry.publisher_connected(),
        },
        "telemetry": {
            "z": snap["z"],
            "battery": {"voltage": snap["voltage"]},
            "ts": snap["fresh"],
        },
        "ts": time.time(),
    }


@router.post("/safety/fall")
async def report_fall(payload: FallAlert) -> dict:
    """Client confirms a fall (event=fall). Alert + fall-response takeoff."""
    log.warning(
        "FALL ALERT stream=%s confidence=%.2f detected_at=%s axis=%s bbox=%s",
        payload.stream_id,
        payload.confidence,
        payload.detected_at,
        payload.axis_angle_deg,
        payload.bbox_ratio,
    )

    _STATE["alerts"] += 1
    _STATE["last_alert"] = {
        "ts": time.time(),
        "stream_id": payload.stream_id,
        "confidence": payload.confidence,
        "detected_at": payload.detected_at,
        "axis_angle_deg": payload.axis_angle_deg,
        "bbox_ratio": payload.bbox_ratio,
    }

    # 1) Notification webhook (optional; must never break monitoring).
    webhook = str(_safety_cfg("fall_alert_webhook", "")).strip()
    delivered = False
    if webhook:
        try:
            async with AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    webhook,
                    json=payload.model_dump(exclude_none=True),
                )
                delivered = response.status_code < 400
        except Exception as exc:
            log.error("fall alert webhook failed: %s", exc)

    # 2) Fall response: autonomous takeoff through the gated copilot path.
    response = await _fall_takeoff()
    _STATE["last_takeoff"] = {**response, "ts": time.time()}

    return {
        "ok": True,
        "delivered": delivered,
        "fall_response": response,
    }

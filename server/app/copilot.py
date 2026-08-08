"""AI flight copilot API (REST).

The copilot is the agent-side control surface for the OpenClaw-driven AI
flight copilot. It is a thin REST wrapper around the existing real-drone
command chain, so an LLM agent (through ``extension/copilot/copilot_ctl.py``)
drives the EXACT same validated path as the browser HUD:

    copilot_ctl.py (agent tool)
      -> POST /api/copilot/command      (this module)
        -> drone_commands.forward_command()   (schema validated + clamped)
          -> WS downlink -> telemetry_relay.py -> motion_control_ws.py
            -> Crazyflie

Safety — the flight gate: every flight-capable action (takeoff, move, and
the one-shot up/down/forward/back/left/right) is refused while the gate is
OFF. The gate only lives server-side (memory + a small file) and can only
be flipped by a real human via PUT /api/copilot/gate (or the copilot panel
in the SPA) — an LLM cannot raise it for itself. land / stop / estop are
NEVER gated: the pilot can always recover.

Auth: mirrors the drone endpoints — when config.json -> "drone" ->
"telemetry_token" is set, the ?token= query parameter must match; an empty
token means open (fine for local dev). Production must set the token.
"""

import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import drone_commands, telemetry
from .config import CONFIG
from .drone_commands import _validate
from .stream import stream_config

router = APIRouter(tags=["copilot"])

# Actions that physically move the drone — gated by the flight gate.
# (land / stop / estop are always allowed: they only make things safer.)
_FLIGHT_ACTIONS = {"takeoff", "move", "up", "down", "forward", "back", "left", "right"}

# Persisted gate state (server/data/copilot_gate.json) so a server restart
# does not silently re-arm autonomous flight.
_GATE_FILE = Path(__file__).resolve().parent.parent / "data" / "copilot_gate.json"


class GateState(BaseModel):
    enabled: bool


class CopilotCommand(BaseModel):
    action: str
    height: float | None = None
    vx: float | None = None
    vy: float | None = None
    vz: float | None = None
    yawrate: float | None = None
    distance: float | None = None


def _token() -> str:
    return CONFIG.get("drone", {}).get("telemetry_token", "") or ""


def _authorized(token_param: str) -> bool:
    token = _token()
    return not token or token_param == token


def _gate_enabled() -> bool:
    try:
        return _GATE_FILE.read_text().strip() == "on"
    except FileNotFoundError:
        return False


def _set_gate(enabled: bool) -> None:
    _GATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _GATE_FILE.write_text("on" if enabled else "off")


def _telemetry_snapshot() -> dict:
    snap = telemetry.snapshot()
    snap["ts"] = telemetry.last_updated()  # real frame time, not now() — so callers
    return snap                            # can detect stale data (frozen link)


@router.get("/copilot/gate")
async def copilot_gate_get() -> dict:
    """Current flight-gate state (the human's permission for AI flight)."""
    return {"enabled": _gate_enabled()}


@router.put("/copilot/gate")
async def copilot_gate_put(state: GateState, token: str = "") -> dict:
    """Set the flight gate. Humans only — the agent tool never calls this."""
    if not _authorized(token):
        raise HTTPException(status_code=4403, detail="unauthorized")
    _set_gate(state.enabled)
    return {"enabled": state.enabled}


@router.get("/copilot/status")
async def copilot_status() -> dict:
    """One-call summary for the agent: gate, link health, last telemetry,
    and the playable stream catalog."""
    return {
        "gate": {"enabled": _gate_enabled()},
        "link": {
            "command_downlink": drone_commands.downlink_connected(),
            "telemetry_publisher": telemetry.publisher_connected(),
        },
        "telemetry": _telemetry_snapshot(),
        "stream": await stream_config(),
        "ts": time.time(),
    }


@router.post("/copilot/command")
async def copilot_command(cmd: CopilotCommand, token: str = "") -> dict:
    """Send one flight command through the same validated path as the HUD.

    Returns the downlink ack plus a fresh telemetry snapshot so the agent
    gets "command delivered" and "where is the drone now" in one call.
    """
    if not _authorized(token):
        raise HTTPException(status_code=4403, detail="unauthorized")

    raw = {k: v for k, v in cmd.model_dump().items() if v is not None}
    validated = _validate(raw)
    if validated is None:
        raise HTTPException(status_code=400, detail="unknown action")

    if validated["action"] in _FLIGHT_ACTIONS and not _gate_enabled():
        return {
            "delivered": False,
            "action": validated["action"],
            "reason": "flight_gate_off",
            "telemetry": _telemetry_snapshot(),
        }

    delivered = await drone_commands.forward_command(validated)
    return {
        "delivered": delivered,
        "action": validated["action"],
        "reason": "ok" if delivered else "no drone link",
        "telemetry": _telemetry_snapshot(),
    }

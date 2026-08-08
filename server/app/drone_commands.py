"""Real-drone flight-command relay (WebSocket).

Reverse direction of the telemetry pipeline — commands travel
browser -> server -> desktop -> drone:

    SPA useDroneCommands (Real Drone -> Livestream Host, Takeoff/Landing)
      -> WS /api/drone/command             (this module, browser side)
        -> WS /api/drone/command/downlink  (this module, relay side)
          -> extension/crazyflie_bridge/telemetry_relay.py command_forwarder()
            -> motion_control_ws.py (owns the Crazyflie link, ws://:8765)

Kept deliberately separate from telemetry.py: commands are validated against
a strict whitelist (action + numeric clamps mirroring
motion_control_ws._handle_command) before they are forwarded — the server
never relays arbitrary payloads to the drone.

Downlink auth: same shared secret as telemetry publish
(config.json -> "drone" -> "telemetry_token", passed as ?token=...).

Acks: every browser command gets an immediate {"type": "ack", ...} frame so
the UI can tell apart "delivered towards the drone" from "no drone link".
The ack means the command was forwarded to the desktop relay; the bridge
itself may still refuse it (e.g. the USB-cable takeoff interlock).
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import telemetry as drone_telemetry
from .config import CONFIG

logger = logging.getLogger(__name__)

router = APIRouter(tags=["drone-commands"])

_downlink: WebSocket | None = None    # the ONE desktop relay connection
_commander: WebSocket | None = None   # the ONE browser connection (new replaces old)
_LOCK = asyncio.Lock()
_pending_action: dict[str, Any] | None = None
_last_gesture_event: dict[str, Any] | None = None
_last_pose_event: dict[str, Any] | None = None
_pose_state: dict[str, Any] = {
    "ready_for_confirmation": False,
    "control_mode": "idle",
    "last_effect": None,
}


class DroneActionRequest(BaseModel):
    type: Literal["takeoff", "land", "goto", "stop"]
    params: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


class DroneActionResponse(BaseModel):
    accepted: bool
    action_id: str
    status: Literal["sent", "rejected"]
    reason: str | None = None
    execution_confirmed: bool = False
    execution_state: Literal["forwarded_only", "not_executed", "unknown"] = "forwarded_only"
    verification_required: bool = True
    verification_hint: str | None = None
    echo: dict[str, Any]
    forwarded_commands: list[dict[str, Any]] = Field(default_factory=list)


class PendingDroneActionRequest(BaseModel):
    type: Literal["takeoff", "land", "goto"]
    params: dict[str, Any] = Field(default_factory=dict)
    source: str = "gesture_control"


class GestureEventRequest(BaseModel):
    gesture: Literal["open_palm", "thumb_up", "fist"]
    confidence: float = Field(ge=0.0, le=1.0)
    held_ms: int = Field(default=0, ge=0)
    source: str = "browser_camera"
    timestamp_ms: int | None = None


class PoseEventRequest(BaseModel):
    pose: Literal["hands_up", "arms_crossed", "t_pose"]
    confidence: float = Field(ge=0.0, le=1.0)
    held_ms: int = Field(default=0, ge=0)
    source: str = "browser_camera"
    timestamp_ms: int | None = None


def _token() -> str:
    return CONFIG.get("drone", {}).get("telemetry_token", "") or ""


def _no_fly() -> bool:
    return os.environ.get("CF_NO_FLY", "") == "1"


def _connected() -> bool:
    return _downlink is not None


def downlink_connected() -> bool:
    """True when a desktop relay (telemetry_relay.py) is attached.

    Used by copilot.py / safety.py to report link state (kept from the
    pre-merge version; the browser control flow needs it too).
    """
    return _downlink is not None


async def forward_command(cmd: dict) -> bool:
    """Forward a pre-validated command to the desktop relay; True on delivery.

    Used by the AI copilot (copilot.py) and the fall response (safety.py) so
    they drive the same downlink as the browser HUD — never a parallel path
    to the drone.
    """
    downlink = _downlink
    if downlink is None:
        return False
    try:
        await downlink.send_text(json.dumps(cmd))
        logger.info("copilot command forwarded: %s", cmd)
        return True
    except Exception as e:  # downlink died mid-send
        logger.warning("copilot command forward failed: %s", e)
        return False


def _is_simulated() -> bool:
    return bool(getattr(drone_telemetry, "_latest_simulated", False))


def _telemetry_snapshot() -> dict[str, Any]:
    position = drone_telemetry._latest.get("position") or {}
    attitude = drone_telemetry._latest.get("attitude") or {}
    battery = drone_telemetry._latest.get("battery") or {}
    simulated = _is_simulated()
    telemetry_age_s = None
    if drone_telemetry._latest_ts:
        telemetry_age_s = max(0.0, time.time() - drone_telemetry._latest_ts)
    telemetry_fresh = bool(
        (not simulated)
        and drone_telemetry._latest_ts
        and (time.time() - drone_telemetry._latest_ts) < 2.5
    )
    connected = _connected() and telemetry_fresh

    z = position.get("z")
    in_air = bool(isinstance(z, (int, float)) and z > 0.05)
    return {
        "connected": connected,
        "simulated": simulated,
        "bridge_connected": _connected() and not simulated,
        "telemetry_fresh": telemetry_fresh,
        "telemetry_age_s": telemetry_age_s,
        "armed": in_air if z is not None else None,
        "in_air": in_air,
        "mode": "flying" if in_air and connected else ("idle" if connected else "disconnected"),
        "battery": battery if battery else None,
        "position": position if position else None,
        "attitude": attitude if attitude else None,
        "no_fly": _no_fly(),
    }


def _pending_action_snapshot() -> dict[str, Any]:
    if _pending_action is None:
        return {
            "active": False,
            "action_id": None,
            "type": None,
            "params": None,
            "source": None,
            "created_at_ms": None,
            "preview_commands": [],
        }
    return {
        "active": True,
        "action_id": _pending_action["action_id"],
        "type": _pending_action["type"],
        "params": _pending_action["params"],
        "source": _pending_action["source"],
        "created_at_ms": _pending_action["created_at_ms"],
        "preview_commands": _pending_action.get("preview_commands", []),
    }


def _gesture_status_snapshot() -> dict[str, Any]:
    return {
        "pending_action": _pending_action_snapshot(),
        "last_gesture_event": _last_gesture_event,
        "supported_gestures": ["open_palm", "thumb_up", "fist"],
        "hold_threshold_ms": 1000,
    }


def _pose_status_snapshot() -> dict[str, Any]:
    return {
        "pose_state": dict(_pose_state),
        "last_pose_event": _last_pose_event,
        "supported_poses": ["hands_up", "arms_crossed", "t_pose"],
        "hold_threshold_ms": 1000,
        "pending_action": _pending_action_snapshot(),
    }


def _clamp_number(value: Any, lo: float, hi: float, field_name: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid {field_name}") from exc
    if not (lo <= numeric <= hi):
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} out of range [{lo}, {hi}]",
        )
    return numeric


def _build_http_commands(req: DroneActionRequest) -> list[dict[str, Any]]:
    params = req.params or {}
    if req.type in {"takeoff", "land", "goto"} and not req.confirm:
        raise HTTPException(status_code=409, detail="high-risk action requires confirm=true")
    if not _connected():
        raise HTTPException(status_code=503, detail="no drone link")

    if req.type == "stop":
        return [{"action": "stop"}]

    if req.type == "land":
        return [{"action": "land"}]

    if req.type == "takeoff":
        if _no_fly():
            raise HTTPException(status_code=409, detail="takeoff rejected: CF_NO_FLY is enabled")
        alt_m = _clamp_number(params.get("alt_m", 0.5), 0.2, 1.5, "alt_m")
        return [{"action": "takeoff", "height": alt_m}]

    frame = params.get("frame", "local_enu")
    if frame != "local_enu":
        raise HTTPException(status_code=422, detail="only frame=local_enu is supported in MVP")

    target_x = _clamp_number(params.get("x_m"), -2.0, 2.0, "x_m")
    target_y = _clamp_number(params.get("y_m"), -2.0, 2.0, "y_m")
    target_z = _clamp_number(params.get("z_m"), 0.0, 1.5, "z_m")
    speed_mps = _clamp_number(params.get("speed_mps", 0.3), 0.05, 1.0, "speed_mps")

    position = drone_telemetry._latest.get("position") or {}
    if not {"x", "y", "z"} <= set(position.keys()):
        raise HTTPException(status_code=409, detail="goto requires current position telemetry")

    current_x = float(position["x"])
    current_y = float(position["y"])
    current_z = float(position["z"])
    if current_z <= 0.05:
        raise HTTPException(
            status_code=409,
            detail="goto requires the drone to be airborne; send takeoff first",
        )
    delta_x = target_x - current_x
    delta_y = target_y - current_y
    delta_z = target_z - current_z

    commands: list[dict[str, Any]] = []
    # MVP bridge only supports relative primitives. Implement goto as a
    # segmented move in local_enu based on current telemetry.
    if delta_z > 0.05:
        commands.append({"action": "up", "distance": round(min(abs(delta_z), 1.0), 3)})
    if abs(delta_x) > 0.05:
        commands.append({
            "action": "forward" if delta_x > 0 else "back",
            "distance": round(min(abs(delta_x), 1.0), 3),
        })
    if abs(delta_y) > 0.05:
        commands.append({
            "action": "right" if delta_y > 0 else "left",
            "distance": round(min(abs(delta_y), 1.0), 3),
        })
    if delta_z < -0.05:
        commands.append({"action": "down", "distance": round(min(abs(delta_z), 1.0), 3)})

    if not commands:
        raise HTTPException(status_code=409, detail="goto target is already within tolerance")

    for cmd in commands:
        if "distance" in cmd:
            cmd["speed_mps"] = speed_mps
    return commands


async def _send_to_downlink(cmd: dict[str, Any]) -> None:
    downlink = _downlink
    if downlink is None:
        raise HTTPException(status_code=503, detail="no drone link")
    try:
        await downlink.send_text(json.dumps(cmd))
    except Exception as exc:
        logger.warning("drone HTTP forward failed: %s", exc)
        raise HTTPException(status_code=502, detail="downlink send failed") from exc


async def _execute_action(req: DroneActionRequest) -> DroneActionResponse:
    forwarded_commands = _build_http_commands(req)
    for cmd in forwarded_commands:
        await _send_to_downlink(cmd)

    return DroneActionResponse(
        accepted=True,
        action_id=f"act-{int(time.time() * 1000)}",
        status="sent",
        reason=None,
        execution_confirmed=False,
        execution_state="forwarded_only",
        verification_required=True,
        verification_hint=(
            "Command was forwarded to the drone bridge only. "
            "Do not claim physical execution until /api/drone/status shows the expected state change."
        ),
        echo={"type": req.type, "params": req.params, "confirm": req.confirm},
        forwarded_commands=forwarded_commands,
    )


def _clamp(value, lo, hi, default):
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _validate(raw: dict) -> dict | None:
    """Whitelist + clamp an incoming command; None = reject.

    Mirrors the accepted schema and clamps of motion_control_ws._dispatch_command
    (note: the bridge spells the yaw field "yawrate").
    """
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    if action == "takeoff":
        return {"action": "takeoff", "height": _clamp(raw.get("height", 0.5), 0.1, 1.5, 0.5)}
    if action in ("land", "stop", "estop"):
        return {"action": action}
    if action == "move":
        return {
            "action": "move",
            "vx": _clamp(raw.get("vx", 0.0), -0.5, 0.5, 0.0),
            "vy": _clamp(raw.get("vy", 0.0), -0.5, 0.5, 0.0),
            "vz": _clamp(raw.get("vz", 0.0), -0.5, 0.5, 0.0),
            "yawrate": _clamp(raw.get("yawrate", 0.0), -120.0, 120.0, 0.0),
        }
    if action in ("up", "down", "forward", "back", "left", "right"):
        return {"action": action, "distance": _clamp(raw.get("distance", 0.2), 0.05, 1.0, 0.2)}
    return None


async def _ack(ws: WebSocket, action: str, delivered: bool, reason: str = "") -> None:
    frame = {"type": "ack", "action": action, "delivered": delivered}
    if reason:
        frame["reason"] = reason
    try:
        await ws.send_text(json.dumps(frame))
    except Exception:
        pass


@router.websocket("/drone/command/downlink")
async def command_downlink(websocket: WebSocket) -> None:
    """The desktop relay connects here to receive commands (token-guarded)."""
    global _downlink
    token = _token()
    if token and websocket.query_params.get("token", "") != token:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    async with _LOCK:
        if _downlink is not None:
            try:
                await _downlink.close(code=4000)  # replaced by the newer relay
            except Exception:
                pass
        _downlink = websocket
    logger.info("drone command downlink connected: %s", websocket.client)
    try:
        while True:
            await websocket.receive_text()  # hold open; nothing expected inbound
    except WebSocketDisconnect:
        pass
    finally:
        async with _LOCK:
            if _downlink is websocket:
                _downlink = None
        logger.info("drone command downlink disconnected")


@router.websocket("/drone/command")
async def command(websocket: WebSocket) -> None:
    """Browser command channel: validate, forward to the downlink, ack."""
    global _commander
    await websocket.accept()
    async with _LOCK:
        if _commander is not None:
            try:
                await _commander.close(code=4000)  # single commander: newest wins
            except Exception:
                pass
        _commander = websocket
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await _ack(websocket, "", False, "invalid json")
                continue
            cmd = _validate(payload)
            if cmd is None:
                await _ack(websocket, str(payload.get("action", "")), False, "unknown action")
                continue
            downlink = _downlink
            if downlink is None:
                await _ack(websocket, cmd["action"], False, "no drone link")
                continue
            try:
                await downlink.send_text(json.dumps(cmd))
                logger.info("drone command forwarded: %s (from %s)", cmd, websocket.client)
                await _ack(websocket, cmd["action"], True)
            except Exception as e:  # downlink died mid-send
                logger.warning("drone command forward failed: %s", e)
                await _ack(websocket, cmd["action"], False, "downlink send failed")
    except WebSocketDisconnect:
        pass
    finally:
        async with _LOCK:
            if _commander is websocket:
                _commander = None


@router.get("/drone/status")
async def drone_status() -> dict[str, Any]:
    return _telemetry_snapshot()


@router.get("/drone/pending-action")
async def drone_pending_action() -> dict[str, Any]:
    return _pending_action_snapshot()


@router.post("/drone/pending-action")
async def create_drone_pending_action(req: PendingDroneActionRequest) -> dict[str, Any]:
    global _pending_action
    preview_req = DroneActionRequest(type=req.type, params=req.params, confirm=True)
    preview_commands = _build_http_commands(preview_req)
    created_at_ms = int(time.time() * 1000)
    _pending_action = {
        "action_id": f"pending-{created_at_ms}",
        "type": req.type,
        "params": req.params,
        "source": req.source,
        "created_at_ms": created_at_ms,
        "preview_commands": preview_commands,
    }
    return {
        "accepted": True,
        "detail": "pending action created",
        "pending_action": _pending_action_snapshot(),
    }


@router.delete("/drone/pending-action")
async def clear_drone_pending_action() -> dict[str, Any]:
    global _pending_action
    had_pending = _pending_action is not None
    _pending_action = None
    return {
        "accepted": True,
        "detail": "pending action cleared" if had_pending else "no pending action",
        "pending_action": _pending_action_snapshot(),
    }


@router.get("/gesture/status")
async def gesture_status() -> dict[str, Any]:
    return _gesture_status_snapshot()


@router.get("/pose/status")
async def pose_status() -> dict[str, Any]:
    return _pose_status_snapshot()


@router.post("/gesture/event")
async def gesture_event(req: GestureEventRequest) -> dict[str, Any]:
    global _last_gesture_event, _pending_action

    observed_at_ms = req.timestamp_ms or int(time.time() * 1000)
    _last_gesture_event = {
        "gesture": req.gesture,
        "confidence": req.confidence,
        "held_ms": req.held_ms,
        "source": req.source,
        "observed_at_ms": observed_at_ms,
    }

    effect = "observed"
    detail = None
    action_response = None

    if req.gesture == "open_palm":
        try:
            action_response = await _execute_action(
                DroneActionRequest(type="stop", params={}, confirm=False)
            )
            effect = "stop_forwarded"
        except HTTPException as exc:
            effect = "stop_failed"
            detail = str(exc.detail)
    elif req.gesture == "thumb_up":
        if _pending_action is None:
            effect = "no_pending_action"
            detail = "there is no pending action to confirm"
        else:
            try:
                action_response = await _execute_action(
                    DroneActionRequest(
                        type=_pending_action["type"],
                        params=_pending_action["params"],
                        confirm=True,
                    )
                )
                _pending_action = None
                effect = "pending_action_confirmed"
            except HTTPException as exc:
                effect = "pending_action_failed"
                detail = str(exc.detail)
    elif req.gesture == "fist":
        if _pending_action is None:
            effect = "no_pending_action"
            detail = "there is no pending action to cancel"
        else:
            _pending_action = None
            effect = "pending_action_cancelled"

    return {
        "accepted": effect not in {"stop_failed", "pending_action_failed"},
        "effect": effect,
        "detail": detail,
        "pending_action": _pending_action_snapshot(),
        "last_gesture_event": _last_gesture_event,
        "action": action_response.model_dump() if action_response else None,
    }


@router.post("/pose/event")
async def pose_event(req: PoseEventRequest) -> dict[str, Any]:
    global _last_pose_event, _pending_action, _pose_state

    observed_at_ms = req.timestamp_ms or int(time.time() * 1000)
    _last_pose_event = {
        "pose": req.pose,
        "confidence": req.confidence,
        "held_ms": req.held_ms,
        "source": req.source,
        "observed_at_ms": observed_at_ms,
    }

    effect = "pose_observed"
    detail = None

    if req.pose == "hands_up":
        _pose_state["ready_for_confirmation"] = True
        effect = "pose_ready_enabled"
    elif req.pose == "arms_crossed":
        _pose_state["ready_for_confirmation"] = False
        _pose_state["control_mode"] = "idle"
        if _pending_action is not None:
            _pending_action = None
            effect = "pending_action_cancelled"
        else:
            effect = "pose_ready_cleared"
    elif req.pose == "t_pose":
        _pose_state["control_mode"] = "pose_mode"
        effect = "pose_mode_enabled"

    _pose_state["last_effect"] = effect

    return {
        "accepted": True,
        "effect": effect,
        "detail": detail,
        "pose_state": dict(_pose_state),
        "last_pose_event": _last_pose_event,
        "pending_action": _pending_action_snapshot(),
    }


@router.post("/drone/action", response_model=DroneActionResponse)
async def drone_action(req: DroneActionRequest) -> DroneActionResponse:
    return await _execute_action(req)

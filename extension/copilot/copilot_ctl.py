#!/usr/bin/env python3
"""Agent-side CLI for the AI flight copilot.

Bridges an LLM agent (OpenClaw) to the drone-navigation FastAPI copilot
endpoints. Pure standard library — no cflib, no websockets, nothing to
install. The agent runs one-shot commands and parses the JSON answer:

    copilot_ctl.py status                       # gate + link + telemetry
    copilot_ctl.py command takeoff --height 0.5
    copilot_ctl.py command move --vx 0.2 --vz 0.1 --yawrate 0
    copilot_ctl.py command forward --distance 0.5
    copilot_ctl.py command land | stop | estop

Every command is schema-validated and clamped by the server before it is
forwarded to the drone; the flight gate (a human toggled switch) is checked
server-side, so a hallucinating model can never arm flight by itself.

Env overrides: COPILOT_BASE (default http://127.0.0.1:8000),
COPILOT_TOKEN (default "" — set when the server configures telemetry_token).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("COPILOT_BASE", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("COPILOT_TOKEN", "")

# Below this battery voltage (V) the copilot refuses takeoff, mirroring the
# skill's safety rule. Unknown telemetry (no bridge) -> allowed, the server
# will report "no drone link" anyway.
BATTERY_FLOOR_V = 3.5


def _api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    if TOKEN:
        url += ("&" if "?" in path else "?") + f"token={TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        return {"error": f"HTTP {e.code}", "detail": detail}
    except Exception as e:
        return {"error": str(e)}


def _out(payload: dict) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def cmd_status() -> int:
    return _out(_api("/api/copilot/status"))


def cmd_command(args) -> int:
    body = {"action": args.action}
    if args.height is not None:
        body["height"] = args.height
    if args.distance is not None:
        body["distance"] = args.distance
    for k in ("vx", "vy", "vz", "yawrate"):
        v = getattr(args, k)
        if v is not None:
            body[k] = v

    # Pre-flight battery check: refuse takeoff on a clearly low battery.
    if args.action == "takeoff":
        status = _api("/api/copilot/status")
        if "error" in status:
            return _out({"error": f"preflight status failed: {status['error']}"})
        voltage = (status.get("telemetry") or {}).get("battery") or {}
        v = voltage.get("voltage")
        if v is not None and v < BATTERY_FLOOR_V:
            return _out(
                {
                    "delivered": False,
                    "action": "takeoff",
                    "reason": f"battery too low ({v:.2f}V < {BATTERY_FLOOR_V}V)",
                }
            )

    return _out(_api("/api/copilot/command", method="POST", body=body))


def main() -> int:
    parser = argparse.ArgumentParser(prog="copilot_ctl.py", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="gate + link + telemetry + stream summary")

    p_cmd = sub.add_parser("command", help="send one flight command")
    p_cmd.add_argument("action", help="takeoff|land|stop|estop|move|up|down|forward|back|left|right")
    p_cmd.add_argument("--height", type=float, help="takeoff height (0.1-1.5m)")
    p_cmd.add_argument("--distance", type=float, help="one-shot move distance (0.05-1.0m)")
    p_cmd.add_argument("--vx", type=float)
    p_cmd.add_argument("--vy", type=float)
    p_cmd.add_argument("--vz", type=float)
    p_cmd.add_argument("--yawrate", type=float)

    args = parser.parse_args()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "command":
        return cmd_command(args)
    parser.error("unknown command")


if __name__ == "__main__":
    sys.exit(main())

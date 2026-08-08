#!/usr/bin/env python3
"""Local E2E check for the real-drone command chain (no browser needed).

Simulates the SPA's useDroneCommands module against the LOCAL server:

    this script -> WS /api/drone/command        (FastAPI: validate + ack)
      -> WS /api/drone/command/downlink         (telemetry_relay.py)
        -> motion_control_ws.py :8765           (bridge dispatcher)

Also subscribes to WS /api/drone/telemetry (the HUD channel) to verify the
reverse direction (drone -> bridge -> relay -> server -> browser).

Run with the crazyflie conda env while server + bridge + relay are up:
    python e2e_command_check.py
"""

import asyncio
import json
import sys

import websockets

SERVER = "ws://127.0.0.1:8000/api/drone"

# The exact frames the RealDroneView UI sends (see useDroneCommands.js).
CASES = [
    ("takeoff (UI takeoff button)", {"action": "takeoff", "height": 0.5}),
    ("move +x (disk M push)", {"action": "move", "vx": 0.3, "vy": 0.0, "vz": 0.0, "yawrate": 0.0}),
    ("move +z (disk H push = auto-takeoff path)", {"action": "move", "vx": 0.0, "vy": 0.0, "vz": 0.3, "yawrate": 0.0}),
    ("hover (disk release)", {"action": "move", "vx": 0.0, "vy": 0.0, "vz": 0.0, "yawrate": 0.0}),
    ("land (UI landing button)", {"action": "land"}),
    ("stop (UI stop button)", {"action": "stop"}),
    ("bogus (must be rejected)", {"action": "bogus"}),
]


async def recv_ack(ws, timeout=3.0):
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return json.loads(raw)


async def check_commands():
    print(f"== Command channel: {SERVER}/command")
    ok = True
    async with websockets.connect(f"{SERVER}/command") as ws:
        for label, frame in CASES:
            await ws.send(json.dumps(frame))
            try:
                ack = await recv_ack(ws)
            except asyncio.TimeoutError:
                print(f"  FAIL  {label}: no ack within 3 s")
                ok = False
                continue
            expect_delivered = frame["action"] != "bogus"
            got = ack.get("delivered")
            status = "ok  " if got == expect_delivered else "FAIL"
            if got != expect_delivered:
                ok = False
            reason = f"  reason={ack.get('reason')}" if ack.get("reason") else ""
            print(f"  {status} {label}: ack delivered={got}{reason}")
    return ok


async def check_telemetry():
    print(f"== Telemetry channel: {SERVER}/telemetry (HUD subscription)")
    try:
        async with websockets.connect(f"{SERVER}/telemetry") as ws:
            raw = await asyncio.wait_for(ws.recv(), 5.0)
            frame = json.loads(raw)
            print(f"  ok   first frame: type={frame.get('type')} category={frame.get('category')} data={frame.get('data')}")
            # 'snapshot' (state sync for late joiners) or a live 'telemetry'
            # frame both prove the drone -> browser channel is up.
            return frame.get("type") in ("telemetry", "snapshot")
    except asyncio.TimeoutError:
        print("  FAIL  no telemetry within 5 s (is the relay publishing?)")
        return False


async def main():
    ok_t = await check_telemetry()
    ok_c = await check_commands()
    print("== RESULT:", "PASS" if (ok_t and ok_c) else "FAIL")
    sys.exit(0 if (ok_t and ok_c) else 1)


if __name__ == "__main__":
    asyncio.run(main())

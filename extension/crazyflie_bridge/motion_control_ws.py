#!/usr/bin/env python3
"""
Crazyflie WebSocket Bridge

Runs a WebSocket server that accepts commands from a PWA frontend,
forwards them to a Crazyflie drone, and streams telemetry back.

Usage:
    python3 motion_control_ws.py
    python3 motion_control_ws.py --cf-uri radio://0/80/2M/E7E7E7E7E7 --port 8765
"""

import argparse
import asyncio
import json
import os
import queue
import signal
import sys
import threading
import time
import warnings
from contextlib import contextmanager

# Suppress cflib deprecation / firmware-version warnings globally
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)
# Monkeypatch warnings.warn to truly silence cflib internal warnings
_original_warn = warnings.warn
def _silent_warn(message, category=UserWarning, stacklevel=1, **kwargs):
    if category is DeprecationWarning or category is UserWarning:
        return
    _original_warn(message, category=category, stacklevel=stacklevel, **kwargs)
warnings.warn = _silent_warn

import logging

# cflib is very chatty (link drivers, TOC downloads, reconnect warnings) —
# keep errors only; connection problems still surface as exceptions below.
logging.getLogger("cflib").setLevel(logging.ERROR)

# Dead-man switch: a 'move' velocity setpoint expires this many seconds after
# the last velocity command unless refreshed (the web Flight disk re-sends
# every 150 ms while active). On expiry the drone is put into a hover — a
# dropped browser / relay / server must never leave it flying a stale
# velocity.
MOVE_WATCHDOG_S = 0.5

# If no telemetry frame arrives for this long, the radio link is considered
# silently dead (with the legacy-firmware cflib patches, a link drop often
# never raises — the worker would sit in its inner loop forever, serving
# stale telemetry to the panel). Bail out of the session so the retry loop
# reconnects the moment the drone answers again.
LINK_SILENT_S = 5.0

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander

import warnings

# The drone runs a custom firmware (CRTP protocol v6). cflib emits three
# harmless compatibility warnings — the legacy paths it falls back to are
# exactly what this firmware needs. Suppress them all.
warnings.filterwarnings(
    'ignore',
    message=r'Using legacy TYPE_.*_LEGACY',  # hover/zdistance packet types
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'platform\.send_arming_request is deprecated',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'The supervisor subsystem requires CRTP protocol version 12 or later',
    category=UserWarning,
)

try:
    import websockets
except ImportError:
    print("Error: 'websockets' library not installed. Run: pip install websockets")
    sys.exit(1)


class CrazyflieBridge:
    """
    WebSocket server bridge for Crazyflie drone control.

    - WebSocket server accepts connections from PWA clients
    - Crazyflie connection + MotionCommander runs on a dedicated thread
    - Telemetry flows:  Crazyflie callbacks -> asyncio queue -> WebSocket clients
    - Commands flow:    WebSocket clients -> thread-safe queue -> MotionCommander
    """

    def __init__(self, cf_uri, port=8765, telemetry_hz=10):
        self.cf_uri = cf_uri
        self.port = port
        self.telemetry_period_ms = int(1000 / telemetry_hz)

        # Cross-thread communication
        self._command_queue = queue.Queue()
        self._telemetry_queue = asyncio.Queue(maxsize=100)

        self._loop = None
        self._running = True
        self._cf_thread = None
        self._motion_commander = None
        self._scf = None
        self._clients = set()

        # Current height tracked from telemetry (thread-safe via GIL for float)
        self._current_z = 0.0

        # Epoch time of the newest telemetry frame; 0 until first frame of a
        # session. Feeds the link-silence watchdog in the worker loop.
        self._last_telemetry = 0.0

        # Consecutive Crazyflie connection failures — the error line is
        # logged on the 1st failure and then only every 30th retry (the
        # worker retries forever every 2 s, which is ~43k lines/day when
        # the drone is simply off).
        self._cf_failures = 0

        # SAFETY interlock: a USB-tethered drone must NEVER take off (the
        # cable would yank it down). Block 'takeoff' and the move-up
        # auto-takeoff path while the link is usb://*. Override for bench
        # tests with CF_ALLOW_USB_TAKEOFF=1.
        # CF_NO_FLY=1 is a dry-run mode for ANY link (incl. radio): every
        # takeoff attempt is refused, so the full command chain can be
        # exercised without the drone ever leaving the ground.
        self._no_fly = os.environ.get("CF_NO_FLY", "") == "1"
        self._usb_takeoff_blocked = self._no_fly or (
            self.cf_uri.startswith("usb")
            and os.environ.get("CF_ALLOW_USB_TAKEOFF", "") != "1"
        )

        # Dead-man switch deadline (epoch seconds) for velocity setpoints;
        # None while the last 'move' was all-zeros or no move is active.
        self._velocity_deadline = None

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _suppress_stderr():
        """Context manager that temporarily silences stderr (for cflib noise)."""
        @contextmanager
        def _cm():
            old_stderr = sys.stderr
            sys.stderr = open(os.devnull, 'w')
            try:
                yield
            finally:
                sys.stderr.close()
                sys.stderr = old_stderr
        return _cm()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def start(self):
        """Initialize CRTP drivers and spin up the Crazyflie worker thread."""
        cflib.crtp.init_drivers()
        self._cf_thread = threading.Thread(target=self._cf_worker, daemon=False)
        self._cf_thread.start()

    async def run(self):
        """Start the WebSocket server and telemetry broadcaster."""
        self._loop = asyncio.get_event_loop()
        await asyncio.sleep(2)

        async with websockets.serve(self._ws_handler, "0.0.0.0", self.port):
            print(f"[Bridge] WebSocket server running on ws://0.0.0.0:{self.port}")
            await self._broadcast_telemetry()

    def stop(self):
        """Signal all loops to exit."""
        self._running = False

    def join(self, timeout=10):
        """Wait for the Crazyflie worker thread to finish (e.g. after landing)."""
        if self._cf_thread and self._cf_thread.is_alive():
            self._cf_thread.join(timeout=timeout)

    # ------------------------------------------------------------------ #
    #  WebSocket Server Handler
    # ------------------------------------------------------------------ #

    async def _ws_handler(self, websocket):
        """Handle a single WebSocket client connection."""
        self._clients.add(websocket)
        remote = websocket.remote_address
        print(f"[Bridge] Client connected: {remote}")
        try:
            async for message in websocket:
                try:
                    cmd = json.loads(message)
                    action = cmd.get("action")
                    if action:
                        self._command_queue.put_nowait(cmd)
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            print(f"[Bridge] Client disconnected: {remote}")
            # Safety: the LAST command channel went away while a velocity
            # setpoint could still be active -> hover. (Relay/server restart
            # mid-flight must not leave the drone flying blind.)
            if not self._clients and self._is_flying:
                self._command_queue.put_nowait(
                    {"action": "move", "vx": 0, "vy": 0, "vz": 0, "yawrate": 0}
                )

    async def _broadcast_telemetry(self):
        """Continuously read from telemetry queue and broadcast to all clients."""
        while self._running:
            try:
                telem = self._telemetry_queue.get_nowait()
                msg = json.dumps(telem)
                dead = set()
                for ws in self._clients:
                    try:
                        await ws.send(msg)
                    except websockets.exceptions.ConnectionClosed:
                        dead.add(ws)
                self._clients -= dead
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.01)

    # ------------------------------------------------------------------ #
    #  Crazyflie Worker Thread
    # ------------------------------------------------------------------ #

    def _cf_worker(self):
        """Background thread: owns the Crazyflie connection and MotionCommander."""
        while self._running:
            try:
                with SyncCrazyflie(self.cf_uri, cf=Crazyflie(rw_cache='./cache')) as scf:
                    self._scf = scf
                    self._cf_failures = 0
                    print(f"[Bridge] Crazyflie connected: {self.cf_uri}")

                    self._setup_logging(scf.cf)
                    # Legacy firmware (CRTP -1, platform v6) gates hover and
                    # velocity setpoints behind commander.enHighLevel — without
                    # it takeoff/hover/move commands are silently ignored.
                    # Modern firmware lacks the param; enable it if present.
                    if 'enHighLevel' in scf.cf.param.toc.toc.get('commander', {}):
                        try:
                            scf.cf.param.set_value('commander.enHighLevel', 1)
                            print('[Bridge] commander.enHighLevel = 1 (legacy firmware)')
                        except Exception as e:
                            print(f'[Bridge] enHighLevel set failed: {e}')
                    # Try new supervisor arming first (firmware v12+), fallback to legacy.
                    # Print the result — if arming fails the motors never spin up
                    # and takeoff is silently a no-op.
                    try:
                        scf.cf.supervisor.send_arming_request(True)
                        print('[Bridge] supervisor arming requested')
                    except (AttributeError, Exception) as e:
                        print(f'[Bridge] supervisor arming unavailable ({e}); '
                              'trying platform arming...')
                        try:
                            scf.cf.platform.send_arming_request(True)
                            print('[Bridge] platform arming requested (fallback)')
                        except (AttributeError, Exception) as e2:
                            print(f'[Bridge] platform arming failed: {e2}')
                    time.sleep(1.0)
                    # Zero the position estimator on every (re)connect: without
                    # a Flow deck, IMU-integrated X/Y drift by metres while the
                    # drone sits still, so a long-sitting bench unit shows
                    # nonsense like (5.3, 4.7, 0.0). Start each session at
                    # 0,0,0 so the panel reads sane until takeoff.
                    try:
                        scf.cf.param.set_value('kalman.resetEstimation', '1')
                        print('[Bridge] Position estimator reset (kalman.resetEstimation=1)')
                    except Exception as e:
                        print(f'[Bridge] estimator reset failed: {e}')

                    with self._suppress_stderr():
                        mc = MotionCommander(scf, default_height=0.5)
                    # Store mc but do NOT enter context (that auto-takes-off).
                    # We'll use the low-level commander for takeoff.
                    self._motion_commander = mc
                    self._is_flying = False
                    print("[Bridge] Ready. Waiting for takeoff command...")

                    try:
                        while self._running:
                            try:
                                cmd = self._command_queue.get_nowait()
                                self._dispatch_command(cmd)
                            except queue.Empty:
                                pass
                            # Dead-man switch: stale velocity -> hover.
                            if (
                                self._is_flying
                                and self._velocity_deadline is not None
                                and time.time() > self._velocity_deadline
                                and self._motion_commander is not None
                            ):
                                print("[Bridge] Velocity watchdog expired -> hover")
                                try:
                                    self._motion_commander.start_linear_motion(0, 0, 0, 0)
                                except Exception:
                                    pass
                                self._velocity_deadline = None
                            # Link-silence watchdog: no telemetry frame for
                            # LINK_SILENT_S means the radio link died without
                            # raising (legacy firmware) — force a reconnect.
                            if (
                                self._last_telemetry
                                and time.time() - self._last_telemetry > LINK_SILENT_S
                            ):
                                print(f"[Bridge] No telemetry for {LINK_SILENT_S}s — forcing reconnect")
                                raise ConnectionError("telemetry link watchdog")
                            time.sleep(0.01)
                    finally:
                        # Shutdown — land and properly exit MotionCommander
                        if self._is_flying:
                            print("[Bridge] Landing drone...")
                            try:
                                self._gentle_land()
                            except Exception as e:
                                print(f"[Bridge] Land failed: {e}")
                            # Properly exit MotionCommander context
                            try:
                                mc.__exit__(None, None, None)
                            except Exception:
                                pass
                        # Always send stop setpoint to reset drone commander state
                        try:
                            scf.cf.commander.send_stop_setpoint()
                        except Exception:
                            pass
                        time.sleep(0.3)
                        self._motion_commander = None
                        self._is_flying = False
                        print("[Bridge] Drone connection clean.")

            except Exception as e:
                self._cf_failures += 1
                if self._cf_failures == 1 or self._cf_failures % 30 == 0:
                    print(f"[Bridge] Crazyflie error (attempt {self._cf_failures}): {e}")
                self._motion_commander = None
                self._scf = None
                if self._running:
                    time.sleep(2)

    def _setup_logging(self, cf):
        """Register log blocks for position, attitude, and battery."""
        with self._suppress_stderr():
            log_pos = LogConfig(name='Position', period_in_ms=self.telemetry_period_ms)
            log_pos.add_variable('stateEstimate.x', 'float')
            log_pos.add_variable('stateEstimate.y', 'float')
            log_pos.add_variable('stateEstimate.z', 'float')
            cf.log.add_config(log_pos)
            log_pos.data_received_cb.add_callback(self._on_position)
            log_pos.start()

            log_stab = LogConfig(name='Stabilizer', period_in_ms=self.telemetry_period_ms)
            log_stab.add_variable('stabilizer.roll', 'float')
            log_stab.add_variable('stabilizer.pitch', 'float')
            log_stab.add_variable('stabilizer.yaw', 'float')
            cf.log.add_config(log_stab)
            log_stab.data_received_cb.add_callback(self._on_attitude)
            log_stab.start()

            log_batt = LogConfig(name='Battery', period_in_ms=1000)
            log_batt.add_variable('pm.vbat', 'FP16')
            cf.log.add_config(log_batt)
            log_batt.data_received_cb.add_callback(self._on_battery)
            log_batt.start()

    # ------------------------------------------------------------------ #
    #  Telemetry callbacks (Crazyflie thread -> asyncio queue)
    # ------------------------------------------------------------------ #

    def _on_position(self, timestamp, data, logconf):
        self._last_telemetry = time.time()
        z = data.get('stateEstimate.z', data.get('kalman.stateZ', 0))
        self._current_z = z
        self._enqueue_telemetry("position", timestamp, {
            "x": data.get('stateEstimate.x', data.get('kalman.stateX', 0)),
            "y": data.get('stateEstimate.y', data.get('kalman.stateY', 0)),
            "z": z
        })

    def _on_attitude(self, timestamp, data, logconf):
        self._enqueue_telemetry("attitude", timestamp, {
            "roll": data.get('stabilizer.roll', 0),
            "pitch": data.get('stabilizer.pitch', 0),
            "yaw": data.get('stabilizer.yaw', 0)
        })

    def _on_battery(self, timestamp, data, logconf):
        self._enqueue_telemetry("battery", timestamp, {
            "voltage": data.get('pm.vbat', 0)
        })

    def _enqueue_telemetry(self, category, timestamp, payload):
        """Marshal telemetry from Crazyflie callbacks into the asyncio queue."""
        if self._loop is None or not self._loop.is_running():
            return

        telem = {
            "type": "telemetry",
            "category": category,
            "timestamp": timestamp,
            "data": payload
        }

        async def _put():
            try:
                self._telemetry_queue.put_nowait(telem)
            except asyncio.QueueFull:
                pass  # Drop if back-pressured

        asyncio.run_coroutine_threadsafe(_put(), self._loop)

    # ------------------------------------------------------------------ #
    #  Descent speed limiting & gentle landing
    # ------------------------------------------------------------------ #

    def _clamp_descent(self, vz):
        """
        Scale down the descent speed when the drone is below 0.5 m.

        Returns a negative (downward) velocity whose magnitude is reduced
        proportionally to the current height:
          - At 0.5 m or above:  full requested speed
          - At 0.25 m:          ~half speed
          - At 0.10 m:          ~20 % speed  (minimum 0.03 m/s)
        """
        z = max(self._current_z, 0.0)
        threshold = 0.5          # metres – start slowing below this
        min_speed = 0.03         # m/s – never slower than this (avoids stall)

        if z >= threshold:
            return vz            # above threshold, full speed

        scale = max(z / threshold, min_speed / abs(vz) if vz != 0 else 0)
        return vz * scale

    def _gentle_land(self):
        """
        Land the drone with a slow, controlled descent instead of the
        default MotionCommander.land() which can be abrupt.

        Strategy: descend at progressively slower speeds as height decreases,
        then stop motors once effectively on the ground.
        Includes a timeout to avoid blocking forever if telemetry stops.
        """
        mc = self._motion_commander
        if mc is None:
            return

        print("[Bridge] Gentle landing...")
        deadline = time.time() + 5.0  # max 5 seconds for landing

        # Phase 1: descend to ~0.15 m at a moderate speed
        while self._current_z > 0.15 and time.time() < deadline:
            speed = max(0.05, min(0.2, self._current_z * 0.4))
            mc.start_linear_motion(0, 0, -speed, 0)
            time.sleep(0.05)

        # Phase 2: very slow final descent
        while self._current_z > 0.04 and time.time() < deadline:
            mc.start_linear_motion(0, 0, -0.03, 0)
            time.sleep(0.05)

        # Phase 3: cut motors
        try:
            mc.stop()
        except Exception:
            pass
        if self._scf:
            try:
                self._scf.cf.commander.send_stop_setpoint()
            except Exception:
                pass
        # Reset the MotionCommander state machine — the gentle-land path
        # bypasses cflib's land(), so we must reproduce its bookkeeping:
        # stop the setpoint thread, notify the high-level commander, and
        # clear _is_flying. Without this the next take_off() raises
        # "Already flying" and the drone is stuck on the ground.
        try:
            if mc._thread is not None:
                mc._thread.stop()
                mc._thread = None
        except Exception:
            pass
        if self._scf:
            try:
                self._scf.cf.commander.send_notify_setpoint_stop()
            except Exception:
                pass
        try:
            mc._is_flying = False
        except Exception:
            pass
        time.sleep(0.3)
        print("[Bridge] Landed.")

    # ------------------------------------------------------------------ #
    #  Command dispatch (Crazyflie thread)
    # ------------------------------------------------------------------ #

    def _do_takeoff(self, height=0.5):
        """
        Perform takeoff by entering the MotionCommander context.
        __enter__() resets the estimator and takes off to default_height.
        """
        if self._is_flying:
            return
        # __enter__ handles: reset estimator -> start setpoint thread -> take_off
        self._motion_commander.__enter__()
        self._is_flying = True
        print(f"[Bridge] Takeoff complete (target {height}m)")

    def _dispatch_command(self, cmd):
        """Execute a high-level motion command on the drone."""
        if self._motion_commander is None:
            print("[Bridge] Command dropped: MotionCommander not ready")
            return

        action = cmd.get("action")
        print(f"[Bridge] CMD >> {action}  {cmd}")

        # USB-cable interlock: refuse anything that would spin up for takeoff.
        wants_takeoff = action == "takeoff" or (
            action == "move" and (cmd.get("vz") or 0) > 0 and not self._is_flying
        )
        if wants_takeoff and self._usb_takeoff_blocked:
            reason = ("CF_NO_FLY dry-run mode" if self._no_fly
                      else "drone is tethered via USB "
                      "(unplug the cable / use the radio link to fly)")
            print(f"[Bridge] {action} REFUSED: {reason}")
            return

        try:
            if action == "takeoff":
                self._velocity_deadline = None
                self._do_takeoff(height=cmd.get("height", 0.5))
            elif action == "land":
                self._velocity_deadline = None
                if self._is_flying:
                    self._gentle_land()
                    self._is_flying = False
            elif action == "stop":
                self._velocity_deadline = None
                if self._is_flying:
                    self._motion_commander.stop()
            elif action == "estop":
                # EMERGENCY motor cut (mid-air): kill the setpoint thread
                # FIRST so nothing re-arms the commander, then cut thrust
                # immediately — no landing profile, the drone falls. The
                # link stays up and a fresh MotionCommander is staged, so
                # the next takeoff works without reconnecting.
                self._velocity_deadline = None
                try:
                    self._motion_commander._thread.stop()
                except Exception:
                    pass
                try:
                    self._scf.cf.commander.send_stop_setpoint()
                except Exception:
                    pass
                self._is_flying = False
                self._motion_commander = MotionCommander(self._scf, default_height=0.5)
                print("[Bridge] EMERGENCY STOP: motors cut.")
            elif action == "move":
                vx = cmd.get("vx") or 0
                vy = cmd.get("vy") or 0
                vz = cmd.get("vz") or 0
                yawrate = cmd.get("yawrate") or 0

                # If not flying yet and user pushes up, treat as takeoff
                if not self._is_flying:
                    if vz > 0:
                        self._do_takeoff()
                    return

                # Clamp all velocities to safe range for Crazyflie
                MAX_XY = 0.5   # m/s horizontal
                MAX_Z = 0.5    # m/s vertical
                MAX_YAW = 120  # deg/s
                vx = max(-MAX_XY, min(MAX_XY, vx))
                vy = max(-MAX_XY, min(MAX_XY, vy))
                vz = max(-MAX_Z, min(MAX_Z, vz))
                yawrate = max(-MAX_YAW, min(MAX_YAW, yawrate))

                # Clamp downward speed when close to ground
                if vz < 0:
                    vz = self._clamp_descent(vz)
                self._motion_commander.start_linear_motion(vx, vy, vz, yawrate)
                # Arm the dead-man switch on nonzero velocity, disarm on hover.
                if vx or vy or vz or yawrate:
                    self._velocity_deadline = time.time() + MOVE_WATCHDOG_S
                else:
                    self._velocity_deadline = None
            elif action == "up":
                self._motion_commander.up(cmd.get("distance", 0.2))
            elif action == "down":
                self._motion_commander.down(cmd.get("distance", 0.2),
                                            velocity=self._clamp_descent(-0.2))
            elif action == "forward":
                self._motion_commander.forward(cmd.get("distance", 0.2))
            elif action == "back":
                self._motion_commander.back(cmd.get("distance", 0.2))
            elif action == "left":
                self._motion_commander.left(cmd.get("distance", 0.2))
            elif action == "right":
                self._motion_commander.right(cmd.get("distance", 0.2))
            else:
                print(f"[Bridge] Unknown action: {action}")
        except Exception as e:
            print(f"[Bridge] Command failed: {e}")


# ---------------------------------------------------------------------- #
#  Entry point
# ---------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description="Crazyflie WebSocket Bridge")
    parser.add_argument("--cf-uri", default="radio://0/80/2M/E7E7E7E7E7",
                        help="Crazyflie URI (default: radio://0/80/2M/E7E7E7E7E7)")
    parser.add_argument("--port", type=int, default=8765,
                        help="WebSocket server port (default: 8765)")
    parser.add_argument("--telemetry-hz", type=int, default=10,
                        help="Telemetry publish rate in Hz (default: 10)")
    args = parser.parse_args()

    bridge = CrazyflieBridge(
        cf_uri=args.cf_uri,
        port=args.port,
        telemetry_hz=args.telemetry_hz
    )

    bridge.start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    _sig_count = 0

    def handle_signal(sig, frame):
        nonlocal _sig_count
        _sig_count += 1
        if _sig_count >= 2:
            # Force exit on second Ctrl+C
            print("\n[Bridge] Forced exit.")
            os._exit(0)
        print("\n[Bridge] Shutting down (press Ctrl+C again to force)...")
        bridge.stop()
        # Cancel all asyncio tasks to unblock the event loop
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        loop.run_until_complete(bridge.run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        bridge.stop()
        bridge.join(timeout=5)
        loop.close()
        print("[Bridge] Exited.")
        os._exit(0)


if __name__ == "__main__":
    main()

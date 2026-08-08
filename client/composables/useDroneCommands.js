import { reactive, readonly } from 'vue';

/**
 * Real-drone flight commands — the separated module for the frequently used
 * drone functions (takeoff / land / hover / move / ...). Mirrors the
 * telemetry pipeline in reverse:
 *
 *   this module (browser)
 *     -> WS /api/drone/command            (FastAPI: validate + whitelist)
 *       -> telemetry_relay.py command_forwarder()
 *         -> motion_control_ws.py (owns the Crazyflie link) -> drone
 *
 * Safety rules:
 *  - Commands are NEVER queued: if the link is not OPEN, the command is
 *    dropped and `false` is returned — a stale buffered takeoff is far worse
 *    than a dropped click.
 *  - The server whitelists/clamps everything again; this module only builds
 *    the same schema motion_control_ws._handle_command accepts.
 *  - The bridge additionally refuses `takeoff` while the drone is on a USB
 *    cable (CF_ALLOW_USB_TAKEOFF=1 overrides for bench tests).
 *
 * Every command gets an ack frame from the server:
 *   {"type":"ack","action":"takeoff","delivered":true|false,"reason"?"..."}
 * `delivered` means "forwarded to the desktop relay" (the bridge may still
 * refuse it, e.g. the USB interlock — its refusal appears in the bridge log).
 */

const WS_URL = import.meta.env.DEV
  ? 'ws://localhost:8000/api/drone/command'
  : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/drone/command`;

const RECONNECT_MS = 2000;
const CONNECT_TIMEOUT_MS = 10000; // initial page load can starve the handshake

const state = reactive({
  link: false,        // command WebSocket is OPEN
  lastAck: null,      // {action, delivered, reason?, at} of the most recent ack
});

let ws = null;
let started = false;

function connect() {
  let opened = false;
  let settled = false;
  const retry = () => {
    if (settled) return;
    settled = true;
    ws = null;
    setTimeout(connect, RECONNECT_MS);
  };
  const watchdog = setTimeout(() => {
    if (opened) return;
    try { ws.close(); } catch { /* noop */ }
    retry();
  }, CONNECT_TIMEOUT_MS);

  ws = new WebSocket(WS_URL);
  ws.onopen = () => {
    opened = true;
    state.link = true;
    clearTimeout(watchdog);
  };
  ws.onmessage = (e) => {
    let frame;
    try { frame = JSON.parse(e.data); } catch { return; }
    if (frame.type === 'ack') {
      state.lastAck = {
        action: frame.action || '',
        delivered: !!frame.delivered,
        reason: frame.reason || '',
        at: Date.now(),
      };
    }
  };
  ws.onclose = () => {
    state.link = false;
    clearTimeout(watchdog);
    retry();
  };
  ws.onerror = () => ws.close();
}

function ensureStarted() {
  if (!started) {
    started = true;
    connect();
  }
}

/** Low-level send. Returns false when the link is down (command dropped). */
function sendCommand(cmd) {
  ensureStarted();
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  ws.send(JSON.stringify(cmd));
  return true;
}

// --- Frequently used drone functions ----------------------------------------
// All return true when the command was sent towards the server, false when
// it was dropped (link down). Thin conveniences over the bridge schema of
// motion_control_ws._dispatch_command (the bridge spells yaw "yawrate").

export function useDroneCommands() {
  ensureStarted();
  return {
    commands: readonly(state),

    /** Take off and hover (bridge MotionCommander default height, ~0.5 m). */
    takeoff(height = 0.5) {
      return sendCommand({ action: 'takeoff', height });
    },
    /** Gentle landing (the bridge's land is already the slow profile). */
    land() {
      return sendCommand({ action: 'land' });
    },
    /** Stop in place: zero velocity, keeps flying (bridge hover). */
    stop() {
      return sendCommand({ action: 'stop' });
    },
    /** EMERGENCY stop: cut the motors immediately — the drone falls, even mid-air. */
    estop() {
      return sendCommand({ action: 'estop' });
    },
    /**
     * Continuous velocity command (m/s, deg/s). The bridge re-applies the
     * last velocity via MotionCommander.start_linear_motion, so send
     * hover() / move({}) to level off.
     */
    move({ vx = 0, vy = 0, vz = 0, yawRate = 0 } = {}) {
      return sendCommand({ action: 'move', vx, vy, vz, yawrate: yawRate });
    },
    /** Hold position (zero velocities, keeps flying). */
    hover() {
      return sendCommand({ action: 'move', vx: 0, vy: 0, vz: 0, yawrate: 0 });
    },
    /** Climb at vz m/s (default +0.15). */
    ascend(vz = 0.15) {
      return sendCommand({ action: 'move', vx: 0, vy: 0, vz, yawrate: 0 });
    },
    /** Descend at vz m/s (default 0.15 downward). */
    descend(vz = 0.15) {
      return sendCommand({ action: 'move', vx: 0, vy: 0, vz: -Math.abs(vz), yawrate: 0 });
    },
    /** One-shot relative moves (0.05–1.0 m, default 0.2). */
    up(distance = 0.2) {
      return sendCommand({ action: 'up', distance });
    },
    down(distance = 0.2) {
      return sendCommand({ action: 'down', distance });
    },
    forward(distance = 0.2) {
      return sendCommand({ action: 'forward', distance });
    },
    back(distance = 0.2) {
      return sendCommand({ action: 'back', distance });
    },
    left(distance = 0.2) {
      return sendCommand({ action: 'left', distance });
    },
    right(distance = 0.2) {
      return sendCommand({ action: 'right', distance });
    },
  };
}

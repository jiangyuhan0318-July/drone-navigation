import { reactive, ref } from 'vue';

const FLIGHT_SENSITIVITY = 3;

const flight = reactive({ mode: 'M', vx: 0, vy: 0, yaw: 0, vz: 0 });
const flightCmd = reactive({ mode: 'M', vx: 0, vy: 0, yaw: 0, vz: 0 });
const activeFlightMode = ref('M');
const showFlight = ref(true);

const pressedKeys = new Set();
let keydownHandler = null;
let keyupHandler = null;
let listenersAttached = false;

function isFlightKey(key) {
  return ['w', 'a', 's', 'd'].includes(key);
}

function isTypingTarget(target) {
  return (
    target &&
    (target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.isContentEditable)
  );
}

function updateKeyboardInput() {
  const w = pressedKeys.has('w');
  const a = pressedKeys.has('a');
  const s = pressedKeys.has('s');
  const d = pressedKeys.has('d');

  if (!showFlight.value) return;

  if (activeFlightMode.value === 'M') {
    const vx = ((a ? -1 : 0) + (d ? 1 : 0)) * FLIGHT_SENSITIVITY;
    const vy = ((s ? -1 : 0) + (w ? 1 : 0)) * FLIGHT_SENSITIVITY;
    onFlightMove({ mode: 'M', vx, vy });
  } else if (activeFlightMode.value === 'R') {
    const yaw = (((w || a) ? -1 : 0) + ((s || d) ? 1 : 0)) * FLIGHT_SENSITIVITY;
    onFlightMove({ mode: 'R', yaw });
  } else if (activeFlightMode.value === 'H') {
    const vz = ((s ? -1 : 0) + (w ? 1 : 0)) * FLIGHT_SENSITIVITY;
    onFlightMove({ mode: 'H', vz });
  }
}

function handleKeyDown(e) {
  if (isTypingTarget(e.target)) return;
  const key = e.key.toLowerCase();
  if (!isFlightKey(key)) return;
  e.preventDefault();
  if (pressedKeys.has(key)) return;
  pressedKeys.add(key);
  updateKeyboardInput();
}

function handleKeyUp(e) {
  if (isTypingTarget(e.target)) return;
  const key = e.key.toLowerCase();
  if (!isFlightKey(key)) return;
  e.preventDefault();
  pressedKeys.delete(key);
  if (!['w', 'a', 's', 'd'].some((k) => pressedKeys.has(k))) {
    onFlightStop();
  }
  updateKeyboardInput();
}

function startKeyboard() {
  if (listenersAttached) return;
  keydownHandler = handleKeyDown;
  keyupHandler = handleKeyUp;
  window.addEventListener('keydown', keydownHandler);
  window.addEventListener('keyup', keyupHandler);
  listenersAttached = true;
}

function stopKeyboard() {
  if (!listenersAttached) return;
  window.removeEventListener('keydown', keydownHandler);
  window.removeEventListener('keyup', keyupHandler);
  listenersAttached = false;
}

function onFlightModeChange(mode) {
  activeFlightMode.value = mode;
  flight.mode = mode;
  flightCmd.mode = mode;
  updateKeyboardInput();
}

function onFlightMove(payload) {
  if (typeof payload === 'object' && payload.mode) {
    activeFlightMode.value = payload.mode;
    flight.mode = payload.mode;
    flightCmd.mode = payload.mode;
    if (payload.mode === 'M') {
      flightCmd.vx = payload.vx ?? 0;
      flightCmd.vy = payload.vy ?? 0;
      flightCmd.yaw = 0;
      flightCmd.vz = 0;
    } else if (payload.mode === 'R') {
      flightCmd.vx = 0;
      flightCmd.vy = 0;
      flightCmd.yaw = payload.yaw ?? 0;
      flightCmd.vz = 0;
    } else if (payload.mode === 'H') {
      flightCmd.vx = 0;
      flightCmd.vy = 0;
      flightCmd.yaw = 0;
      flightCmd.vz = payload.vz ?? 0;
    }
  } else {
    // Fallback for non-cycling emission.
    flightCmd.vx = payload ?? 0;
    flightCmd.vy = 0;
  }
}

function onFlightStop() {
  flightCmd.vx = 0;
  flightCmd.vy = 0;
  flightCmd.yaw = 0;
  flightCmd.vz = 0;
  flight.vx = 0;
  flight.vy = 0;
  flight.yaw = 0;
  flight.vz = 0;
}

function toggleFlight() {
  showFlight.value = !showFlight.value;
}

export function useFlightCommands() {
  return {
    flight,
    flightCmd,
    activeFlightMode,
    showFlight,
    toggleFlight,
    onFlightMove,
    onFlightStop,
    onFlightModeChange,
    startKeyboard,
    stopKeyboard,
  };
}

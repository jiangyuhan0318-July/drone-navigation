import { reactive, ref } from 'vue';

const CAMERA_SENSITIVITY = 1;

const camera = reactive({ mode: 'Z', yaw: 0, pitch: 0, roll: 0 });
const cameraCmd = reactive({ mode: 'Z', yaw: 0, pitch: 0, roll: 0 });
const activeCameraMode = ref('Z');
const showCamera = ref(true);

const pressedKeys = new Set();
let keydownHandler = null;
let keyupHandler = null;
let listenersAttached = false;

function isCameraKey(key) {
  return ['arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(key);
}

function updateKeyboardInput() {
  const up = pressedKeys.has('arrowup');
  const down = pressedKeys.has('arrowdown');
  const left = pressedKeys.has('arrowleft');
  const right = pressedKeys.has('arrowright');

  if (!showCamera.value) return;

  const value = (((up || left) ? -1 : 0) + ((down || right) ? 1 : 0)) * CAMERA_SENSITIVITY;
  // Z -> yaw, Y -> pitch (inverted so up/left looks up), X -> roll.
  if (activeCameraMode.value === 'Z') {
    onCameraMove({ mode: 'Z', yaw: value });
  } else if (activeCameraMode.value === 'Y') {
    onCameraMove({ mode: 'Y', pitch: -value });
  } else if (activeCameraMode.value === 'X') {
    onCameraMove({ mode: 'X', roll: value });
  }
}

function handleKeyDown(e) {
  const key = e.key.toLowerCase();
  if (!isCameraKey(key)) return;
  e.preventDefault();
  if (pressedKeys.has(key)) return;
  pressedKeys.add(key);
  updateKeyboardInput();
}

function handleKeyUp(e) {
  const key = e.key.toLowerCase();
  if (!isCameraKey(key)) return;
  e.preventDefault();
  pressedKeys.delete(key);
  if (!['arrowup', 'arrowdown', 'arrowleft', 'arrowright'].some((k) => pressedKeys.has(k))) {
    onCameraStop();
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

function onCameraModeChange(mode) {
  activeCameraMode.value = mode;
  camera.mode = mode;
  cameraCmd.mode = mode;
  updateKeyboardInput();
}

function onCameraMove(payload) {
  if (typeof payload === 'object' && payload.mode) {
    activeCameraMode.value = payload.mode;
    camera.mode = payload.mode;
    cameraCmd.mode = payload.mode;
    cameraCmd.yaw = payload.yaw ?? 0;
    cameraCmd.pitch = payload.pitch ?? 0;
    cameraCmd.roll = payload.roll ?? 0;
  } else {
    // Fallback for non-cycling emission.
    cameraCmd.yaw = payload ?? 0;
    cameraCmd.pitch = 0;
  }
}

function onCameraStop() {
  cameraCmd.yaw = 0;
  cameraCmd.pitch = 0;
  cameraCmd.roll = 0;
  camera.yaw = 0;
  camera.pitch = 0;
  camera.roll = 0;
}

function toggleCamera() {
  showCamera.value = !showCamera.value;
}

export function useCameraCommands() {
  return {
    camera,
    cameraCmd,
    activeCameraMode,
    showCamera,
    toggleCamera,
    onCameraMove,
    onCameraStop,
    onCameraModeChange,
    startKeyboard,
    stopKeyboard,
  };
}

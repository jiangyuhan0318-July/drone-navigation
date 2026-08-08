<script setup>
import { ref, computed } from 'vue';
import ConfigurableIcon from './ConfigurableIcon.vue';

const props = defineProps({
  /**
   * Joystick operating mode.
   * - 'flight': 4-directional flight control arrows.
   * - 'camera': yaw/pitch gimbal control with angle indicator.
   */
  mode: {
    type: String,
    default: 'flight',
    validator: (value) => ['flight', 'camera'].includes(value),
  },
  /** Diameter of the joystick track in pixels. */
  size: {
    type: Number,
    default: 224,
  },
  /** Normalized maximum stick displacement (0..1). */
  maxDistance: {
    type: Number,
    default: 1,
  },
  /** Sensitivity multiplier applied to emitted values. */
  sensitivity: {
    type: Number,
    default: 1,
  },
  /**
   * When true, the joystick cycles between sub-modes by pressing the center
   * knob: M/R/H for flight and X/Y/Z for camera.
   */
  enableModeCycle: {
    type: Boolean,
    default: false,
  },
  /** Configurable icon keys. */
  icons: {
    type: Object,
    default: () => ({
      flightMove: 'FLIGHT_MOVE',
      flightRotate: 'FLIGHT_ROTATE',
      flightHeight: 'FLIGHT_HEIGHT',
      cameraRotate: 'CAMERA_ROTATE',
      pitch: 'CAMERA_PITCH',
    }),
  },
  /** When true, the joystick is disabled and ignores all input. */
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['move', 'stop', 'modeChange']);

const trackRef = ref(null);
const dragging = ref(false);
const position = ref({ x: 0, y: 0 });
const lastTouchTime = ref(0);

// Mode-cycling state (used when enableModeCycle is true)
const flashChar = ref(null);
const pressedCenter = ref(false);
const centerPressOrigin = ref({ x: 0, y: 0 });

const isModeCycling = computed(() => props.enableModeCycle);

const cyclingModes = computed(() => {
  if (props.mode === 'flight') return ['M', 'R', 'H'];
  if (props.mode === 'camera') return ['Z', 'Y', 'X'];
  return [];
});

const cyclingMode = ref(cyclingModes.value[0] ?? null);

const trackStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}));

const knobStyle = computed(() => {
  const radius = props.size / 2;
  const maxPx = radius * 0.55; // knob travel limit inside the track
  const x = position.value.x * maxPx;
  const y = position.value.y * maxPx;
  return {
    transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`,
  };
});

const wedgeStyle = computed(() => {
  const angle = Math.atan2(position.value.y, position.value.x) * (180 / Math.PI);
  return {
    transform: `translate(-50%, -50%) rotate(${angle}deg)`,
  };
});

const modeLabel = computed(() => {
  if (isModeCycling.value) return cyclingMode.value;
  if (props.mode === 'camera') return 'C';
  return 'F';
});

/**
 * Convert a pointer position to normalized coordinates relative to the
 * joystick center. Logic mirrors the reference PWA implementation.
 */
function getRelativePos(clientX, clientY) {
  if (!trackRef.value) return { dx: 0, dy: 0, dist: 0 };
  const rect = trackRef.value.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const dx = (clientX - cx) / (rect.width / 2);
  const dy = (clientY - cy) / (rect.height / 2);
  const dist = Math.sqrt(dx * dx + dy * dy);
  return { dx, dy, dist };
}

function clampInput(dx, dy) {
  const dist = Math.sqrt(dx * dx + dy * dy);
  if (dist <= props.maxDistance) return { x: dx, y: dy };
  const scale = props.maxDistance / dist;
  return { x: dx * scale, y: dy * scale };
}

function applyInput(dx, dy) {
  const clamped = clampInput(dx, dy);
  position.value = clamped;

  if (isModeCycling.value) {
    // Filter and emit payload based on the active sub-mode.
    const m = cyclingMode.value;
    if (props.mode === 'flight') {
      switch (m) {
        case 'M':
          // Movement: full 2D control (pitch/roll and forward/backward speed).
          emit('move', {
            mode: 'M',
            vx: clamped.x * props.sensitivity,
            vy: -clamped.y * props.sensitivity,
          });
          break;
        case 'R':
          // Rotate: yaw only. Lat/lon/alt remain unchanged by the consumer.
          emit('move', {
            mode: 'R',
            yaw: clamped.x * props.sensitivity,
          });
          break;
        case 'H':
          // Height/Altitude: vertical only. Lat/lon remain unchanged by the consumer.
          emit('move', {
            mode: 'H',
            vz: -clamped.y * props.sensitivity,
          });
          break;
      }
    } else if (props.mode === 'camera') {
      // Gimbal X/Y/Z single-axis control.
      // Z -> yaw, Y -> pitch, X -> roll.
      switch (m) {
        case 'Z':
          emit('move', { mode: 'Z', yaw: clamped.x * props.sensitivity });
          break;
        case 'Y':
          emit('move', { mode: 'Y', pitch: -clamped.y * props.sensitivity });
          break;
        case 'X':
          emit('move', { mode: 'X', roll: clamped.x * props.sensitivity });
          break;
      }
    }
  } else {
    // Standard single-mode emission for backwards compatibility.
    emit('move', clamped.x * props.sensitivity, -clamped.y * props.sensitivity);
  }
}

function cycleMode() {
  if (props.disabled) return;
  const modes = cyclingModes.value;
  const idx = modes.indexOf(cyclingMode.value);
  const next = modes[(idx + 1) % modes.length];
  cyclingMode.value = next;
  flashChar.value = next;
  emit('modeChange', next);
  setTimeout(() => {
    flashChar.value = null;
  }, 600);
}

function handleStart(e) {
  if (props.disabled) return;
  const { dx, dy, dist } = getRelativePos(e.clientX, e.clientY);
  // Ignore synthetic mouse events after touch.
  if (e.pointerType === 'touch') {
    lastTouchTime.value = Date.now();
  } else if (Date.now() - lastTouchTime.value < 500) {
    return;
  }
  e.preventDefault();
  trackRef.value?.setPointerCapture(e.pointerId);

  if (isModeCycling.value && dist < 0.35) {
    // Center press initiates mode cycle (matches reference PWA behavior).
    pressedCenter.value = true;
    centerPressOrigin.value = { x: e.clientX, y: e.clientY };
    return;
  }

  dragging.value = true;
  applyInput(dx, dy);
}

function handleMove(e) {
  if (props.disabled) return;
  if (e.pointerType === 'mouse' && Date.now() - lastTouchTime.value < 500) return;
  e.preventDefault();

  if (pressedCenter.value) {
    const moved = Math.sqrt(
      Math.pow(e.clientX - centerPressOrigin.value.x, 2) +
      Math.pow(e.clientY - centerPressOrigin.value.y, 2)
    );
    if (moved > 8) {
      // User dragged out of the center knob; treat as a drag input.
      pressedCenter.value = false;
      dragging.value = true;
      const { dx, dy } = getRelativePos(e.clientX, e.clientY);
      applyInput(dx, dy);
    }
    return;
  }

  if (!dragging.value) return;
  const { dx, dy } = getRelativePos(e.clientX, e.clientY);
  applyInput(dx, dy);
}

function handleEnd(e) {
  if (props.disabled) return;
  if (pressedCenter.value) {
    pressedCenter.value = false;
    cycleMode();
    emit('stop');
    return;
  }

  if (!dragging.value) return;
  dragging.value = false;
  position.value = { x: 0, y: 0 };
  try {
    trackRef.value?.releasePointerCapture(e.pointerId);
  } catch {
    // releasePointerCapture throws if pointer is not currently captured.
  }
  emit('stop');
}
</script>

<template>
  <div
    ref="trackRef"
    class="joystick-track"
    :class="{ 'joystick-track--disabled': disabled }"
    :style="trackStyle"
    @pointerdown="handleStart"
    @pointermove="handleMove"
    @pointerup="handleEnd"
    @pointercancel="handleEnd"
  >
    <!-- Flight mode glyphs: movement arrows for M, rotation arcs for R, vertical arrows for H -->
    <template v-if="mode === 'flight' && (!isModeCycling || cyclingMode === 'M')">
      <div class="glyph-svg">
        <ConfigurableIcon :name="icons.flightMove" :size="224" color="rgba(107,114,128,0.6)" />
      </div>
    </template>

    <!-- Rotation arcs for flight R mode -->
    <template v-if="mode === 'flight' && cyclingMode === 'R'">
      <div class="glyph-svg">
        <ConfigurableIcon :name="icons.flightRotate" :size="224" color="rgba(107,114,128,0.6)" />
      </div>
    </template>

    <!-- Rotation arcs for camera mode -->
    <template v-if="mode === 'camera'">
      <div class="glyph-svg">
        <ConfigurableIcon :name="icons.cameraRotate" :size="224" color="rgba(107,114,128,0.6)" />
      </div>
    </template>

    <!-- Height mode: vertical arrows -->
    <template v-if="mode === 'flight' && cyclingMode === 'H'">
      <div class="glyph-svg">
        <ConfigurableIcon :name="icons.flightHeight" :size="224" color="rgba(107,114,128,0.6)" />
      </div>
    </template>

    <!-- Movable control knob -->
    <div
      class="joystick-knob"
      :class="{ 'joystick-knob--active': dragging }"
      :style="knobStyle"
    >
      <div
        v-if="mode === 'camera' && (position.x !== 0 || position.y !== 0)"
        class="knob-pointer"
        :style="wedgeStyle"
      >
        <ConfigurableIcon :name="icons.pitch" :size="16" color="rgba(107,114,128,0.8)" />
      </div>
      <span
        v-else
        class="knob-label"
        :class="{ 'knob-label--flash': flashChar }"
      >
        {{ flashChar ?? modeLabel }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.joystick-track {
  position: relative;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.18);
  backdrop-filter: blur(6px);
  border: 2px solid rgba(255, 255, 255, 0.45);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2), inset 0 0 20px rgba(255, 255, 255, 0.08);
  touch-action: none;
  user-select: none;
  cursor: pointer;
  flex-shrink: 0;
}

.joystick-track--disabled {
  opacity: 0.35;
  pointer-events: none;
  cursor: not-allowed;
}

.glyph {
  position: absolute;
  display: flex;
  align-items: center;
  justify-content: center;
}

.glyph-top {
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
}

.glyph-bottom {
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
}

.glyph-left {
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
}

.glyph-right {
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
}

.glyph-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
}

.glyph-svg :deep(svg),
.glyph-svg :deep(img) {
  width: 100%;
  height: 100%;
  pointer-events: none;
  -webkit-user-drag: none;
  user-select: none;
}

.joystick-knob {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.55);
  border: 2px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s ease, border-color 0.15s ease;
  pointer-events: none;
}

.joystick-knob--active {
  background: rgba(200, 210, 230, 0.65);
  border-color: rgba(255, 255, 255, 0.85);
}

.knob-label {
  font-family: Calibri, 'Segoe UI', sans-serif;
  font-size: 1.25rem;
  font-weight: 700;
  color: rgba(30, 40, 60, 0.95);
  text-shadow: 0 1px 2px rgba(255, 255, 255, 0.5);
  transition: color 0.15s ease;
}

.joystick-knob--active .knob-label {
  color: rgba(255, 255, 255, 0.9);
}

.knob-label--flash {
  color: #4ade80 !important;
}

.knob-pointer {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>

<script setup>
import { useI18n } from 'vue-i18n';
import AppDock from './AppDock.vue';
import FlightController from './FlightController.vue';
import GimbalController from './GimbalController.vue';
import HUD from './HUD.vue';

const { t } = useI18n();

defineProps({
  leftItems: { type: Array, default: () => [] },
  rightItems: { type: Array, default: () => [] },
  showFlight: { type: Boolean, default: true },
  showCamera: { type: Boolean, default: true },
  showHud: { type: Boolean, default: true },
  flight: { type: Object, default: () => ({ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }) },
  camera: { type: Object, default: () => ({ mode: '-', yaw: 0, pitch: 0, roll: 0 }) },
  // Real-drone telemetry override for the HUD (Real Drone page); when set,
  // the HUD renders the physical drone's live state instead of the sim rows.
  realTelemetry: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
});

defineEmits([
  'flightMove',
  'flightStop',
  'flightModeChange',
  'cameraMove',
  'cameraStop',
  'cameraModeChange',
  'dockItemClick',
]);
</script>

<template>
  <div class="view-composer">
    <slot name="background" />

    <slot name="top-overlay" />

    <AppDock
      position="left"
      :items="leftItems"
      @itemClick="$emit('dockItemClick', $event)"
    />

    <main class="control-area">
      <div class="joystick-pair">
        <div
          class="joystick-group"
          :class="{ 'joystick-group--hidden': !showCamera }"
        >
          <GimbalController
            :size="224"
            :sensitivity="1"
            enable-mode-cycle
            :disabled="disabled"
            @move="$emit('cameraMove', $event)"
            @stop="$emit('cameraStop')"
            @modeChange="$emit('cameraModeChange', $event)"
          />
          <span class="joystick-label">{{ t('viewcomposer.gimbal') }}</span>
        </div>

        <div
          class="joystick-group"
          :class="{ 'joystick-group--hidden': !showFlight }"
        >
          <FlightController
            :size="224"
            :sensitivity="3"
            enable-mode-cycle
            :disabled="disabled"
            @move="$emit('flightMove', $event)"
            @stop="$emit('flightStop')"
            @modeChange="$emit('flightModeChange', $event)"
          />
          <span class="joystick-label">{{ t('viewcomposer.flight') }}</span>
        </div>
      </div>
    </main>

    <AppDock
      position="right"
      :items="rightItems"
      @itemClick="$emit('dockItemClick', $event)"
    />

    <HUD v-if="showHud" :flight="flight" :camera="camera" :real="realTelemetry" />
  </div>
</template>

<style scoped>
.view-composer {
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  width: 100%;
  height: 100%;
  padding: 24px;
  box-sizing: border-box;
  position: relative;
  pointer-events: none;
}

.view-composer > * {
  pointer-events: auto;
}

.view-composer > .control-area {
  pointer-events: none;
}

.control-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 0;
  pointer-events: none;
  z-index: 5;
}

.joystick-pair {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 40px;
  width: 100%;
  max-width: 1400px;
  padding: 0 clamp(24px, 8vw, 100px);
  box-sizing: border-box;
  pointer-events: none;
}

.joystick-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  pointer-events: auto;
}

.joystick-group--hidden {
  visibility: hidden;
  pointer-events: none;
}

.joystick-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
}

@media (max-width: 768px) {
  .joystick-pair {
    gap: 24px;
    padding: 0 16px;
  }
}
</style>

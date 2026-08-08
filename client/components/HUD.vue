<script setup>
import { useI18n } from 'vue-i18n';
import { useDrone } from '@shared-composables/useDrone.js';

const { drone, gimbal } = useDrone();
const { t } = useI18n();

defineProps({
  flight: {
    type: Object,
    default: () => ({ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }),
  },
  camera: {
    type: Object,
    default: () => ({ mode: '-', yaw: 0, pitch: 0, roll: 0 }),
  },
  // Real-drone telemetry (useDroneTelemetry). When set, the HUD shows the
  // physical drone's live state instead of the simulator rows; the Flight /
  // Camera / Gimbal rows are hidden (the Crazyflie has no gimbal and its
  // 'camera' is the livestream itself).
  real: {
    type: Object,
    default: null,
  },
});

// Null-safe number formatting ('-' until the first frame of a category).
const fmt = (v, digits = 2) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(digits);
</script>

<template>
  <!-- Real drone: live telemetry from the physical Crazyflie. -->
  <div v-if="real" class="telemetry">
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.link') }}</span>
      <span class="telemetry-value" :class="{ 'telemetry-value--lost': !real.linked }">
        <template v-if="real.linked">{{ t('hud.live') }} | {{ real.hz.toFixed(1) }} Hz</template>
        <template v-else>{{ t('hud.lost') }}</template>
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.position') }}</span>
      <span class="telemetry-value">
        x: {{ fmt(real.position.x) }} m | y: {{ fmt(real.position.y) }} m | z: {{ fmt(real.position.z) }} m
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.direction') }}</span>
      <span class="telemetry-value">
        {{ t('hud.yaw') }} {{ fmt(real.attitude.yaw, 1) }} | {{ t('hud.pitch') }} {{ fmt(real.attitude.pitch, 1) }} | {{ t('hud.roll') }} {{ fmt(real.attitude.roll, 1) }}
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.battery') }}</span>
      <span class="telemetry-value">{{ real.battery.voltage === null ? '-' : `${fmt(real.battery.voltage)} V` }}</span>
    </div>
  </div>

  <!-- Simulator (3D Aerial / 2D maps). -->
  <div v-else class="telemetry">
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.flight') }}</span>
      <span class="telemetry-value">
        {{ t('hud.mode') }} {{ flight.mode }}
        <template v-if="flight.mode === 'M'">| vx: {{ flight.vx.toFixed(2) }}, vy: {{ flight.vy.toFixed(2) }}</template>
        <template v-if="flight.mode === 'R'">| yaw: {{ flight.yaw.toFixed(2) }}</template>
        <template v-if="flight.mode === 'H'">| vz: {{ flight.vz.toFixed(2) }}</template>
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.camera') }}</span>
      <span class="telemetry-value">
        {{ t('hud.mode') }} {{ camera.mode }}
        <template v-if="camera.mode === 'Z'">| yaw: {{ camera.yaw.toFixed(2) }}</template>
        <template v-if="camera.mode === 'Y'">| pitch: {{ camera.pitch.toFixed(2) }}</template>
        <template v-if="camera.mode === 'X'">| roll: {{ camera.roll.toFixed(2) }}</template>
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.position') }}</span>
      <span class="telemetry-value">
        {{ t('hud.lat') }} {{ drone.lat.toFixed(4) }} | {{ t('hud.lon') }} {{ drone.lon.toFixed(4) }} | {{ t('hud.alt') }} {{ drone.alt.toFixed(4) }}
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.direction') }}</span>
      <span class="telemetry-value">
        {{ t('hud.yaw') }} {{ drone.heading.toFixed(1) }} | {{ t('hud.pitch') }} {{ (0).toFixed(1) }} | {{ t('hud.roll') }} {{ (0).toFixed(1) }}
      </span>
    </div>
    <div class="telemetry-row">
      <span class="telemetry-key">{{ t('hud.gimbal') }}</span>
      <span class="telemetry-value">
        {{ t('hud.yaw') }} {{ gimbal.yaw.toFixed(1) }} | {{ t('hud.pitch') }} {{ gimbal.pitch.toFixed(1) }} | {{ t('hud.roll') }} {{ gimbal.roll.toFixed(1) }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.telemetry {
  position: absolute;
  bottom: 48px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 14px 20px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.72);
  backdrop-filter: blur(6px);
  color: #4ade80;
  font-family: 'Courier New', Courier, monospace;
  font-size: 0.82rem;
  line-height: 1.4;
  pointer-events: none;
  z-index: 50;
}

.telemetry-row {
  display: flex;
  gap: 16px;
  white-space: nowrap;
}

.telemetry-key {
  width: 72px;
  flex-shrink: 0;
  font-weight: 700;
  color: #86efac;
}

.telemetry-value {
  flex: 1;
}

/* Real-drone link lost: warn in red instead of the nominal green. */
.telemetry-value--lost {
  color: #f87171;
}

@media (max-width: 768px) {
  .telemetry {
    font-size: 0.7rem;
    padding: 10px 14px;
    bottom: 40px;
  }

  .telemetry-key {
    width: 60px;
  }
}
</style>

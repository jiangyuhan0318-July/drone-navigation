<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue';
import {
  createStreetView,
  altitudeToStreetViewZoom,
  altitudeToStreetViewPitchOffset,
} from '@/3d_street/streetView.js';

const props = defineProps({
  lat: { type: Number, default: 0 },
  lon: { type: Number, default: 0 },
  heading: { type: Number, default: 0 }, // radians, Cesium convention
  pitch: { type: Number, default: 0 },   // radians, Cesium convention
  altitude: { type: Number, default: 0 }, // meters above surface
  visible: { type: Boolean, default: false },
  prewarm: { type: Boolean, default: false },
});

const containerRef = ref(null);
const streetView = ref(null);
const error = ref(null);
const isReady = ref(false);

const emit = defineEmits(['ready']);

async function initStreetView() {
  if (!containerRef.value || streetView.value) return;
  try {
    streetView.value = await createStreetView(containerRef.value, {
      lat: props.lat,
      lon: props.lon,
      heading: props.heading,
      pitch: props.pitch,
      zoom: altitudeToStreetViewZoom(props.altitude),
    });
    // Listen for panorama tiles loaded
    streetView.value.panorama.addListener('status_changed', () => {
      if (!isReady.value) {
        isReady.value = true;
        emit('ready');
      }
    });
  } catch (e) {
    error.value = e.message;
    console.error('[StreetViewPane]', e);
  }
}

watch(
  () => [props.visible, props.prewarm],
  async ([visible, prewarm]) => {
    if ((visible || prewarm) && !streetView.value) {
      await initStreetView();
    }
    if (streetView.value && visible) {
      streetView.value.setVisible(true);
    }
  },
  { immediate: true }
);

watch(
  () => [props.lat, props.lon],
  () => {
    if (streetView.value) {
      streetView.value.setPosition(props.lat, props.lon);
      // Re-assert heading after setPosition to prevent Google Street View
      // from snapping to the nearest road link direction (which can be ~180° off).
      const pitchOffsetRad = (altitudeToStreetViewPitchOffset(props.altitude) * Math.PI) / 180;
      streetView.value.setPov(props.heading, props.pitch + pitchOffsetRad);
    }
  }
);

watch(
  () => [props.heading, props.pitch, props.altitude],
  () => {
    if (streetView.value) {
      // Add altitude-based pitch offset: tilts view upward as drone rises
      // to simulate a rising viewpoint (more sky/horizon, less street)
      const pitchOffsetRad = (altitudeToStreetViewPitchOffset(props.altitude) * Math.PI) / 180;
      streetView.value.setPov(props.heading, props.pitch + pitchOffsetRad);
      streetView.value.setZoom(altitudeToStreetViewZoom(props.altitude));
    }
  }
);

onMounted(() => {
  if (props.visible) initStreetView();
});

onUnmounted(() => {
  if (streetView.value) {
    streetView.value.destroy();
    streetView.value = null;
  }
});
</script>

<template>
  <div
    class="street-view-pane"
    :class="{ 'street-view-pane--visible': visible, 'street-view-pane--hidden': !visible }"
  >
    <div ref="containerRef" class="street-view-container" />
    <div v-if="error" class="street-view-error">
      {{ $t('streetviewpane.unavailable') }} {{ error }}
    </div>
  </div>
</template>

<style scoped>
.street-view-pane {
  position: absolute;
  inset: 0;
  z-index: 0;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.4s ease-in-out;
  background: #111;
}

.street-view-pane--visible {
  opacity: 1;
  pointer-events: auto;
}

.street-view-container {
  width: 100%;
  height: 100%;
}

/* Hide Google Maps API attribution footer injected into the panorama container */
.street-view-container :deep(.gm-style-cc),
.street-view-container :deep(.gm-style a) {
  display: none !important;
}

.street-view-error {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  color: #f87171;
  font-family: Calibri, 'Segoe UI', sans-serif;
  font-size: 0.9rem;
  text-align: center;
  background: rgba(0, 0, 0, 0.7);
}
</style>

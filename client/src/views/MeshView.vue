<script setup>
import { ref, onMounted, onUnmounted, h } from 'vue';
import { useI18n } from 'vue-i18n';
import ViewComposer from '@shared/_ViewComposer.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import DockMenuButton from '@shared/DockMenuButton.vue';
import { applyNeutralSphericalHarmonics } from '@shared-composables/useTilesetSource.js';

const { t } = useI18n();
const { leftItems, registerLeft, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();

const loadingMessage = ref('Loading OSM Buildings…');

let osmBuildingsTileset = null;
let savedGoogleTileset = null;
let flightRafId = null;
let flightStartTimer = null;

// Initial camera target — matches the OSM Buildings reference view:
// https://osmbuildings.org/?lat=52.52110&lon=13.41078&zoom=16.0&tilt=30
const START_LON = 13.41078;
const START_LAT = 52.52110;
const START_HEIGHT = 1500; // ~zoom 16 (neighborhood scale)
const START_HEADING = 0; // north-up, like the reference
const START_PITCH = -60; // OSM tilt 30° from nadir → Cesium pitch −60°

function stopFlight() {
  if (flightRafId !== null) {
    cancelAnimationFrame(flightRafId);
    flightRafId = null;
  }
}

// Simulated fly-around: the camera orbits the start point while gently
// bobbing up and down, demonstrating smooth flight over the OSM buildings.
function startScenicFlight(viewer) {
  stopFlight();
  const startTime = performance.now();
  const orbitRadiusDeg = 0.0045; // ~300 m
  const step = (now) => {
    const t = (now - startTime) / 1000;
    const ang = t * 0.12; // slow orbit
    const lon = START_LON + orbitRadiusDeg * Math.cos(ang);
    const lat = START_LAT + orbitRadiusDeg * 0.65 * Math.sin(ang);
    const height = START_HEIGHT - 300 + 220 * Math.sin(t * 0.4);
    const heading = ((-ang * 180) / Math.PI + 90) % 360; // face travel direction
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, height),
      orientation: {
        heading: Cesium.Math.toRadians(heading),
        pitch: Cesium.Math.toRadians(-35),
        roll: 0,
      },
    });
    flightRafId = requestAnimationFrame(step);
  };
  flightRafId = requestAnimationFrame(step);
}

async function initMeshView() {
  const viewer = window.cesiumViewer;
  if (!viewer) {
    loadingMessage.value = 'Cesium viewer unavailable.';
    return;
  }

  // Save reference to Google tileset so we can restore it on unmount
  savedGoogleTileset = window.getGoogleTileset ? window.getGoogleTileset() : null;

  // Remove Google Photorealistic tileset
  if (savedGoogleTileset) {
    viewer.scene.primitives.remove(savedGoogleTileset);
    console.log('[MeshView] Removed Google tileset.');
  }

  // Re-enable globe for OSM Buildings context
  viewer.scene.globe.show = true;

  // Load Cesium World Terrain for elevation
  try {
    const terrain = await Cesium.createWorldTerrainAsync();
    viewer.terrainProvider = terrain;
    console.log('[MeshView] World Terrain loaded.');
  } catch (e) {
    console.warn('[MeshView] World Terrain failed:', e);
  }

  // Load OSM Buildings 3D Tiles (requires valid Cesium Ion token)
  try {
    osmBuildingsTileset = await Cesium.createOsmBuildingsAsync();
    // Explicit IBL spherical harmonics BEFORE the tileset enters the scene, so
    // its model pipelines capture them at shader-build time — otherwise the
    // pick pass logs "uniform3fv: no array" every frame. See useTilesetSource.js.
    applyNeutralSphericalHarmonics(osmBuildingsTileset);
    viewer.scene.primitives.add(osmBuildingsTileset);
    console.log('[MeshView] OSM Buildings loaded.');
  } catch (e) {
    console.warn('[MeshView] OSM Buildings failed:', e);
    // Clear the entire scene — show white page with error
    viewer.scene.globe.show = false;
    viewer.scene.primitives.removeAll();
    viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    loadingMessage.value = 'Failed to load OSM Buildings. Check Cesium Ion token.';
    return;
  }

  // Position the camera over Berlin (Alexanderplatz / Fernsehturm area) using
  // the same parameters as the OSM Buildings reference URL.
  // Use a delay to ensure AerialView's animation loop has fully stopped
  // (it cancels on unmount, but there may be a race during view transition).
  setTimeout(() => {
    // Cancel any in-progress camera flight first
    viewer.camera.cancelFlight();

    // Set camera instantly to the Berlin start view
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(START_LON, START_LAT, START_HEIGHT),
      orientation: {
        heading: Cesium.Math.toRadians(START_HEADING),
        pitch: Cesium.Math.toRadians(START_PITCH),
        roll: 0,
      },
    });
    console.log('[MeshView] Camera set to Berlin (lat 52.52110, lon 13.41078, zoom 16, tilt 30).');

    // Hold the exact start view briefly (for comparison), then begin the
    // simulated fly-around animation.
    flightStartTimer = setTimeout(() => startScenicFlight(viewer), 4000);
  }, 500);

  loadingMessage.value = '';
}

onMounted(() => {
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  registerLeft({
    id: 'router',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'aerialview.pages',
      pages,
    }),
  });

  initMeshView();
});

onUnmounted(() => {
  // Stop the fly-around animation so it cannot keep mutating the camera.
  if (flightStartTimer !== null) {
    clearTimeout(flightStartTimer);
    flightStartTimer = null;
  }
  stopFlight();

  // Restore Google Photorealistic tileset
  const viewer = window.cesiumViewer;
  if (viewer) {
    // Remove OSM Buildings
    if (osmBuildingsTileset) {
      viewer.scene.primitives.remove(osmBuildingsTileset);
      osmBuildingsTileset = null;
    }
    // Restore Google tileset
    if (savedGoogleTileset) {
      viewer.scene.primitives.add(savedGoogleTileset);
    }
    // Re-hide globe (matching AerialView default)
    viewer.scene.globe.show = false;
  }

  clear();
  unregisterPage('aerial');
  unregisterPage('realdrone');
  unregisterPage('map');
  unregisterPage('myspace');
  unregisterPage('chat');
  unregisterPage('extensions');
});
</script>

<template>
  <ViewComposer
    :left-items="leftItems"
    :right-items="[]"
    :show-flight="false"
    :show-camera="false"
    :flight="{ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }"
    :camera="{ mode: '-', yaw: 0, pitch: 0, roll: 0 }"
  >
    <template #background>
      <div class="mesh-overlay" v-if="loadingMessage">
        <p class="mesh-overlay__message">{{ loadingMessage }}</p>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.mesh-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.mesh-overlay__message {
  font-size: 1.25rem;
  font-weight: 600;
  color: #c0392b;
  letter-spacing: 0.05em;
  background: rgba(255, 255, 255, 0.9);
  padding: 16px 24px;
  border-radius: 8px;
}
</style>

<script setup>
import { onMounted, onUnmounted, h, ref, computed, watch } from 'vue';
import ViewComposer from '@shared/_ViewComposer.vue';
import { MapView } from '@/2d_map/index.js';
import { useDrone } from '@shared-composables/useDrone.js';
import { useFlightCommands } from '@shared-composables/useFlightCommands.js';
import { useFlightPhysics } from '@shared-composables/useFlightPhysics.js';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useWaypointPicker } from '@shared-composables/useWaypointPicker.js';
import { useConnectionStatus, checkGoogleConnection } from '@shared-composables/useConnectionStatus.js';
import DockMenuButton from '@shared/DockMenuButton.vue';
import WaypointButton from '@shared/WaypointButton.vue';
import ConnectionError from '@shared/ConnectionError.vue';

const { drone } = useDrone();
const {
  flight,
  showFlight,
  toggleFlight,
  onFlightMove,
  onFlightStop,
  onFlightModeChange,
  startKeyboard,
  stopKeyboard,
} = useFlightCommands();
const { step: stepFlightPhysics } = useFlightPhysics();
const { leftItems, rightItems, registerLeft, registerRight, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { isPicking, isPanelOpen, setPicked, openPanel, commitOrigin, setNearbyPois, setRouteResult, clearRouteResult, setRouteError, clearRouteError, pickedLocation, activeWaypointId, originDraft, waypoints } = useWaypointPicker();

const { googleReady, googleError } = useConnectionStatus();
const showConnectionError = computed(() => !googleReady.value);
const connectionMessage = computed(() => googleError.value || 'Cannot connect to Google.');
let connectionCheckInterval = null;

function onMapCenterChange({ lat, lng }) {
  drone.lat = lat;
  drone.lon = lng;
}

function onMapZoomChange(alt) {
  drone.alt = Math.max(0, Math.min(100000, alt));
}

const mapViewRef = ref(null);

// Active subpage of the 2D Map page: 'address' (default) or 'satellite'.
const activeSubpage = ref('address');
const mapTypeId = computed(() => (activeSubpage.value === 'address' ? 'roadmap' : 'satellite'));

function onMapClick({ lat, lng }) {
  if (isPicking.value || isPanelOpen.value) {
    // If the origin input is active and contains text, commit it as a waypoint
    // before filling the newly clicked coordinate.
    if (activeWaypointId.value === null && originDraft.value.trim()) {
      commitOrigin();
    }
    setPicked(lat, lng, 0);
    if (mapViewRef.value) {
      mapViewRef.value.searchNearbyPoisAt(lat, lng);
    }
    openPanel();
  }
}

function onPoisFound(pois) {
  setNearbyPois(pois);
}

function onPoisError(message) {
  console.error('[Map2DView] poisError:', message);
  setNearbyPois([]);
  setRouteError(message);
}

function onRouteFound(result) {
  setRouteResult(result);
}

function onRouteError(status) {
  setRouteResult(null);
  let message;
  if (status === 'REQUEST_DENIED') {
    message = 'Routes API access was denied. Please enable the Routes API for your Google Maps API key in the Google Cloud Console.';
  } else if (status === 'OVER_QUERY_LIMIT') {
    message = 'Routes API quota exceeded. Please check your Google Cloud billing and quota limits.';
  } else if (status === 'ZERO_RESULTS') {
    message = 'No route found between the given waypoints.';
  } else {
    message = status ? `Route request failed: ${status}` : 'Could not find a route. Please check the waypoints.';
  }
  setRouteError(message);
}

function parseCoordinateText(text) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/[\s,]+/).filter(Boolean);
  const lat = Number(parts[0]);
  const lon = Number(parts[1]);
  if (!isNaN(lat) && !isNaN(lon)) {
    return { lat, lon };
  }
  return null;
}

function resolveSearchLocation() {
  if (pickedLocation.value) {
    return pickedLocation.value;
  }
  if (activeWaypointId.value === null) {
    const originLoc = parseCoordinateText(originDraft.value);
    if (originLoc) return originLoc;
    // Fallback to the first committed waypoint if the origin is empty.
    const firstWp = waypoints.value[0];
    if (firstWp) {
      const firstLoc = parseCoordinateText(firstWp.name);
      if (firstLoc) return firstLoc;
    }
  }
  const id = activeWaypointId.value;
  const list = id !== null ? waypoints.value : [];
  const wp = list.find((w) => w.id === id);
  if (wp) {
    const wpLoc = parseCoordinateText(wp.name);
    if (wpLoc) return wpLoc;
  }
  // Final fallback: search around the drone's current position.
  if (!isNaN(drone.lat) && !isNaN(drone.lon)) {
    return { lat: drone.lat, lon: drone.lon };
  }
  return null;
}

function onSearchWaypoints() {
  clearRouteResult();
  clearRouteError();
  const loc = resolveSearchLocation();
  if (loc && mapViewRef.value) {
    mapViewRef.value.searchNearbyPoisAt(loc.lat, loc.lon);
  } else {
    console.warn('[Search waypoints] no usable location');
    setRouteError('Please pick a location on the map or enter coordinates first.');
  }
}

function onSearchRoutes() {
  setNearbyPois([]);
  if (mapViewRef.value) {
    mapViewRef.value.searchRoutes(waypoints.value);
  }
}

let rafId = null;

const MIN_ALT = 10; // meters – matches Google Maps max zoom (z21 ≈ 10 m)
const MAX_ALT = 100000; // operational ceiling

function loop() {
  stepFlightPhysics(1 / 60, { allowAltitude: true, applyMovement: showFlight.value, exponentialAltitude: true });
  // Clamp altitude to the allowed [10 m, 100 000 m] range.
  drone.alt = Math.max(MIN_ALT, Math.min(MAX_ALT, drone.alt));
  rafId = requestAnimationFrame(loop);
}

onMounted(() => {
  startKeyboard();

  // Initial connection check and periodic re-check.
  checkGoogleConnection();
  connectionCheckInterval = setInterval(() => {
    checkGoogleConnection();
  }, 10000);

  // Register pages for the router menu
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
      onBeforeOpen: () => { showFlight.value = false; },
    }),
  });
  registerLeft({
    id: 'subpage_address',
    icon: 'MENU_MAP',
    titleKey: 'aerialview.subpage_address',
    active: activeSubpage.value === 'address',
    onClick: () => {
      activeSubpage.value = 'address';
    },
  });
  registerLeft({
    id: 'subpage_satellite',
    icon: 'MENU_SATELLITE',
    titleKey: 'aerialview.subpage_satellite',
    active: activeSubpage.value === 'satellite',
    onClick: () => {
      activeSubpage.value = 'satellite';
    },
  });
  registerRight({
    id: 'steer',
    icon: 'MENU_CONTROL_STICK',
    titleKey: 'aerialview.steer',
    active: false,
    onClick: toggleFlight,
  });
  registerRight({
    id: 'waypoint',
    render: () => h(WaypointButton, {
      onBeforeOpen: () => { showFlight.value = false; },
      onSearchWaypoints,
      onSearchRoutes,
    }),
  });

  // Keep the subpage selector buttons in sync with the active subpage.
  watch(activeSubpage, (val) => {
    const addressBtn = leftItems.find((i) => i.id === 'subpage_address');
    if (addressBtn) addressBtn.active = val === 'address';
    const satelliteBtn = leftItems.find((i) => i.id === 'subpage_satellite');
    if (satelliteBtn) satelliteBtn.active = val === 'satellite';
  });

  rafId = requestAnimationFrame(loop);
});

onUnmounted(() => {
  stopKeyboard();
  if (rafId) cancelAnimationFrame(rafId);
  if (connectionCheckInterval) clearInterval(connectionCheckInterval);
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
    :right-items="rightItems"
    :show-flight="showFlight"
    :show-camera="false"
    :show-hud="false"
    :flight="flight"
    :camera="{ mode: '-', yaw: 0, pitch: 0, roll: 0 }"
    @flightMove="onFlightMove"
    @flightStop="onFlightStop"
    @flightModeChange="onFlightModeChange"
  >
    <template #top-overlay>
      <ConnectionError :visible="showConnectionError" :message="connectionMessage" />
    </template>
    <template #background>
      <MapView
        ref="mapViewRef"
        class="view-composer__background"
        :map-type-id="mapTypeId"
        :lat="drone.lat"
        :lon="drone.lon"
        :alt="drone.alt"
        :heading="drone.heading"
        :is-picking="isPicking"
        :is-panel-open="isPanelOpen"
        @centerChange="onMapCenterChange"
        @zoomChange="onMapZoomChange"
        @mapClick="onMapClick"
        @poisFound="onPoisFound"
        @poisError="onPoisError"
        @routeFound="onRouteFound"
        @routeError="onRouteError"
      />
    </template>
  </ViewComposer>
</template>

<style scoped>
:deep(.view-composer__background) {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: auto;
}
</style>

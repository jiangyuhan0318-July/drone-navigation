<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { loadGoogleMaps } from './googleMaps.js';
import droneIconUrl from '../../icons/drone.svg';

const { t } = useI18n();

const props = defineProps({
  lat: { type: Number, required: true },
  lon: { type: Number, required: true },
  alt: { type: Number, default: 0 },
  heading: { type: Number, default: 0 },
  mapTypeId: { type: String, default: 'roadmap' },
  isPicking: { type: Boolean, default: false },
  isPanelOpen: { type: Boolean, default: false },
});

const emit = defineEmits(['centerChange', 'zoomChange', 'mapClick', 'poisFound', 'poisError', 'routeFound', 'routeError']);

const containerRef = ref(null);
const map = ref(null);
const error = ref('');

const MIN_DRONE_SIZE = 24;
const MAX_DRONE_SIZE = 80;
const ALT_SIZE_RANGE = 500;

const droneSize = computed(() => {
  const ratio = Math.min(Math.max(props.alt / ALT_SIZE_RANGE, 0), 1);
  return Math.round(MAX_DRONE_SIZE - ratio * (MAX_DRONE_SIZE - MIN_DRONE_SIZE));
});

// Altitude (meters) ↔ Google Maps zoom level.
// Uses Google's exponential model: altitude ≈ 20 971 520 / 2^zoom.
//
//    z7 ≈ 163 840 m   z11 ≈ 10 240 m   z15 ≈   640 m   z19 ≈   40 m
//    z8 ≈  81 920 m   z12 ≈  5 120 m   z16 ≈   320 m   z20 ≈   20 m
//    z9 ≈  40 960 m   z13 ≈  2 560 m   z17 ≈   160 m   z21 ≈   10 m
//   z10 ≈  20 480 m   z14 ≈  1 280 m   z18 ≈    80 m
const MIN_ZOOM = 7;      // ~163 840 m
const MAX_ZOOM = 21;     // ~10 m
const MAX_ALT  = 100000; // operational ceiling (meters)
const MIN_ALT  = 10;     // matches Google Maps max zoom (z21 ≈ 10 m)
const ALT_ZOOM_K = 20971520; // exact: 10 m * 2^21

// Guard flags to distinguish programmatic changes from user-initiated gestures.
let lastProgrammaticCenter = null;
let lastProgrammaticZoom = null;
let lastZoomChangeTime = 0;  // timestamp (ms) of last user-initiated zoom
let listeners = [];
let wheelHandler = null;     // stored so we can removeEventListener on unmount
let clickListener = null;    // Google Maps click listener for picking mode
let mapsApi = null;          // loaded Google Maps API namespace

function altToZoom(alt) {
  const clamped = Math.max(MIN_ALT, Math.min(MAX_ALT, alt));
  const z = Math.log2(ALT_ZOOM_K / clamped);
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(z)));
}

function zoomToAlt(zoom) {
  const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
  return Math.max(MIN_ALT, Math.min(MAX_ALT, ALT_ZOOM_K / Math.pow(2, clamped)));
}

function isSameCenter(a, b) {
  return Math.abs(a.lat - b.lat) < 1e-7 && Math.abs(a.lng - b.lng) < 1e-7;
}

function updateMapCenter(lat, lng) {
  if (!map.value) return;
  const current = map.value.getCenter();
  const target = { lat, lng };
  if (isSameCenter({ lat: current.lat(), lng: current.lng() }, target)) return;
  lastProgrammaticCenter = target;
  map.value.setCenter(target);
}

// ── Anchor-preserving zoom (reverse-engineered from Google Maps internals) ──
//
// Google Maps' native wheel-zoom pipeline:
//   1. Read cursor pixel position from the WheelEvent
//   2. Un-project that pixel to a geographic point (Web Mercator inverse)
//   3. Change the zoom level
//   4. Compute where that geo point lands at the new zoom (forward projection)
//   5. Shift the map center so the geo point stays under the cursor
//
// We replicate this exact pipeline using Google Maps' public Projection API
// (fromLatLngToPoint / fromPointToLatLng).  The same function is used for:
//   • Mouse wheel  – anchor = cursor pixel position  (cursor-anchored)
//   • H-mode       – anchor = map center              (center-anchored)
//
// Neither zoom_changed nor center_changed side-effects are emitted because all
// resulting state changes are guarded by lastProgrammaticZoom / lastProgrammaticCenter.
function anchoredZoom(zoomDelta, anchorX, anchorY, silent = false) {
  if (!map.value) return;
  const projection = map.value.getProjection();
  if (!projection) return;

  const curZoom = map.value.getZoom();
  const newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, curZoom + zoomDelta));
  if (newZoom === curZoom) return;

  const scale0 = Math.pow(2, curZoom) * 256;
  const scale1 = Math.pow(2, newZoom) * 256;
  const center = map.value.getCenter();
  const centerWorld = projection.fromLatLngToPoint(center);
  const rect = map.value.getDiv().getBoundingClientRect();
  const halfW = rect.width / 2;
  const halfH = rect.height / 2;

  const ax0 = centerWorld.x + (anchorX - halfW) / scale0;
  const ay0 = centerWorld.y + (anchorY - halfH) / scale0;
  const ax1 = centerWorld.x + (anchorX - halfW) / scale1;
  const ay1 = centerWorld.y + (anchorY - halfH) / scale1;

  const newCx = centerWorld.x + (ax0 - ax1);
  const newCy = centerWorld.y + (ay0 - ay1);
  const newCenter = projection.fromPointToLatLng(new google.maps.Point(newCx, newCy));

  // Always guard the center_changed side effect of the zoom.
  lastProgrammaticCenter = { lat: newCenter.lat(), lng: newCenter.lng() };
  // For silent (programmatic/H-mode) zooms, also guard zoom_changed so the
  // altitude prop update doesn't trigger a feedback loop.
  if (silent) {
    lastProgrammaticZoom = newZoom;
  } else {
    // For user wheel zooms, record timestamp so the center_changed side effect
    // is suppressed regardless of event ordering.
    lastZoomChangeTime = Date.now();
  }

  map.value.setZoom(newZoom);
  map.value.setCenter(newCenter);
}

// H-mode: programmatic zoom always anchors at the map center (drone icon).
function updateMapZoom(alt) {
  if (!map.value) return;
  const rect = map.value.getDiv()?.getBoundingClientRect();
  if (!rect) return;
  anchoredZoom(altToZoom(alt) - map.value.getZoom(), rect.width / 2, rect.height / 2, true);
}

function handleCenterChanged() {
  if (!map.value) return;
  const center = map.value.getCenter();
  const target = { lat: center.lat(), lng: center.lng() };
  if (Date.now() - lastZoomChangeTime < 150) {
    return;
  }
  if (lastProgrammaticCenter && isSameCenter(target, lastProgrammaticCenter)) {
    lastProgrammaticCenter = null;
    return;
  }
  lastProgrammaticCenter = null;
  emit('centerChange', target);
}

function handleZoomChanged() {
  if (!map.value) return;
  const zoom = map.value.getZoom();
  if (lastProgrammaticZoom !== null && Math.abs(zoom - lastProgrammaticZoom) < 0.5) {
    lastProgrammaticZoom = null;
    return;
  }
  lastProgrammaticZoom = null;
  lastZoomChangeTime = Date.now();
  emit('zoomChange', zoomToAlt(zoom));
}

function onWheel(e) {
  if (!map.value) return;
  e.stopPropagation();
  const rect = map.value.getDiv().getBoundingClientRect();
  anchoredZoom(e.deltaY < 0 ? 1 : -1, e.clientX - rect.left, e.clientY - rect.top, false);
}

onMounted(async () => {
  try {
    mapsApi = await loadGoogleMaps();

    map.value = new mapsApi.Map(containerRef.value, {
      center: { lat: props.lat, lng: props.lon },
      zoom: altToZoom(props.alt),
      mapTypeId: props.mapTypeId,
      disableDefaultUI: true,
      clickableIcons: false,  // POI icons should not intercept map picks
      scrollwheel: false,     // we handle wheel events ourselves
      gestureHandling: 'auto',
      draggable: true,
      keyboardShortcuts: false,
      zoomControl: false,
      mapTypeControl: false,
      streetViewControl: false,
      fullscreenControl: false,
      scaleControl: false,
      rotateControl: false,
    });

    listeners.push(mapsApi.event.addListener(map.value, 'center_changed', handleCenterChanged));
    listeners.push(mapsApi.event.addListener(map.value, 'zoom_changed', handleZoomChanged));
    attachMapClickListener();

    // Capture-phase wheel listener: fires before any Google Maps listener.
    // passive: false avoids Chrome's passive-listener console warning.
    wheelHandler = onWheel;
    containerRef.value.addEventListener('wheel', wheelHandler, { capture: true, passive: false });
  } catch (e) {
    console.error('[2D Map]', e);
    error.value = e?.message || String(e);
  }
});

onUnmounted(() => {
  listeners.forEach((listener) => listener?.remove());
  listeners = [];
  if (clickListener) {
    clickListener.remove();
    clickListener = null;
  }
  if (wheelHandler && containerRef.value) {
    containerRef.value.removeEventListener('wheel', wheelHandler, { capture: true });
  }
});

watch(() => [props.lat, props.lon], ([lat, lon]) => {
  updateMapCenter(lat, lon);
});

watch(() => props.alt, (alt) => {
  updateMapZoom(alt);
});

// React to map-type changes (e.g. switching between the 2D Address and
// 2D Satellite subpages) after the map has been created.
watch(() => props.mapTypeId, (mapTypeId) => {
  if (map.value) map.value.setMapTypeId(mapTypeId);
});

function displayNameOf(place) {
  if (!place || !place.displayName) return '';
  return typeof place.displayName === 'string' ? place.displayName : place.displayName.text || '';
}

async function searchNearbyPois(latLng) {
  if (!mapsApi?.places?.Place?.searchNearby) {
    emit('poisError', 'Places API is not available. Please enable the Places API for your Google Maps API key.');
    return;
  }
  try {
    const circle = new mapsApi.Circle({
      center: latLng,
      radius: 500, // meters
    });
    const request = {
      locationRestriction: circle,
      fields: ['id', 'displayName', 'location'],
    };
    const response = await mapsApi.places.Place.searchNearby(request);
    const places = (response?.places || []).slice(0, 10).map((place) => ({
      place_id: place.id,
      name: displayNameOf(place),
      geometry: {
        location: place.location,
      },
    }));
    emit('poisFound', places);
  } catch (err) {
    console.error('[MapView] Place.searchNearby error:', err);
    emit('poisError', `Places API request failed: ${err?.message || err}`);
  }
}

function searchNearbyPoisAt(lat, lng) {
  if (!mapsApi) return;
  searchNearbyPois(new mapsApi.LatLng(lat, lng));
}

function parseWaypointInput(name) {
  if (!name) return null;
  const trimmed = name.trim();
  // Try to parse our coordinate format: "lat, lon, alt"
  const coordMatch = trimmed.match(/^(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)$/);
  if (coordMatch) {
    return new mapsApi.LatLng(parseFloat(coordMatch[1]), parseFloat(coordMatch[2]));
  }
  // Otherwise treat as a place/address string
  return trimmed;
}

// ── Routes API (google.maps.routes.Route.computeRoutes) ──────────────────
// The legacy google.maps.DirectionsService is deprecated (Feb 2026). We use
// the Routes API instead and adapt its response back into the
// DirectionsResult shape that WaypointPanel.vue consumes, so the panel needs
// no changes.

// Routes API durations are protobuf strings such as "300s" (or "3.5s").
function durationStringToSeconds(d) {
  if (typeof d === 'number') return d;
  if (typeof d === 'string') {
    const n = parseFloat(d);
    return isNaN(n) ? 0 : n;
  }
  return 0;
}

function formatDistanceText(meters) {
  if (meters == null) return '';
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(1)} km`;
}

function formatDurationText(seconds) {
  if (seconds == null) return '';
  const mins = Math.round(seconds / 60);
  if (mins < 1) return `${Math.round(seconds)} secs`;
  if (mins < 60) return `${mins} mins`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  return rem ? `${hours} hours ${rem} mins` : `${hours} hours`;
}

// Build a Routes API Waypoint from a waypoint input ("lat, lon, alt" coords
// or a free-form place/address string).
function buildRouteWaypoint(name) {
  const parsed = parseWaypointInput(name);
  if (parsed == null) return null;
  if (typeof parsed === 'string') return { address: parsed };
  // google.maps.LatLng
  return { location: { latLng: { latitude: parsed.lat(), longitude: parsed.lng() } } };
}

function convertRouteStep(step) {
  const distanceMeters = step.distanceMeters ?? step.localizedValues?.distance?.value ?? 0;
  return {
    distance: {
      value: distanceMeters,
      text: step.localizedValues?.distance?.text || formatDistanceText(distanceMeters),
    },
    instructions:
      step.navigationInstruction?.instructions ||
      step.navigationInstruction?.maneuver ||
      '',
  };
}

function convertRouteLeg(leg, startIndex, waypoints) {
  const distanceMeters = leg.distanceMeters ?? leg.localizedValues?.distance?.value ?? 0;
  const durationSeconds =
    leg.localizedValues?.staticDuration?.value ??
    durationStringToSeconds(leg.staticDuration ?? leg.duration);
  // Fall back to the user-entered waypoint names when the API does not return
  // human-readable addresses for the leg endpoints.
  const startName = waypoints[startIndex]?.name || '';
  const endName = waypoints[startIndex + 1]?.name || '';
  return {
    distance: {
      value: distanceMeters,
      text: leg.localizedValues?.distance?.text || formatDistanceText(distanceMeters),
    },
    duration: {
      value: durationSeconds,
      text: leg.localizedValues?.staticDuration?.text || formatDurationText(durationSeconds),
    },
    start_address: leg.startLocation?.address || startName,
    end_address: leg.endLocation?.address || endName,
    steps: (leg.steps || []).map(convertRouteStep),
  };
}

function convertRoute(route, waypoints) {
  return {
    legs: (route.legs || []).map((leg, i) => convertRouteLeg(leg, i, waypoints)),
  };
}

async function searchRoutes(waypoints) {
  if (!mapsApi || waypoints.length < 2) return;
  if (typeof mapsApi.importLibrary !== 'function') {
    emit('routeError', 'Routes API is not available for this Google Maps API key.');
    return;
  }
  try {
    const { Route } = await mapsApi.importLibrary('routes');
    const origin = buildRouteWaypoint(waypoints[0].name);
    const destination = buildRouteWaypoint(waypoints[waypoints.length - 1].name);
    if (!origin || !destination) {
      emit('routeError', 'ZERO_RESULTS');
      return;
    }
    const intermediates = waypoints
      .slice(1, -1)
      .map((wp) => buildRouteWaypoint(wp.name))
      .filter(Boolean);

    const response = await Route.computeRoutes({
      origin,
      destination,
      intermediates,
      travelMode: 'DRIVE',
      computeAlternativeRoutes: true,
      languageCode: 'en-US',
      units: 'METRIC',
    });

    const routes = (response?.routes || []).map((r) => convertRoute(r, waypoints));
    if (!routes.length) {
      emit('routeError', 'ZERO_RESULTS');
      return;
    }

    // Select the fastest route by total duration.
    const fastest = routes.reduce((best, route) => {
      const duration = route.legs.reduce((sum, leg) => sum + (leg.duration?.value || 0), 0);
      const bestDuration = best.legs.reduce((sum, leg) => sum + (leg.duration?.value || 0), 0);
      return duration < bestDuration ? route : best;
    });
    emit('routeFound', { routes: [fastest] });
  } catch (err) {
    console.error('[MapView] computeRoutes error:', err);
    const msg = err?.message || String(err);
    const code = err?.code || '';
    if (code === 'PERMISSION_DENIED' || /denied|not authorized|forbidden/i.test(msg)) {
      emit('routeError', 'REQUEST_DENIED');
    } else if (code === 'RESOURCE_EXHAUSTED' || /quota/i.test(msg)) {
      emit('routeError', 'OVER_QUERY_LIMIT');
    } else {
      emit('routeError', msg);
    }
  }
}

function attachMapClickListener() {
  if (!map.value) return;
  if (clickListener) {
    clickListener.remove();
    clickListener = null;
  }
  if (props.isPicking || props.isPanelOpen) {
    clickListener = map.value.addListener('click', (e) => {
      const lat = e.latLng.lat();
      const lng = e.latLng.lng();
      emit('mapClick', { lat, lng });
    });
  }
}

defineExpose({
  searchNearbyPoisAt,
  searchRoutes,
});

watch(() => [props.isPicking, props.isPanelOpen], () => {
  attachMapClickListener();
});


</script>

<template>
  <div class="map-view">
    <div ref="containerRef" class="map-container"></div>
    <img
      class="drone-marker"
      :src="droneIconUrl"
      alt="Drone"
      draggable="false"
      :width="droneSize"
      :height="droneSize"
      :style="{
        transform: `translate(-50%, -50%) rotate(${props.heading}deg)`,
      }"
    />
    <div v-if="error" class="map-error">
      <strong>{{ t('mapview.load_failed') }}</strong>
      <p>{{ error }}</p>
      <p class="map-error-hint">
        {{ t('mapview.api_hint') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.map-view {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  background: #0b0b0b;
  overflow: hidden;
}

.map-container {
  width: 100%;
  height: 100%;
}

.drone-marker {
  position: absolute;
  top: 50%;
  left: 50%;
  z-index: 2;
  pointer-events: none;
  user-select: none;
  -webkit-user-drag: none;
  filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.35));
}

/* Hide Google Maps UI widgets and bottom-right attribution links. */
.map-container :deep(.gmnoprint),
.map-container :deep(.gm-style-cc),
.map-container :deep(.gm-style a[href^="https://maps.google.com/maps?"]),
.map-container :deep(.gm-style a[href^="https://www.google.com/intl/"]),
.map-container :deep(.gm-style-cc a),
.map-container :deep(.gm-style .gm-style-cc span),
.map-container :deep(.gm-style > div > a),
.map-container :deep(.gm-style > div > div > a) {
  display: none !important;
}

.map-error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.85);
  color: #f87171;
  text-align: center;
}

.map-error-hint {
  color: #aaaaaa;
  font-size: 0.85rem;
  max-width: 480px;
}
</style>

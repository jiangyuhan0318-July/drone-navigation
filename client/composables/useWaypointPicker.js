import { reactive, computed, ref, watch } from 'vue';

const WAYPOINTS_STORAGE_KEY = 'drone-navigation-waypoints';

function loadStoredWaypoints() {
  try {
    const raw = localStorage.getItem(WAYPOINTS_STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    console.warn('Failed to load waypoints from localStorage', e);
  }
  return [];
}

function saveStoredWaypoints(waypoints) {
  try {
    localStorage.setItem(WAYPOINTS_STORAGE_KEY, JSON.stringify(waypoints));
  } catch (e) {
    console.warn('Failed to save waypoints to localStorage', e);
  }
}

function computeNextId(waypoints) {
  return waypoints.length ? Math.max(...waypoints.map((w) => w.id)) + 1 : 1;
}

const state = reactive({
  isPicking: false,
  pickedLocation: null, // { lat, lon, alt }
  nearbyPois: [], // google.maps.places.PlaceResult[]
  selectedPoi: null, // google.maps.places.PlaceResult | null
  routeResult: null, // google.maps.DirectionsResult | null
  routeError: '', // last route search error message
  isPanelOpen: false,
});

const storedWaypoints = loadStoredWaypoints();
const waypoints = ref(storedWaypoints);
const nextWaypointId = ref(computeNextId(storedWaypoints));
const originDraft = ref('');
const activeWaypointId = ref(null); // null = origin input, number = existing waypoint id
const inputFocused = ref(false);

watch(waypoints, (val) => saveStoredWaypoints(val), { deep: true });

export function useWaypointPicker() {
  const isPicking = computed(() => state.isPicking);
  const pickedLocation = computed(() => state.pickedLocation);
  const nearbyPois = computed(() => state.nearbyPois);
  const selectedPoi = computed(() => state.selectedPoi);
  const routeResult = computed(() => state.routeResult);
  const routeError = computed(() => state.routeError);
  const isPanelOpen = computed(() => state.isPanelOpen);

  function startPicking() {
    state.isPicking = true;
  }

  function stopPicking() {
    state.isPicking = false;
  }

  function setPicked(lat, lon, alt = 0) {
    state.pickedLocation = { lat, lon, alt };
    state.isPicking = false;
    const value = `${lat.toFixed(6)}, ${lon.toFixed(6)}, ${alt}`;
    if (activeWaypointId.value === null) {
      originDraft.value = value;
    } else {
      const wp = waypoints.value.find((w) => w.id === activeWaypointId.value);
      if (wp) wp.name = value;
    }
  }

  function setActiveWaypointId(id) {
    activeWaypointId.value = id ?? null;
  }

  function setInputFocused(value) {
    inputFocused.value = !!value;
  }

  function commitOrigin() {
    const value = originDraft.value.trim();
    if (!value) return;
    waypoints.value.push({
      id: nextWaypointId.value++,
      name: value,
    });
    clearPicked();
    originDraft.value = '';
  }

  function clearPicked() {
    state.pickedLocation = null;
  }

  function setNearbyPois(pois) {
    state.nearbyPois = pois ?? [];
  }

  function selectPoi(poi) {
    state.selectedPoi = poi ?? null;
  }

  function setRouteResult(result) {
    state.routeResult = result ?? null;
    if (result) state.routeError = '';
  }

  function clearRouteResult() {
    state.routeResult = null;
  }

  function setRouteError(message) {
    state.routeError = message ?? '';
  }

  function clearRouteError() {
    state.routeError = '';
  }

  function openPanel() {
    state.isPanelOpen = true;
  }

  function closePanel() {
    state.isPanelOpen = false;
  }

  return {
    isPicking,
    pickedLocation,
    nearbyPois,
    selectedPoi,
    routeResult,
    routeError,
    isPanelOpen,
    waypoints,
    nextWaypointId,
    originDraft,
    activeWaypointId,
    inputFocused,
    startPicking,
    stopPicking,
    setPicked,
    clearPicked,
    setNearbyPois,
    selectPoi,
    setRouteResult,
    clearRouteResult,
    setRouteError,
    clearRouteError,
    setActiveWaypointId,
    setInputFocused,
    commitOrigin,
    openPanel,
    closePanel,
  };
}

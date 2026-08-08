<script setup>
import { ref, computed, onMounted, onUnmounted, watch, h } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter } from 'vue-router';
import ViewComposer from '@shared/_ViewComposer.vue';
import CollisionWarning from '@shared/CollisionWarning.vue';
import StreetViewPane from '@shared/StreetViewPane.vue';
import { useDrone } from '@shared-composables/useDrone.js';
import { useAltitudeGate, PHASES, DESCEND_THRESHOLD, ASCEND_THRESHOLD } from '@shared-composables/useAltitudeGate.js';
import { useFlightCommands } from '@shared-composables/useFlightCommands.js';
import { useCameraCommands } from '@shared-composables/useCameraCommands.js';
import { useFlightPhysics } from '@shared-composables/useFlightPhysics.js';
import { useCameraPhysics } from '@shared-composables/useCameraPhysics.js';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useTilesetSource } from '@shared-composables/useTilesetSource.js';
import { useScreenCapture } from '@shared-composables/useScreenCapture.js';
import { useAppSettings } from '@shared-composables/useAppSettings.js';
import { useAuth } from '@shared-composables/useAuth.js';
import { useConnectionStatus, checkGoogleConnection, checkCesiumConnection } from '@shared-composables/useConnectionStatus.js';
import DockMenuButton from '@shared/DockMenuButton.vue';
import ConnectionError from '@shared/ConnectionError.vue';

const { t } = useI18n();

const router = useRouter();

const { drone, gimbal } = useDrone();

// 3D data source of the shared Cesium viewer. The 3D Aerial / 3D Mesh
// subpages differ ONLY in this source (Google tiles vs OSM Buildings); every
// control (disks, sidebars, physics) is identical between them.
const { activeSource, isSwitching, setSource, getActiveTileset } = useTilesetSource();
const altitudeGate = useAltitudeGate(drone);

const {
  flight,
  flightCmd,
  activeFlightMode,
  showFlight,
  toggleFlight,
  onFlightMove,
  onFlightStop,
  onFlightModeChange,
  startKeyboard: startFlightKeyboard,
  stopKeyboard: stopFlightKeyboard,
} = useFlightCommands();

const {
  camera,
  cameraCmd,
  activeCameraMode,
  showCamera,
  toggleCamera,
  onCameraMove,
  onCameraStop,
  onCameraModeChange,
  startKeyboard: startCameraKeyboard,
  stopKeyboard: stopCameraKeyboard,
} = useCameraCommands();

const { computeDesiredEnuMove, applyEnuMove, updateTelemetry: updateFlightTelemetry } = useFlightPhysics();
const { step: stepCameraPhysics } = useCameraPhysics();
const { leftItems, rightItems, registerLeft, registerRight, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { recorderState, replayProgress, replayPov, captureScreenshot, sampleFrame, toggleRecorder, resetRecorder } = useScreenCapture();
const { isAuthenticated } = useAuth();
const { settings } = useAppSettings();

// Login gate for Screenshot / Screen Recording (the 3D Aerial and 3D Mesh
// subpages share this right dock): anonymous users get a green top-center
// reminder instead of the capture action.
const captureAuthNotice = ref(''); // '' | 'screenshot' | 'recording'
let captureAuthTimer = null;
function flashCaptureAuth(action) {
  captureAuthNotice.value = action;
  clearTimeout(captureAuthTimer);
  captureAuthTimer = setTimeout(() => { captureAuthNotice.value = ''; }, 6000);
}
function guardedScreenshot() {
  if (isAuthenticated.value) return captureScreenshot();
  flashCaptureAuth('screenshot');
}
function guardedToggleRecorder() {
  // Never trap an ACTIVE recording: toggling off is always allowed.
  if (isAuthenticated.value || recorderState.value !== 'idle') return toggleRecorder();
  flashCaptureAuth('recording');
}
const isRecorderActive = computed(() => recorderState.value !== 'idle');
let savedDiskVisibility = null;

// Active subpage of the 3D Exploration page: 'aerial' (default) or 'mesh'.
const activeSubpage = ref('aerial');

// Progress bar shown at the top center while a subpage switch streams and
// renders the new 3D assets (Google tiles <-> OSM Buildings).
const assetLoading = ref(false);
const assetLoadProgress = ref(0); // 0..1
let loadStartTs = 0;
let loadToken = 0; // guards against overlapping switches: latest one wins

// ── Splash-clip cover during subpage asset switches ──
// While the 3D data source is being swapped (progress bar visible), a muted,
// looping splash clip covers the scene so its half-loaded state is never
// visible. Reuses the auto-generated /splash/playlist.json manifest with a
// shuffled, no-back-to-back-repeat queue, mirroring the splash screen.
const switchVideoUrl = ref('');
let allSwitchClips = [];
let switchQueue = [];
let lastSwitchClip = '';
let warmVideo = null; // off-DOM element used to pre-buffer the next clip

function shuffleArray(arr) {
  const copy = arr.slice();
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

function refillSwitchQueue(avoidClip) {
  switchQueue = shuffleArray(allSwitchClips);
  if (switchQueue.length > 1 && switchQueue[0] === avoidClip) {
    const i = switchQueue.findIndex((c) => c !== avoidClip);
    [switchQueue[0], switchQueue[i]] = [switchQueue[i], switchQueue[0]];
  }
}

function peekSwitchClip() {
  if (!allSwitchClips.length) return '';
  if (!switchQueue.length) refillSwitchQueue(lastSwitchClip);
  return switchQueue[0];
}

function nextSwitchClip() {
  const clip = peekSwitchClip();
  if (!clip) return '';
  switchQueue.shift();
  lastSwitchClip = clip;
  return clip;
}

/** Extract the bare file name from a clip URL, for logging (like splash.js). */
function clipName(url) {
  return String(url).split('/').pop();
}

// Fetch the splash clip manifest, then warm the first queued clip. The splash
// screen's opening clip (firstClip, video_00.mp4) is EXCLUDED: the subpage
// switch cover should never replay the exact video the user already watched
// at startup. Falls back to firstClip only if it is the sole clip available.
async function loadSwitchClips() {
  try {
    const res = await fetch('/splash/playlist.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allSwitchClips = [...(data.otherClips || [])].filter(Boolean);
    if (!allSwitchClips.length && data.firstClip) allSwitchClips = [data.firstClip];
  } catch (e) {
    console.warn('[switch-cover] splash playlist fetch failed; switch cover disabled:', e.message);
    allSwitchClips = [];
  }
  warmSwitchClip();
}

// Buffer the next queued clip in the background so a later switch starts
// instantly, without the download competing with an in-flight tile stream.
function warmSwitchClip() {
  const clip = peekSwitchClip();
  if (!clip) return;
  if (!warmVideo) {
    warmVideo = document.createElement('video');
    warmVideo.muted = true;
    warmVideo.preload = 'auto';
  }
  if (warmVideo.src.indexOf(clip) !== -1) return; // already warming this clip
  warmVideo.src = clip;
  warmVideo.load();
  // Permanent log, mirroring splash.js: report when this clip has buffered
  // enough to be shown without stalling. The src guard ignores stale events
  // from a warm-up that has been superseded.
  warmVideo.addEventListener('canplay', function onCanPlay() {
    warmVideo.removeEventListener('canplay', onCanPlay);
    if (warmVideo.src.indexOf(clip) !== -1) {
      console.log('[switch-cover] Cached & ready to display: ' + clipName(clip));
    }
  });
}

// Permanent log, mirroring splash.js: report the clip that is starting to be
// displayed. Fires per cover mount (the keyed video element is remounted per
// clip and unmounted when the cover hides).
function onSwitchVideoPlaying() {
  if (switchVideoUrl.value) {
    console.log('[switch-cover] Now playing: ' + clipName(switchVideoUrl.value));
  }
}

const isCollisionFrozen = ref(false);
const collisionSurfaceNormal = ref(null);
const MIN_SAFETY_BUFFER = 2.0; // meters
const LOOK_AHEAD_TIME = 2.0; // seconds

const { googleReady, cesiumReady, googleError, cesiumError } = useConnectionStatus();
const connectionMessage = computed(() => {
  if (!cesiumReady.value && !googleReady.value) {
    return cesiumError.value || googleError.value || 'Cannot connect to Cesium and Google.';
  }
  if (!cesiumReady.value) return cesiumError.value || 'Cannot connect to Cesium.';
  if (!googleReady.value) return googleError.value || 'Cannot connect to Google.';
  return '';
});
const showConnectionError = computed(() => !cesiumReady.value || !googleReady.value);
let connectionCheckInterval = null;

const cesiumContainer = ref(null);
const streetViewReady = ref(false);
const lockedMessage = ref('');
let lockedMessageTimer = null;

const isTakeoffLanding = computed(() => altitudeGate.isTransitioning.value);
const isPausedByCollision = computed(() => altitudeGate.isPausedByCollision.value);
const isAutoActive = computed(() => isTakeoffLanding.value && !isPausedByCollision.value);
const collisionPausedMessage = computed(() => {
  if (!isPausedByCollision.value) return '';
  const p = altitudeGate.flightPhase.value;
  if (p === PHASES.ASCENDING) return t('aerialview.obstacle_above');
  if (p === PHASES.DESCENDING) return t('aerialview.obstacle_below');
  return '';
});
const isPreCaching = computed(() => {
  const p = altitudeGate.flightPhase.value;
  return p === PHASES.PRE_TAKEOFF || p === PHASES.PRE_LANDING;
});
// Street View is only used on the 3D Aerial (Google tiles) subpage. On the
// 3D Mesh (OSM Buildings) subpage the drone renders OSM buildings all the way
// from airborne to ground, so no Street View switch-over happens. Loading
// Google Street View there would also spin up a second WebGL context that
// fights the Cesium context (the source of the uniform3fv warnings).
const streetViewEnabled = computed(() => activeSource.value !== 'osm');
const showStreetView = computed(() => streetViewEnabled.value && (drone.alt - altitudeGate.surfaceAlt.value) < ASCEND_THRESHOLD);
const shouldPrewarmSV = computed(() => {
  if (!streetViewEnabled.value) return false;
  const phase = altitudeGate.flightPhase.value;
  if (phase === PHASES.PRE_LANDING || phase === PHASES.DESCENDING) return true;
  return (drone.alt - altitudeGate.surfaceAlt.value) < 20;
});
const isTransitioning = computed(() => {
  const rel = drone.alt - altitudeGate.surfaceAlt.value;
  return rel >= DESCEND_THRESHOLD && rel < ASCEND_THRESHOLD;
});
const streetViewOpacity = computed(() => {
  if (!streetViewEnabled.value) return 0;
  const rel = drone.alt - altitudeGate.surfaceAlt.value;
  if (rel <= DESCEND_THRESHOLD) return 1;
  if (rel >= ASCEND_THRESHOLD) return 0;
  return 1 - (rel - DESCEND_THRESHOLD) / (ASCEND_THRESHOLD - DESCEND_THRESHOLD);
});
// Effective state bound to StreetViewPane: live flight values normally, the
// replayed trajectory while the recorder replays it. Without this the replay
// (and the recorded clip) would stick to the 3D tiles and never reproduce
// the aerial -> street view asset switch.
const svPaneState = computed(() => {
  if (recorderState.value === 'replaying' && replayPov.value) {
    const pov = replayPov.value;
    return {
      lat: pov.lat,
      lon: pov.lon,
      headingRad: pov.headingRad,
      pitchRad: pov.pitchRad,
      relativeAlt: pov.relativeAlt,
      visible: pov.showStreetView,
      opacity: pov.streetViewOpacity,
      transitioning: pov.relativeAlt >= DESCEND_THRESHOLD && pov.relativeAlt < ASCEND_THRESHOLD,
    };
  }
  const pov = getStreetViewPov();
  return {
    lat: drone.lat,
    lon: drone.lon,
    headingRad: pov.headingRad,
    pitchRad: pov.pitchRad,
    relativeAlt: pov.relativeAlt,
    visible: showStreetView.value,
    opacity: streetViewOpacity.value,
    transitioning: isTransitioning.value,
  };
});
const takeoffLandingLabel = computed(() => {
  const p = altitudeGate.flightPhase.value;
  if (p === PHASES.PRE_TAKEOFF) return t('aerialview.preparing_takeoff');
  if (p === PHASES.PRE_LANDING) return t('aerialview.scanning_landing');
  if (p === PHASES.ASCENDING) return t('aerialview.taking_off');
  if (p === PHASES.DESCENDING) return t('aerialview.landing_in_progress');
  return altitudeGate.isOnGround.value ? t('aerialview.takeoff') : t('aerialview.landing');
});

function hideAllDisks() {
  showFlight.value = false;
  showCamera.value = false;
}

// Opening the Pages menu leaves the recording context: abort any active
// screen recording (discard without saving) so it cannot be orphaned by a
// navigation away from this page.
function onPagesOpen() {
  hideAllDisks();
  if (recorderState.value !== 'idle') {
    resetRecorder();
  }
}

// Wait until the newly active tileset (and the globe in mesh mode) reports
// its view-dependent tiles as loaded, with guards so a tile failure can
// never trap the progress bar on screen. Like the splash dismissal, this
// polls `tilesLoaded` rather than counting tileLoadProgressEvent requests.
function waitForAssetsLoaded() {
  return new Promise((resolve) => {
    const viewer = window.cesiumViewer;
    if (!viewer) return resolve();
    const start = performance.now();
    const MIN_WAIT = 400; // ms: let Cesium issue the first tile requests
    const MAX_WAIT = 30000; // ms: never trap the UI on tile failures
    const check = () => {
      const elapsed = performance.now() - start;
      const tileset = getActiveTileset();
      const tilesetDone = !tileset || tileset.tilesLoaded;
      const globeDone = activeSource.value !== 'osm' || viewer.scene.globe.tilesLoaded;
      if ((elapsed >= MIN_WAIT && tilesetDone && globeDone) || elapsed >= MAX_WAIT) {
        resolve();
        return;
      }
      requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  });
}

// Swap the 3D data source for the active subpage and show the top-center
// progress bar until the new assets are loaded and rendered.
async function swapSourceWithProgress(val) {
  const token = ++loadToken;
  assetLoading.value = true;
  assetLoadProgress.value = 0;
  loadStartTs = performance.now();
  // Lazy manifest fallback: AWAIT it so even the very first switch (clicked
  // before the mount-time warm-up has landed) still gets a cover clip.
  if (!allSwitchClips.length) await loadSwitchClips();
  switchVideoUrl.value = nextSwitchClip(); // '' only if the fetch failed
  // Serialize with any in-flight swap so rapid back-and-forth clicks queue
  // (last click wins) instead of being dropped by setSource's isSwitching
  // guard, which would leave the scene on the subpage the user clicked AWAY
  // from while this direction's cover hid early.
  while (isSwitching.value) {
    if (token !== loadToken) return; // superseded while queued
    await new Promise((r) => setTimeout(r, 100));
  }
  await setSource(val === 'mesh' ? 'osm' : 'google');
  await waitForAssetsLoaded();
  if (token !== loadToken) return; // a newer switch took over
  assetLoadProgress.value = 1;
  setTimeout(() => {
    if (token !== loadToken) return;
    assetLoading.value = false;
    switchVideoUrl.value = ''; // Transition fade-out keeps the last frame
    warmSwitchClip(); // pre-buffer the next queued clip for the next switch
  }, 500);
}

// ── Takeoff / Stop / Landing switcher ──
// The dock button is a 3-state switcher cycled ENTIRELY by the user:
//   takeoff -> stop -> landing -> stop -> takeoff -> ...
// It never judges whether the drone is on the ground or airborne:
// - 'takeoff' starts the auto takeoff sequence (climb to takeoffAltitude);
// - 'landing' starts the auto landing sequence (descend to the surface);
// - 'stop' aborts an in-progress sequence and holds the current altitude
//   (inside the bottom ground band the ground clamp settles the drone onto
//   the surface, so a low-altitude stop behaves like an early landing).
// The button stays ENABLED during takeoff/landing so the sequence can be
// interrupted mid-flight; the other buttons keep their original locking.
const SWITCH_SEQUENCE = ['takeoff', 'stop', 'landing', 'stop'];
const switchIndex = ref(0); // index of the action the button currently offers

function syncTakeoffSwitchItem() {
  const item = rightItems.find((i) => i.id === 'takeoff');
  if (!item) return;
  const action = SWITCH_SEQUENCE[switchIndex.value];
  item.icon = action === 'takeoff' ? 'MENU_TAKEOFF'
    : action === 'landing' ? 'MENU_LANDING'
    : 'MENU_STOP';
  item.titleKey = `aerialview.${action}`;
}

function toggleTakeoffLanding() {
  const viewer = window.cesiumViewer;
  const action = SWITCH_SEQUENCE[switchIndex.value];
  if (action === 'takeoff') {
    // startTakeoff returns false when the drone is already above the takeoff
    // altitude (settings.takeoffAltitude, default 100 m): no sequence starts,
    // the user just gets the green reminder below.
    //
    // The takeoff tile pre-warm teleports the Cesium camera to the target
    // altitude for a few frames. Only allow that while the Street View
    // overlay fully covers the (still rendering) Cesium canvas — mirrored
    // from the .cesium-hidden watcher below — otherwise the teleport shows
    // up as a visible tremble.
    const cesiumCovered = svPaneState.value.visible && !svPaneState.value.transitioning && streetViewReady.value;
    if (!altitudeGate.startTakeoff(viewer, { cameraPrewarm: cesiumCovered })) {
      flashTakeoffLimitNotice();
    }
  } else if (action === 'landing') {
    altitudeGate.startLanding(viewer);
  } else {
    altitudeGate.stopAuto();
  }
  switchIndex.value = (switchIndex.value + 1) % SWITCH_SEQUENCE.length;
  syncTakeoffSwitchItem();
}

// Green top-center reminder: 'takeoff' was clicked while the drone is already
// beyond the takeoff altitude. Auto-hides after a few seconds.
const takeoffLimitNotice = ref('');
let takeoffLimitTimer = null;
function flashTakeoffLimitNotice() {
  takeoffLimitNotice.value = t('aerialview.takeoff_above_limit', { alt: settings.takeoffAltitude });
  clearTimeout(takeoffLimitTimer);
  takeoffLimitTimer = setTimeout(() => { takeoffLimitNotice.value = ''; }, 5000);
}

watch(
  [() => svPaneState.value.visible, () => svPaneState.value.transitioning, streetViewReady],
  ([show, transitioning, svReady]) => {
    const viewer = window.cesiumViewer;
    if (viewer) {
      // In mesh (OSM) mode the globe must stay visible as ground context; in
      // aerial (Google) mode it is only shown during the street-view
      // transition crossfade.
      viewer.scene.globe.show = activeSource.value === 'osm' || (show && transitioning);
    }
    if (cesiumContainer.value) {
      // Only hide Cesium when Street View is fully loaded to prevent black flash
      cesiumContainer.value.classList.toggle('cesium-hidden', show && !transitioning && svReady);
    }
  },
  { immediate: true }
);

function getFlightCommandSpeed() {
  if (activeFlightMode.value === 'M') {
    const cmdMag = Math.hypot(flightCmd.vx, flightCmd.vy);
    return cmdMag * 0.0002 * 111320;
  }
  if (activeFlightMode.value === 'H') {
    return Math.abs(flightCmd.vz) * 20.0;
  }
  return 0;
}

function getFlightCommandDirection() {
  const viewer = window.cesiumViewer;
  if (!viewer) return null;

  const position = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, drone.alt);
  const enuTransform = Cesium.Transforms.eastNorthUpToFixedFrame(position);

  if (activeFlightMode.value === 'M') {
    const mag = Math.hypot(flightCmd.vx, flightCmd.vy) || 1;
    const headingRad = Cesium.Math.toRadians(drone.heading);
    const enuDir = new Cesium.Cartesian3(
      (flightCmd.vy * Math.sin(headingRad) + flightCmd.vx * Math.cos(headingRad)) / mag,
      (flightCmd.vy * Math.cos(headingRad) - flightCmd.vx * Math.sin(headingRad)) / mag,
      0
    );
    const worldDir = Cesium.Matrix4.multiplyByPointAsVector(enuTransform, enuDir, new Cesium.Cartesian3());
    return Cesium.Cartesian3.normalize(worldDir, worldDir);
  }

  if (activeFlightMode.value === 'H') {
    const enuUp = new Cesium.Cartesian3(0, 0, flightCmd.vz >= 0 ? 1 : -1);
    const worldDir = Cesium.Matrix4.multiplyByPointAsVector(enuTransform, enuUp, new Cesium.Cartesian3());
    return Cesium.Cartesian3.normalize(worldDir, worldDir);
  }

  return null;
}

function checkCollisionAhead() {
  const viewer = window.cesiumViewer;
  const tileset = getActiveTileset();
  if (!viewer || !tileset || !showFlight.value) return null;

  const speed = getFlightCommandSpeed();
  if (speed <= 0) return null;

  const direction = getFlightCommandDirection();
  if (!direction) return null;

  const position = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, drone.alt);
  const ray = new Cesium.Ray(position, direction);
  let result = null;
  try {
    result = viewer.scene.pickFromRay(ray);
  } catch {
    return null; // transient raycast failure while tiles stream — skip this frame
  }

  if (!result || !result.position) return null;

  const hitObject = result.object;
  const isTilesetHit =
    hitObject === tileset ||
    (hitObject && hitObject.tileset === tileset) ||
    (hitObject && hitObject.primitive === tileset);
  if (!isTilesetHit) return null;

  const distance = Cesium.Cartesian3.distance(position, result.position);
  const buffer = MIN_SAFETY_BUFFER + speed * LOOK_AHEAD_TIME;
  if (distance > buffer) return null;

  const normal = Cesium.Cartesian3.normalize(
    Cesium.Cartesian3.subtract(position, result.position, new Cesium.Cartesian3()),
    new Cesium.Cartesian3()
  );

  return { distance, position: result.position, normal };
}

function projectEnuMove(enuMove, collision) {
  const position = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, drone.alt);
  const enuTransform = Cesium.Transforms.eastNorthUpToFixedFrame(position);
  const invTransform = Cesium.Matrix4.inverse(enuTransform, new Cesium.Matrix4());
  const enuNormal = Cesium.Matrix4.multiplyByPointAsVector(invTransform, collision.normal, new Cesium.Cartesian3());
  Cesium.Cartesian3.normalize(enuNormal, enuNormal);

  const dot = Cesium.Cartesian3.dot(enuMove, enuNormal);
  if (dot >= 0) return enuMove;

  const normalComponent = Cesium.Cartesian3.multiplyByScalar(enuNormal, dot, new Cesium.Cartesian3());
  return Cesium.Cartesian3.subtract(enuMove, normalComponent, new Cesium.Cartesian3());
}

function syncCesiumCamera() {
  if (typeof window.updateCesiumCamera === 'function') {
    window.updateCesiumCamera({
      lat: drone.lat,
      lon: drone.lon,
      alt: drone.alt,
      heading: drone.heading,
      gimbalYaw: gimbal.yaw,
      gimbalPitch: gimbal.pitch,
      gimbalRoll: gimbal.roll,
    });
  }
}

function getStreetViewPov() {
  const headingRad = ((drone.heading + gimbal.yaw) * Math.PI) / 180;
  const pitchRad = (gimbal.pitch * Math.PI) / 180;
  const relativeAlt = Math.max(0, drone.alt - altitudeGate.surfaceAlt.value);
  return { headingRad, pitchRad, relativeAlt };
}

let rafId = null;

function updateDroneState() {
  const dt = 1 / 60;
  const viewer = window.cesiumViewer;

  altitudeGate.update(viewer);

  if (isTakeoffLanding.value) {
    altitudeGate.stepAuto(dt, viewer);
    // During collision pause, allow manual flight/camera so user can reposition.
    // Only block manual input when the auto sequence is actively moving.
    if (!isPausedByCollision.value) {
      onFlightStop();
      onCameraStop();
      return;
    }
  }

  const allowAltitude = !altitudeGate.isOnGround.value || activeFlightMode.value === 'H';
  let enuMove = null;

  if (showFlight.value) {
    enuMove = computeDesiredEnuMove(dt, allowAltitude);
  }

  const collision = checkCollisionAhead();
  if (collision && enuMove) {
    enuMove = projectEnuMove(enuMove, collision);
    isCollisionFrozen.value = true;
    collisionSurfaceNormal.value = collision.normal;
  } else {
    isCollisionFrozen.value = false;
    collisionSurfaceNormal.value = null;
  }

  if (showFlight.value) {
    applyEnuMove(enuMove);
    updateFlightTelemetry(allowAltitude);
    // R-mode: rotate drone heading (3D view rotates accordingly)
    if (activeFlightMode.value === 'R') {
      drone.heading += flightCmd.yaw * 60.0 * dt;
    }
  }

  if (altitudeGate.isOnGround.value) {
    if (activeFlightMode.value === 'M') {
      // M-mode: clamp to ground, no vertical movement allowed
      altitudeGate.snapToGround();
      flightCmd.vz = 0;
    } else if (activeFlightMode.value === 'R') {
      // R-mode: allow rotation, clamp altitude to ground
      altitudeGate.snapToGround();
      flightCmd.vz = 0;
    }
    // H-mode: no ground clamp — user controls altitude freely
  }

  if (showCamera.value) {
    stepCameraPhysics(dt, { applyMovement: true });
  }
}

let loopErrorLogTs = 0;

function loop() {
  // A single bad frame (e.g., a Cesium raycast failing while tiles stream)
  // must never kill the loop: if it stops, the scene freezes and the disks
  // appear dead. Log throttled and keep animating.
  try {
    if (recorderState.value === 'recording') {
      sampleFrame(drone, gimbal, altitudeGate.surfaceAlt.value);
    }
    // Advance the asset-loading progress bar while a subpage switch streams
    // in (asymptotic to 90%; the last 10% completes on tilesLoaded).
    if (assetLoading.value && assetLoadProgress.value < 0.9) {
      const elapsedMs = performance.now() - loadStartTs;
      assetLoadProgress.value = Math.min(0.9, 0.9 * (1 - Math.exp(-elapsedMs / 1500)));
    }
    // During replay the replay engine owns the Cesium camera; skip the flight
    // physics, collision checks and camera sync so they cannot fight it.
    if (recorderState.value !== 'replaying') {
      updateDroneState();
      syncCesiumCamera();
    }
  } catch (err) {
    const now = performance.now();
    if (now - loopErrorLogTs > 2000) {
      loopErrorLogTs = now;
      console.error('[AerialView] Frame error (loop continues):', err);
    }
  }
  rafId = requestAnimationFrame(loop);
}

onMounted(() => {
  cesiumContainer.value = document.getElementById('cesiumContainer');
  startFlightKeyboard();
  startCameraKeyboard();
  syncCesiumCamera();

  // Initial connection check and periodic re-check.
  checkGoogleConnection();
  checkCesiumConnection();
  connectionCheckInterval = setInterval(() => {
    checkGoogleConnection();
    checkCesiumConnection();
  }, 10000);

  // Register pages for the router menu
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'copilot', nameKey: 'copilotview.page_copilot', route: '/copilot' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  registerLeft({
    id: 'router',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'aerialview.pages',
      pages,
      onBeforeOpen: onPagesOpen,
    }),
  });
  registerLeft({
    id: 'camera',
    icon: 'MENU_CAMERA',
    titleKey: 'aerialview.camera',
    active: showCamera.value,
    onClick: toggleCamera,
  });
  registerLeft({
    id: 'subpage_aerial',
    icon: 'MENU_HELICOPTER',
    titleKey: 'aerialview.subpage_aerial',
    active: activeSubpage.value === 'aerial',
    onClick: () => {
      activeSubpage.value = 'aerial';
    },
  });
  registerLeft({
    id: 'subpage_mesh',
    icon: 'MENU_MESH',
    titleKey: 'aerialview.subpage_mesh',
    active: activeSubpage.value === 'mesh',
    onClick: () => {
      activeSubpage.value = 'mesh';
    },
  });

  registerRight({
    id: 'steer',
    icon: 'MENU_CONTROL_STICK',
    titleKey: 'aerialview.steer',
    active: showFlight.value,
    onClick: toggleFlight,
  });
  // Takeoff/Stop/Landing switcher — always starts at 'takeoff'; its icon
  // and title are driven by switchIndex (see toggleTakeoffLanding), NOT by
  // the drone's altitude.
  registerRight({
    id: 'takeoff',
    icon: 'MENU_TAKEOFF',
    titleKey: 'aerialview.takeoff',
    onClick: toggleTakeoffLanding,
  });
  registerRight({
    id: 'screenshot',
    icon: 'MENU_PHOTO',
    titleKey: 'aerialview.screenshot',
    onClick: guardedScreenshot,
  });
  registerRight({
    id: 'recorder',
    icon: 'MENU_RECORDER',
    titleKey: 'aerialview.recorder',
    active: isRecorderActive,
    danger: true,
    onClick: guardedToggleRecorder,
  });

  // Sync dock button active states with toggle state
  watch(showFlight, (val) => {
    const item = rightItems.find((i) => i.id === 'steer');
    if (item) item.active = val;
  });
  watch(showCamera, (val) => {
    const item = leftItems.find((i) => i.id === 'camera');
    if (item) item.active = val;
  });

  // Keep the subpage selector buttons in sync with the active subpage.
  watch(activeSubpage, (val) => {
    const aerialBtn = leftItems.find((i) => i.id === 'subpage_aerial');
    if (aerialBtn) aerialBtn.active = val === 'aerial';
    const meshBtn = leftItems.find((i) => i.id === 'subpage_mesh');
    if (meshBtn) meshBtn.active = val === 'mesh';
  
    // Swap the 3D data source to match the active subpage (with a top-center
    // progress bar while the new assets load and render).
    swapSourceWithProgress(val);
  });

  // Warm the splash-clip manifest + first cover clip in the background, well
  // after the initial tile load has settled so it cannot compete with it.
  setTimeout(loadSwitchClips, 8000);

  // React to recorder state transitions: update the dock button title, and
  // close the Flight/Gimbal disks during replay (restored when it ends).
  watch(recorderState, (state, prev) => {
    const item = rightItems.find((i) => i.id === 'recorder');
    if (item) {
      item.titleKey =
        state === 'recording' ? 'aerialview.recorder_stop'
        : state === 'replaying' ? 'aerialview.recorder_cancel'
        : 'aerialview.recorder';
    }
    // Lock the 3D Aerial / 3D Mesh source switch and the Screenshot button
    // while the recorder is active: swapping the 3D data source mid-recording
    // would corrupt the aerial/street-view asset tracking of the clip, and a
    // screenshot during capture is redundant.
    const assetLocked = state !== 'idle';
    for (const list of [leftItems, rightItems]) {
      for (const dockItem of list) {
        if (dockItem.id === 'subpage_aerial' || dockItem.id === 'subpage_mesh' || dockItem.id === 'screenshot') {
          dockItem.disabled = assetLocked;
        }
      }
    }
    if (state === 'replaying' && prev === 'recording') {
      savedDiskVisibility = { flight: showFlight.value, camera: showCamera.value };
      showFlight.value = false;
      showCamera.value = false;
    } else if (state === 'idle' && prev === 'replaying' && savedDiskVisibility) {
      showFlight.value = savedDiskVisibility.flight;
      showCamera.value = savedDiskVisibility.camera;
      savedDiskVisibility = null;
    }
  });

  // Disable non-navigation dock buttons during takeoff/landing transitions —
  // EXCEPT the takeoff/stop/landing switcher itself, which must stay clickable
  // so the user can interrupt the sequence mid-flight (its whole purpose).
  // During a collision pause the other buttons unlock so the user can
  // reposition. Pages (router) and Chat buttons remain enabled so the user
  // can navigate away.
  watch([isTakeoffLanding, isPausedByCollision], ([transitioning, paused]) => {
    const lockableIds = ['steer', 'camera', 'recorder'];
    for (const list of [leftItems, rightItems]) {
      for (const item of list) {
        if (lockableIds.includes(item.id)) {
          item.disabled = transitioning && !paused;
        }
      }
    }
  });

  rafId = requestAnimationFrame(loop);
});

onUnmounted(() => {
  resetRecorder();
  stopFlightKeyboard();
  stopCameraKeyboard();
  if (rafId) cancelAnimationFrame(rafId);
  if (connectionCheckInterval) clearInterval(connectionCheckInterval);
  clear();
  unregisterPage('aerial');
  unregisterPage('realdrone');
  unregisterPage('map');
  unregisterPage('copilot');
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
    :show-camera="showCamera"
    :show-hud="recorderState !== 'replaying'"
    :flight="flight"
    :camera="camera"
        :disabled="isAutoActive"
    @flightMove="onFlightMove"
    @flightStop="onFlightStop"
    @flightModeChange="onFlightModeChange"
    @cameraMove="onCameraMove"
    @cameraStop="onCameraStop"
    @cameraModeChange="onCameraModeChange"
  >
    <template #background>
      <StreetViewPane
        class="view-composer__background"
        :lat="svPaneState.lat"
        :lon="svPaneState.lon"
        :heading="svPaneState.headingRad"
        :pitch="svPaneState.pitchRad"
        :altitude="svPaneState.relativeAlt"
        :visible="svPaneState.visible"
        :prewarm="shouldPrewarmSV"
        :style="{ opacity: svPaneState.opacity }"
        @ready="streetViewReady = true"
      />
    </template>

    <template #top-overlay>
      <ConnectionError :visible="showConnectionError" :message="connectionMessage" />
      <CollisionWarning :visible="isCollisionFrozen" />
      <div v-if="collisionPausedMessage" class="top-center-message top-center-message--warning">
        {{ collisionPausedMessage }}
      </div>
      <div v-if="lockedMessage" class="top-center-message top-center-message--warning">
        {{ lockedMessage }}
      </div>
      <div v-if="takeoffLimitNotice" class="top-center-message top-center-message--success">
        {{ takeoffLimitNotice }}
      </div>
      <div
        v-if="isPreCaching"
        class="pre-cache-overlay"
      >
        <span class="pre-cache-overlay__text">{{ takeoffLandingLabel }}</span>
      </div>
      <div
        v-if="recorderState === 'replaying'"
        class="top-center-message replay-pill"
      >
        {{ t('aerialview.replaying', { pct: Math.round(replayProgress * 100) }) }}
      </div>
      <Transition name="switch-video">
        <div v-if="assetLoading && switchVideoUrl" class="switch-video-cover">
          <video
            :key="switchVideoUrl"
            class="switch-video-cover__video"
            :src="switchVideoUrl"
            autoplay
            muted
            loop
            playsinline
            preload="auto"
            @playing="onSwitchVideoPlaying"
          />
        </div>
      </Transition>
      <div
        v-if="captureAuthNotice"
        class="top-center-message top-center-message--auth"
      >
        {{ t(`aerialview.auth_notice_${captureAuthNotice}`) }}
      </div>
      <div
        v-if="assetLoading"
        class="top-center-message asset-loading"
      >
        <span>{{ t('aerialview.loading_assets') }}</span>
        <div class="asset-loading__track">
          <div class="asset-loading__fill" :style="{ width: (assetLoadProgress * 100).toFixed(1) + '%' }" />
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
:deep(.view-composer__background) {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

:deep(.view-composer__background.street-view-pane--visible) {
  pointer-events: auto;
}

.pre-cache-overlay {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: inline-flex;
  align-items: center;
  pointer-events: none;
}

.pre-cache-overlay__text {
  font-family: Calibri, 'Segoe UI', sans-serif;
  font-size: 0.77rem;
  font-weight: 700;
  color: #ffffff;
  padding: 12px 28px;
  border-radius: 8px;
  background: rgba(34, 197, 94, 0.88);
  letter-spacing: 0.02em;
  white-space: nowrap;
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.6);
  animation: scan-pulse 1.2s ease-in-out infinite;
}

.pre-cache-overlay--shake {
  animation: engine-shake 0.08s infinite alternate;
}

.pre-cache-overlay--scan .pre-cache-overlay__text {
  animation: scan-pulse 1.2s ease-in-out infinite;
}

@keyframes engine-shake {
  0%   { transform: translateX(-50%) translate(1px, -1px); }
  25%  { transform: translateX(-50%) translate(-1px, 2px); }
  50%  { transform: translateX(-50%) translate(2px, 0px); }
  75%  { transform: translateX(-50%) translate(-2px, -1px); }
  100% { transform: translateX(-50%) translate(1px, 1px); }
}

@keyframes scan-pulse {
  0%, 100% { opacity: 0.6; }
  50%      { opacity: 1; }
}

.top-center-message {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  padding: 12px 28px;
  border-radius: 8px;
  font-family: Calibri, 'Segoe UI', sans-serif;
  font-size: 0.77rem;
  font-weight: 700;
  color: #ffffff;
  white-space: nowrap;
  pointer-events: none;
  text-align: center;
  letter-spacing: 0.02em;
}

.top-center-message--warning {
  background: rgba(180, 100, 0, 0.9);
  box-shadow: 0 0 18px rgba(180, 100, 0, 0.6);
  animation: scan-pulse 1.2s ease-in-out infinite;
}

/* Green info reminder (e.g. takeoff clicked above the takeoff altitude). */
.top-center-message--success {
  background: rgba(34, 197, 94, 0.9);
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.6);
}

.replay-pill {
  background: rgba(34, 197, 94, 0.88);
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.6);
}

/* Login-gate reminder for Screenshot / Screen Recording */
.top-center-message--auth {
  background: rgba(34, 197, 94, 0.92);
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.6);
}

.asset-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  background: rgba(34, 197, 94, 0.88);
  box-shadow: 0 0 18px rgba(34, 197, 94, 0.6);
}

.asset-loading__track {
  width: 240px;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.3);
  overflow: hidden;
}

.asset-loading__fill {
  height: 100%;
  border-radius: 3px;
  background: #ffffff;
  transition: width 0.15s linear;
}

/* Splash-clip cover shown while a subpage switch loads and renders the new
   3D assets. Sits above the 3D background (z 0) but below the docks (z 10),
   HUD (z 50) and top-center messages (z 100). */
.switch-video-cover {
  position: fixed;
  inset: 0;
  z-index: 4;
  background: #000000;
  pointer-events: none;
}

.switch-video-cover__video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.switch-video-enter-active,
.switch-video-leave-active {
  transition: opacity 0.35s ease;
}

.switch-video-enter-from,
.switch-video-leave-to {
  opacity: 0;
}
</style>

<script setup>
import { ref, computed, watch, h, onMounted, onUnmounted, nextTick } from 'vue';
import { useI18n } from 'vue-i18n';
import ViewComposer from '@shared/_ViewComposer.vue';
import DockMenuButton from '@shared/DockMenuButton.vue';
import VolumeDockButton from '@shared/VolumeDockButton.vue';
import { useFlightCommands } from '@shared-composables/useFlightCommands.js';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { createWhepPlayer } from '@shared-composables/useWhepPlayer.js';
import { useStreamConfig } from '@shared-composables/useStreamConfig.js';
import { useDroneTelemetry } from '@shared-composables/useDroneTelemetry.js';
import { useDroneCommands } from '@shared-composables/useDroneCommands.js';
import { useAppSettings } from '@shared-composables/useAppSettings.js';
import { useAuth } from '@shared-composables/useAuth.js';
import { useLiveCapture } from '@shared-composables/useLiveCapture.js';

const { t } = useI18n();
const { settings } = useAppSettings();

// Live telemetry of the physical drone (singleton WS subscription; feeds
// the Host subpage's HUD via the ViewComposer's realTelemetry prop).
const { telemetry: droneTelemetry } = useDroneTelemetry();

// Real flight commands (takeoff/land/hover/move/...) — the separated module.
const droneCommands = useDroneCommands();

// ── Takeoff / Stop / Landing switcher (real drone) ──
// Same user-driven 4-state cycle as the 3D Exploration subpages:
//   takeoff -> stop -> landing -> stop -> takeoff -> ...
// No airborne/on-ground judgment: the user cycles freely, even mid-maneuver.
//   takeoff -> bridge MotionCommander takeoff to ~0.5 m
//   stop    -> hover in place (zero velocity — NOT the motor-cut emergency)
//   landing -> the bridge's gentle landing profile
// The state advances only when the command was actually sent (a dropped
// command — link down — must not light up a phantom state). The button is
// never disabled by maneuvers; the subpage locking below is unchanged.
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

function toggleTakeoff() {
  const action = SWITCH_SEQUENCE[switchIndex.value];
  const sent = action === 'takeoff' ? droneCommands.takeoff()
    : action === 'landing' ? droneCommands.land()
    : droneCommands.hover();
  if (!sent) return;
  switchIndex.value = (switchIndex.value + 1) % SWITCH_SEQUENCE.length;
  syncTakeoffSwitchItem();
}

// ── Flight disk -> real drone ──
// Disk payloads are in ±sensitivity units (FlightController default 3),
// scaled here into the bridge's safe ranges. While a command is active it is
// re-sent every 150 ms: the bridge's dead-man switch (0.5 s) would otherwise
// hover the drone — and lost keep-alives (closed tab, dead relay) hover it
// automatically. currentMove holds DISK axes (vx right+, vy forward+);
// sendCurrentMove maps them onto the cflib body frame (vx forward, vy left,
// vz up, yawrate deg/s — sign calibration pending the first flight test).
const DISK_UNITS = 3;
const DISK_MAX_XY = 0.5;  // m/s horizontal
const DISK_MAX_Z = 0.5;   // m/s vertical
const DISK_MAX_YAW = 60;  // deg/s yaw
const MOVE_KEEPALIVE_MS = 150;

const currentMove = { vx: 0, vy: 0, vz: 0, yawRate: 0 };
let moveKeepAlive = null;

function sendCurrentMove() {
  const c = currentMove;
  droneCommands.move({ vx: c.vy, vy: -c.vx, vz: c.vz, yawRate: c.yawRate });
}

function ensureMoveKeepAlive() {
  if (moveKeepAlive) return;
  moveKeepAlive = setInterval(() => {
    const c = currentMove;
    if (c.vx || c.vy || c.vz || c.yawRate) sendCurrentMove();
  }, MOVE_KEEPALIVE_MS);
}

function onRealFlightMove(payload) {
  onFlightMove(payload); // keep the disk UI state in sync
  if (!payload || !payload.mode) return;
  if (payload.mode === 'M') {
    currentMove.vx = ((payload.vx || 0) / DISK_UNITS) * DISK_MAX_XY;
    currentMove.vy = ((payload.vy || 0) / DISK_UNITS) * DISK_MAX_XY;
    currentMove.vz = 0;
    currentMove.yawRate = 0;
  } else if (payload.mode === 'H') {
    currentMove.vx = 0;
    currentMove.vy = 0;
    currentMove.vz = ((payload.vz || 0) / DISK_UNITS) * DISK_MAX_Z;
    currentMove.yawRate = 0;
  } else if (payload.mode === 'R') {
    currentMove.vx = 0;
    currentMove.vy = 0;
    currentMove.vz = 0;
    currentMove.yawRate = ((payload.yaw || 0) / DISK_UNITS) * DISK_MAX_YAW;
  }
  ensureMoveKeepAlive();
  sendCurrentMove(); // immediate response; the interval keeps it alive
}

// Zero the command and tell the drone to hover (the zero-velocity move also
// disarms the bridge watchdog). Called on disk release, disk close, subpage
// switch away from 'host', and unmount.
function stopRealFlight() {
  onFlightStop();
  currentMove.vx = 0;
  currentMove.vy = 0;
  currentMove.vz = 0;
  currentMove.yawRate = 0;
  droneCommands.hover();
}

function onRealFlightStop() {
  stopRealFlight();
}

// ── Emergency stop (red button, top of the right sidebar) ──
// Cuts the motors NOW — the drone falls, even mid-air (bridge 'estop' ->
// commander.send_stop_setpoint). Zero the disk state FIRST so the 150 ms
// keep-alive cannot resurrect thrust before the estop lands; then reset
// the takeoff switcher to offer 'takeoff' again (the drone is down).
// Deliberately NOT the switcher's 'stop' (hover) nor 'landing' (gentle).
function emergencyStop() {
  currentMove.vx = 0;
  currentMove.vy = 0;
  currentMove.vz = 0;
  currentMove.yawRate = 0;
  onFlightStop();
  droneCommands.estop();
  switchIndex.value = 0;
  syncTakeoffSwitchItem();
}

// ── Screenshot / Recorder on the live stream ──
// Same login gate as the 3D subpages: anonymous users get a green top-center
// reminder instead of the capture action. The capture source is whichever
// <video> is on screen (both subpages play the SAME shared stream, so both
// buttons work on the Viewer too).
const { isAuthenticated } = useAuth();
const { recorderState, isRecorderActive, captureScreenshot, toggleRecorder, stopRecorder } = useLiveCapture();

const captureAuthNotice = ref(''); // '' | 'screenshot' | 'recording'
let captureAuthTimer = null;
function flashCaptureAuth(action) {
  captureAuthNotice.value = action;
  clearTimeout(captureAuthTimer);
  captureAuthTimer = setTimeout(() => { captureAuthNotice.value = ''; }, 6000);
}

function guardedScreenshot() {
  if (isAuthenticated.value) return captureScreenshot(activeVideoEl());
  flashCaptureAuth('screenshot');
}

function guardedToggleRecorder() {
  // Never trap an ACTIVE recording: toggling off is always allowed.
  if (isAuthenticated.value || recorderState.value !== 'idle') return toggleRecorder(activeVideoEl());
  flashCaptureAuth('recording');
}

// Real Drone (真机接入) page — UI shell only.
//
// Two subpages, switched via the left sidebar:
// - 'viewer' (Livestream Viewer / 直播观看): Customer Service outlook —
//   left panel lists the available livestreams, right panel plays the
//   MediaMTX broadcast. Only the draggable divider is implemented for now.
// - 'host' (Livestream Host / 机主直播): mirrors the 3D Aerial outlook —
//   HUD dashboard (REAL drone telemetry, relayed drone -> server -> browser
//   via extension/crazyflie_bridge/telemetry_relay.py) and the Flight disk.
//   The Takeoff/Stop/Landing switcher AND the Flight disk are wired to the
//   REAL drone via the separated flight-functions module
//   @shared-composables/useDroneCommands.js (browser -> server
//   /api/drone/command -> telemetry_relay.py -> motion_control_ws.py).
//   Safety: the bridge REFUSES takeoff while the drone is tethered via USB,
//   and a 0.5 s dead-man switch hovers the drone if velocity commands stop
//   arriving (closed tab, dead relay/server).
//   There is NO Camera/Gimbal UI: the Crazyflie has no gimbal.
//
// Button locking: Steer (right #1) and Takeoff/Landing
// (right #2) are only clickable while the 'host' subpage is active.
// Switching to 'viewer' or opening the Pages menu locks them;
// clicking 'Livestream Host' re-enables them.

const {
  flight,
  showFlight,
  toggleFlight,
  onFlightMove,
  onFlightStop,
  onFlightModeChange,
} = useFlightCommands();

const { leftItems, rightItems, registerLeft, registerRight, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();

// Active subpage of the Real Drone page: 'viewer' | 'host' (default).
const activeSubpage = ref('host');
// 'host' uses the 3D Aerial outlook (HUD + disks);
// 'viewer' uses the Customer Service split-panel outlook.
const isAerialStyle = computed(() => activeSubpage.value === 'host');
const isSplitStyle = computed(() => activeSubpage.value === 'viewer');

/* ─── Split-layout subpages: left-column width drag (Customer Service pattern) ─── */
const LEFT_MIN = 280;
const LEFT_MAX = 600;
const LEFT_DEFAULT = 40; // percentage
const leftWidthPct = ref(LEFT_DEFAULT);
const isDragging = ref(false);

function onDividerPointerDown(e) {
  e.preventDefault();
  isDragging.value = true;
  document.addEventListener('pointermove', onDividerPointerMove);
  document.addEventListener('pointerup', onDividerPointerUp);
}

function onDividerPointerMove(e) {
  if (!isDragging.value) return;
  const panel = document.querySelector('.split-page');
  if (!panel) return;
  const rect = panel.getBoundingClientRect();
  // The page keeps horizontal padding to clear the floating docks — the
  // percentage math must use the CONTENT box, not the padding box.
  const cs = getComputedStyle(panel);
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  const contentW = rect.width - padL - padR;
  const x = e.clientX - rect.left - padL;
  const pct = (x / contentW) * 100;
  const minPct = (LEFT_MIN / contentW) * 100;
  const maxPct = (LEFT_MAX / contentW) * 100;
  leftWidthPct.value = Math.min(maxPct, Math.max(minPct, pct));
}

function onDividerPointerUp() {
  isDragging.value = false;
  document.removeEventListener('pointermove', onDividerPointerMove);
  document.removeEventListener('pointerup', onDividerPointerUp);
}

function hideAllDisks() {
  stopRealFlight(); // never leave a stale velocity running on the real drone
  showFlight.value = false;
}

// Lock/unlock the flight-control buttons (Steer, Takeoff/Landing).
// Locked buttons ignore clicks and render dimmed with a not-allowed cursor.
const LOCKABLE_BUTTON_IDS = ['steer', 'takeoff'];

function setControlsLocked(locked) {
  for (const list of [leftItems, rightItems]) {
    for (const item of list) {
      if (LOCKABLE_BUTTON_IDS.includes(item.id)) item.disabled = locked;
    }
  }
}

// Opening the Pages menu also hides the disks and locks the controls.
function onPagesBeforeOpen() {
  hideAllDisks();
  setControlsLocked(true);
}

/* ─── Livestream: WHEP playback of the MediaMTX stream catalog ─── */
// ONE shared connection for both subpages, playing ONE selected stream
// (default: the PRIMARY, first catalog entry = our own broadcast).
// The ONLY way to change the stream is clicking a card in the Viewer's
// left panel — a stop()+start() re-handshake, so just one stream ever
// consumes bandwidth. Switching subpages NEVER changes the stream: it
// only re-attaches the already-live MediaStream, no second handshake.
// The catalog comes from the backend's /api/stream/config (server/
// config.json "mediamtx" section) with per-environment fallbacks — see
// useStreamConfig. Passed to the player as a getter so it is resolved at
// every start()/retry — the async config fetch needs no await here.
const { streams } = useStreamConfig();

// Viewer card selection. null = follow the primary stream until the user
// picks a card. (Static catalog for the TESTING phase; once the
// FastAPI-users backend lands, identities come from the user database.)
const selectedStreamId = ref(null);
const primaryStream = computed(() => streams.value[0] || null);
const selectedStream = computed(
  () => streams.value.find((s) => s.id === selectedStreamId.value) || primaryStream.value,
);
// The stream the shared connection plays — the selected card, on BOTH
// subpages (subpage switches must not change it).
const targetUrl = computed(() => selectedStream.value?.whep_url || '');
// What the player was last started with — restart only on a real change.
let playingUrl = '';

const hostVideoEl = ref(null);
const viewerVideoEl = ref(null);

// Top-center green progress pill while the connection is being set up
// (same look as the 3D Aerial/Mesh asset-loading bar).
const liveLoading = ref(false);
const liveProgress = ref(0); // 0..1

function onLiveProgress(phase) {
  if (phase === 'start') {
    liveLoading.value = true;
    liveProgress.value = 0.15;
  } else if (phase === 'offer') {
    liveProgress.value = Math.max(liveProgress.value, 0.35);
  } else if (phase === 'handshake') {
    liveProgress.value = Math.max(liveProgress.value, 0.65);
  } else if (phase === 'track') {
    liveProgress.value = Math.max(liveProgress.value, 0.85);
  }
}

const livePlayer = createWhepPlayer({
  url: () => targetUrl.value,
  logTag: 'live',
  onProgress: onLiveProgress,
});

// The video element actually rendered a frame — finish the progress bar.
function onLivePlaying() {
  liveProgress.value = 1;
  setTimeout(() => {
    liveLoading.value = false;
  }, 400);
}

// Point the shared connection at a freshly mounted <video> element.
// Diagnostic: log how long the first frame takes to appear after attach,
// so view-side delay is separable from connection-side delay.
function attachLiveStream(el) {
  if (!el) return;
  const which = el === hostVideoEl.value ? 'host' : 'viewer';
  const tAttach = performance.now();
  console.log(`[live] attach -> '${which}' <video> (tracks already live: ${livePlayer.hasTracks()})`);
  el.addEventListener('playing', () => {
    console.log(`[live] first frame rendered on '${which}' <video> (${el.videoWidth}x${el.videoHeight}) — t+${((performance.now() - tAttach) / 1000).toFixed(2)}s after attach`);
    onLivePlaying();
  }, { once: true });
  livePlayer.attach(el);
}

// Re-point the shared connection at the selected stream. No-op when
// the URL is unchanged. On a real change (Viewer card click or late-
// arriving server config): stop() [which also forgets the render
// target], re-attach, then start() — the progress pill replays via
// onProgress('start').
function syncLiveStream() {
  if (!targetUrl.value || targetUrl.value === playingUrl) return;
  playingUrl = targetUrl.value;
  livePlayer.stop();
  attachLiveStream(activeVideoEl());
  livePlayer.start();
}

// Card clicks and late-arriving server config both funnel through
// targetUrl — a single watcher restarts the connection on any change.
watch(targetUrl, syncLiveStream);

/* ─── Livestream Viewer: fit the video into the adjustable right panel ─── */
// Policy: NEVER upscale past the stream's natural resolution; downscale to
// fit when the panel is smaller; always centered (flex stage). Panel size
// changes (divider drag / window resize) are tracked via ResizeObserver,
// stream size changes via the video element's own events. The fullscreen
// toggle (right sidebar) is the deliberate override: fill the whole page
// proportionally. It works on the Host subpage too (covers the HUD).
// Sound state is shared by the Host monitor and the Viewer (both play the
// same stream). Default muted: autoplay-friendly, and on the Host's own
// machine it avoids a mic -> stream -> speaker feedback loop. Resets to
// muted on every subpage switch (see teardownViewerStage).
const liveMuted = ref(true);
const liveFullscreen = ref(false);
let stageObserver = null;

function fitViewerVideo() {
  if (liveFullscreen.value) return; // CSS owns the size in fullscreen
  const el = viewerVideoEl.value;
  if (!el || !el.parentElement) return;
  const vw = el.videoWidth;
  const vh = el.videoHeight;
  if (!vw || !vh) return; // stream metadata not available yet
  const rect = el.parentElement.getBoundingClientRect();
  const scale = Math.min(rect.width / vw, rect.height / vh, 1); // cap at 1 = never upscale
  el.style.width = `${Math.floor(vw * scale)}px`;
  el.style.height = `${Math.floor(vh * scale)}px`;
}

function setupViewerStage() {
  teardownViewerStage();
  const el = viewerVideoEl.value;
  if (!el) return;
  el.addEventListener('loadedmetadata', fitViewerVideo);
  el.addEventListener('resize', fitViewerVideo); // intrinsic size changes
  stageObserver = new ResizeObserver(fitViewerVideo);
  stageObserver.observe(el.parentElement);
}

function teardownViewerStage() {
  if (stageObserver) {
    stageObserver.disconnect();
    stageObserver = null;
  }
  const el = viewerVideoEl.value;
  if (el) {
    el.removeEventListener('loadedmetadata', fitViewerVideo);
    el.removeEventListener('resize', fitViewerVideo);
  }
  document.removeEventListener('keydown', onLiveEsc);
  liveFullscreen.value = false; // switching subpages exits fullscreen
  liveMuted.value = true; // sound resets when the subpage is reopened
}

/* ─── Livestream sound: splash-style volume pill driving the app-wide setting ─── */
// The pill sits at the same bottom-right spot on BOTH subpages and always
// drives whichever <video> is currently on screen.
function activeVideoEl() {
  return activeSubpage.value === 'host' ? hostVideoEl.value : viewerVideoEl.value;
}

function applyLiveVolume() {
  const el = activeVideoEl();
  if (el) el.volume = settings.audioVolume;
}

// Slider interaction is a user gesture, so it is safe to unmute here.
function onLiveVolumeInput() {
  const el = activeVideoEl();
  if (el) {
    el.muted = false;
    applyLiveVolume();
  }
  liveMuted.value = false;
}

function toggleLiveMute() {
  const el = activeVideoEl();
  if (!el) return;
  el.muted = !el.muted;
  if (!el.muted) applyLiveVolume();
  liveMuted.value = el.muted;
}

/* ─── Fullscreen toggle (right sidebar, both subpages) ─── */
// Viewer: page-fill <-> raw size. Host: covers the HUD for a clean monitor.
// The docks stay clickable above the fullscreen video (z-index bump), and
// Esc exits as well.
function toggleLiveFullscreen() {
  liveFullscreen.value = !liveFullscreen.value;
}

function onLiveEsc(e) {
  if (e.key === 'Escape') liveFullscreen.value = false;
}

// Entering fullscreen lets CSS (object-fit: contain) size the video;
// leaving it restores the Viewer's raw-size fit.
watch(liveFullscreen, (fs) => {
  const el = viewerVideoEl.value;
  if (fs) {
    if (el) {
      el.style.width = '';
      el.style.height = '';
    }
    document.addEventListener('keydown', onLiveEsc);
  } else {
    document.removeEventListener('keydown', onLiveEsc);
    fitViewerVideo();
  }
  // Reflect the state on the dock button (highlight + tooltip swap).
  const item = rightItems.find((i) => i.id === 'fullscreen');
  if (item) {
    item.active = fs;
    item.titleKey = fs ? 'aerialview.exit_fullscreen' : 'aerialview.fullscreen';
  }
});

// Keep the video volume in sync with the app-wide Media setting.
watch(() => settings.audioVolume, applyLiveVolume);

// Render the shared stream on whichever subpage is on screen. The
// connection itself is NOT restarted — attach() is instant once live.
watch(activeSubpage, async (val) => {
  teardownViewerStage();
  await nextTick(); // wait for the target subpage's <video> to mount
  if (val === 'host') {
    attachLiveStream(hostVideoEl.value);
  } else if (val === 'viewer') {
    setupViewerStage();
    attachLiveStream(viewerVideoEl.value);
  }
  // NOTE: the stream itself is intentionally NOT re-synced here —
  // subpage switches never change the selection, only the render target.
});

onMounted(() => {
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
      onBeforeOpen: onPagesBeforeOpen,
    }),
  });
  registerLeft({
    id: 'subpage_viewer',
    icon: 'MENU_LIVESTREAM_VIEWER',
    titleKey: 'aerialview.subpage_livestream_viewer',
    active: activeSubpage.value === 'viewer',
    onClick: () => {
      activeSubpage.value = 'viewer';
    },
  });
  registerLeft({
    id: 'subpage_host',
    icon: 'MENU_REMOTE_CONTROLLER',
    titleKey: 'aerialview.subpage_livestream_host',
    active: activeSubpage.value === 'host',
    onClick: () => {
      activeSubpage.value = 'host';
    },
  });
  // NOTE: no 'camera' button here — the Crazyflie has no gimbal, so the
  // Gimbal disk and its toggle are deliberately absent on this page.

  // Invisible flex spacer: with .app-dock__inner at full height, the two
  // spacers absorb the free space above/below the button group so the
  // volume pill (registered last) sits at the VERY BOTTOM of the right
  // sidebar while the buttons keep their roughly centered look.
  // Emergency stop pinned to the VERY TOP of the right sidebar, above the
  // flex spacer that centers the other buttons. Never locked by subpage —
  // an emergency button must always be clickable.
  registerRight({
    id: 'estop',
    icon: 'MENU_RED_STOP',
    titleKey: 'aerialview.emergency_stop',
    danger: true,
    onClick: emergencyStop,
  });
  registerRight({ id: 'dock_spacer_top', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerRight({
    id: 'steer',
    icon: 'MENU_CONTROL_STICK',
    titleKey: 'aerialview.steer',
    active: showFlight.value,
    onClick: toggleFlight,
  });
  registerRight({
    id: 'takeoff',
    icon: 'MENU_TAKEOFF',
    titleKey: 'aerialview.takeoff',
    onClick: toggleTakeoff,
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
  registerRight({
    id: 'fullscreen',
    icon: 'MENU_WINDOW_SIZE',
    titleKey: 'aerialview.fullscreen',
    active: false,
    onClick: toggleLiveFullscreen,
  });
  registerRight({ id: 'dock_spacer_bottom', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerRight({
    id: 'volume',
    render: () =>
      h(VolumeDockButton, {
        muted: liveMuted.value,
        title: t('aerialview.volume'),
        onToggleMute: toggleLiveMute,
        onVolumeInput: onLiveVolumeInput,
      }),
  });

  // Sync dock button active states with toggle state
  watch(showFlight, (val) => {
    const item = rightItems.find((i) => i.id === 'steer');
    if (item) item.active = val;
  });
  // Keep the subpage selector buttons in sync with the active subpage.
  watch(activeSubpage, (val) => {
    const pairs = [
      ['subpage_viewer', 'viewer'],
      ['subpage_host', 'host'],
    ];
    for (const [id, sub] of pairs) {
      const btn = leftItems.find((i) => i.id === id);
      if (btn) btn.active = val === sub;
    }
    // Flight-control buttons are only clickable on the 'host' subpage.
    setControlsLocked(val !== 'host');
    // Yielding the Host subpage must never leave a stale velocity running.
    if (val !== 'host') stopRealFlight();
  });

  // Default subpage is 'host' — connect the livestream right away; the SAME
  // connection is re-attached to the Viewer's <video> on later switches.
  nextTick(() => {
    if (activeSubpage.value === 'host') attachLiveStream(hostVideoEl.value);
    playingUrl = targetUrl.value;
    livePlayer.start();
  });
});

onUnmounted(() => {
  onDividerPointerUp();
  stopRealFlight();
  stopRecorder(); // an active clip still downloads via the recorder's onstop
  clearTimeout(captureAuthTimer);
  if (moveKeepAlive) {
    clearInterval(moveKeepAlive);
    moveKeepAlive = null;
  }
  livePlayer.stop();
  teardownViewerStage();
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
    :class="{ 'live-fullscreen-active': liveFullscreen }"
    :left-items="leftItems"
    :right-items="rightItems"
    :show-flight="isAerialStyle && showFlight"
    :show-camera="false"
    :show-hud="isAerialStyle"
    :flight="flight"
    :real-telemetry="droneTelemetry"
    @flightMove="onRealFlightMove"
    @flightStop="onRealFlightStop"
    @flightModeChange="onFlightModeChange"
  >
    <template #background>
      <!-- Livestream Host subpage: fullscreen monitor of the currently
           selected stream (same shared connection as the Viewer).
           Muted so autoplay is allowed and to avoid audio feedback. -->
      <video
        v-if="activeSubpage === 'host'"
        ref="hostVideoEl"
        class="host-live"
        :class="{ 'host-live--fullscreen': liveFullscreen }"
        autoplay
        muted
        playsinline
      />

      <!-- Split-layout subpage (Livestream Viewer): two panels
           split by a vertical draggable divider; panel content comes later -->
      <div v-if="isSplitStyle" class="split-page">
        <!-- Left panel: stream catalog from /api/stream/config
             (testing-phase identities; will come from the FastAPI-users
             backend later). Clicking a card switches the right panel. -->
        <aside
          class="split-sidebar"
          :style="{ flexBasis: leftWidthPct + '%' }"
        >
          <div class="stream-list">
            <div
              v-for="s in streams"
              :key="s.id"
              class="stream-card"
              :class="{ 'stream-card--active': s.id === selectedStream?.id }"
              @click="selectedStreamId = s.id"
            >
              <div class="stream-card__head">
                <span class="stream-card__title">{{ s.hostname }}</span>
              </div>
              <p class="stream-card__desc">{{ s.description }}</p>
            </div>
          </div>
        </aside>

        <!-- Divider (draggable) -->
        <div
          class="split-divider"
          @pointerdown="onDividerPointerDown"
        />

        <!-- Right content area: the MediaMTX livestream, centered and
             never upscaled past its natural resolution -->
        <main class="split-content">
          <div class="viewer-stage">
            <video
              ref="viewerVideoEl"
              class="viewer-live"
              :class="{ 'viewer-live--fullscreen': liveFullscreen }"
              autoplay
              muted
              playsinline
            />
          </div>
        </main>
      </div>
    </template>

    <template #top-overlay>
      <!-- Login reminder for Screenshot / Recorder (same gate as the 3D pages) -->
      <div
        v-if="captureAuthNotice"
        class="top-center-message top-center-message--auth"
      >
        {{ t(`aerialview.auth_notice_${captureAuthNotice}`) }}
      </div>
      <!-- Green progress pill while the livestream connection is set up -->
      <div v-if="liveLoading" class="top-center-message asset-loading">
        <span>{{ t('aerialview.loading_livestream') }}</span>
        <div class="asset-loading__track">
          <div class="asset-loading__fill" :style="{ width: (liveProgress * 100).toFixed(1) + '%' }" />
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.split-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
  box-sizing: border-box;
  /* Clear the floating docks (72px wide; 56px below 768px, mirroring
     AppDock) — docked areas otherwise swallow clicks meant for the
     stream cards / stage (the white background still spans full width). */
  padding: 0 72px;
}

@media (max-width: 768px) {
  .split-page {
    padding: 0 56px;
  }
}

/* ─── Left panel ─── */
.split-sidebar {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #f5f5f7;
  overflow-y: auto;
}

/* ─── Stream list (left panel content) ─── */
.stream-list {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stream-card {
  background: #ffffff;
  border: 1px solid #e5e5ea;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  cursor: pointer;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.stream-card:hover {
  border-color: #007aff;
}

/* The card whose stream is playing in the right panel. */
.stream-card--active {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

.stream-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.stream-card__title {
  font-weight: 700;
  font-size: 0.95rem;
  color: #1c1c1e;
  word-break: break-all;
}

.stream-card__desc {
  margin: 6px 0 0;
  font-weight: 300;
  font-size: 0.8rem;
  color: #8e8e93;
  line-height: 1.4;
}

/* ─── Divider ─── */
.split-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.split-divider:hover,
.split-divider:active {
  background: #007aff;
}

/* ─── Right content area ─── */
.split-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  overflow: hidden;
}

/* ─── Livestream Host monitor ─── */
.host-live {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain; /* keep the webcam's 4:3 aspect, letterbox the rest */
  background: #000;
  pointer-events: none; /* docks / HUD stay interactive above the video */
}

/* ─── Livestream Viewer stage ─── */
.viewer-stage {
  flex: 1;
  min-height: 0;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.viewer-live {
  display: block; /* pixel width/height set by fitViewerVideo() */
}

/* Fullscreen: fill the whole page proportionally (like the Host subpage). */
.viewer-live--fullscreen {
  position: fixed;
  inset: 0;
  width: 100% !important;
  height: 100% !important;
  object-fit: contain;
  background: #000;
  z-index: 100;
}

/* Fullscreen Host monitor: cover the HUD for a clean monitoring view. */
.host-live--fullscreen {
  position: fixed;
  z-index: 100;
}

/* Keep both sidebars clickable above the fullscreen video (video z-index
   is 100; the docks are normally 10) so the toggle can switch back. */
.live-fullscreen-active :deep(.app-dock) {
  z-index: 101;
}

/* ─── Livestream connection progress pill (mirrors AerialView asset-loading) ─── */
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
}

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
</style>

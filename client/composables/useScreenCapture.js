import { ref } from 'vue';
import { DESCEND_THRESHOLD, ASCEND_THRESHOLD } from '@shared-composables/useAltitudeGate.js';
import { useTilesetSource } from '@shared-composables/useTilesetSource.js';

// Module-scope singleton state (same pattern as useDockRegistry) so that
// only one recorder session can be active app-wide at any time.
//
// The Screen Recording button is a 3-state flight-replay recorder:
//   idle -> recording: sample flight telemetry each frame while the user
//                       flies normally (no encoder running, controls stay
//                       fully responsive).
//   recording -> replaying: replay the sampled path on the 3D scene while
//                       capturing the VISIBLE asset into a video clip —
//                       Google 3D tiles above the switch altitude, Google
//                       Street View below it (mirroring the live view).
//   replaying -> idle: cancel discards the partial clip; reaching the end
//                       saves the clip and returns to idle automatically.
const recorderState = ref('idle'); // 'idle' | 'recording' | 'replaying'
const replayProgress = ref(0); // 0..1 during replay
// Replayed camera POV + asset-switch state, non-null only while replaying.
// AerialView binds StreetViewPane to this during replay so the on-screen
// replay switches between 3D tiles and Street View exactly like the live
// flight did; the canvas compositor reads the same values to pick layers.
const replayPov = ref(null); // { lat, lon, relativeAlt, headingRad, pitchRad, showStreetView, streetViewOpacity }

let samples = []; // { t, lat, lon, alt, heading, gimbalYaw, gimbalPitch, gimbalRoll, surfaceAlt }
let recordStartTs = 0;
let replayRafId = null;
let replayStartTs = 0;
let replayIndex = 0;

let mediaRecorder = null;
let recordedChunks = [];
let stream = null;
let mirrorCanvas = null;
let mirrorCtx = null;
let mirrorRafId = null;
let removePostRenderListener = null;
let streetViewBlocked = false; // latched when the Street View source proves unreadable
let tilesetSource = null; // lazily resolved useTilesetSource() handle (SV enable gate)
let svSourceCanvas = null; // Street View canvas currently piped through svVideo
let svStream = null; // captureStream of svSourceCanvas (snapshots presented frames)
let svVideo = null; // off-DOM video element used to sample the Street View stream
let svStarveSince = 0; // timestamp when the SV pipe first starved (0 = not starving)
let svStarveWarned = false; // one-shot log for the starvation fallback

// Downscale only when the window exceeds 1080p: the encoder's cost scales
// with pixels * fps, so capping resolution (plus a bitrate cap) keeps the
// replay true-to-speed even on integrated GPUs. Never upscale — a smaller
// window is recorded directly from the original canvas.
const RECORDING_MAX_WIDTH = 1920;
const RECORDING_FPS = 30;
const RECORDING_BITRATE = 6_000_000;
// Max time to drop frames while waiting for the Street View pipe's first
// presented frame. Longer starvation means the panorama failed to load —
// then Cesium is what is actually on screen, so record it instead of
// freezing the clip.
const SV_STARVE_FALLBACK_MS = 2000;

function getViewer() {
  const viewer = window.cesiumViewer;
  if (!viewer || typeof viewer.isDestroyed !== 'function' || viewer.isDestroyed()) {
    return null;
  }
  return viewer;
}

function timestamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function dataUrlToBlob(dataUrl) {
  const [header, base64] = dataUrl.split(',');
  const mime = /data:(.*?)(;|$)/.exec(header)?.[1] || 'image/png';
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mime });
}

function captureScreenshot() {
  const viewer = getViewer();
  if (!viewer || !viewer.canvas) {
    console.warn('[ScreenCapture] Cesium viewer is not ready; screenshot skipped.');
    return;
  }

  // Synchronous render keeps the WebGL drawing buffer valid for toDataURL,
  // so preserveDrawingBuffer is not required.
  viewer.render();
  const dataUrl = viewer.canvas.toDataURL('image/png');
  downloadBlob(dataUrlToBlob(dataUrl), `screenshot-${timestamp()}.png`);
}

// ---------------------------------------------------------------------------
// Telemetry recording (state: recording)
// ---------------------------------------------------------------------------

function startTelemetryCapture() {
  samples = [];
  recordStartTs = performance.now();
  recorderState.value = 'recording';
}

// Called from AerialView's rAF loop while state is 'recording'. surfaceAlt is
// the 3D-tileset surface height sampled beneath the drone: the aerial ->
// street view switch is driven by altitude RELATIVE to the surface, so the
// replay needs it to reproduce the same switch-over.
function sampleFrame(droneState, gimbalState, surfaceAlt = 0) {
  if (recorderState.value !== 'recording') return;
  samples.push({
    t: performance.now() - recordStartTs,
    lat: droneState.lat,
    lon: droneState.lon,
    alt: droneState.alt,
    heading: droneState.heading,
    gimbalYaw: gimbalState.yaw,
    gimbalPitch: gimbalState.pitch,
    gimbalRoll: gimbalState.roll,
    surfaceAlt,
  });
}

// ---------------------------------------------------------------------------
// Canvas capture (state: replaying) — composite canvas clamped to 1080p max
// ---------------------------------------------------------------------------

// Street View is only used on the Google-tiles (aerial) source; on the OSM
// Buildings (mesh) source the drone stays on 3D tiles down to the ground.
// Resolved lazily to keep module import order irrelevant.
function isStreetViewEnabled() {
  if (!tilesetSource) tilesetSource = useTilesetSource();
  return tilesetSource.activeSource.value !== 'osm';
}

// The Google StreetViewPanorama renders into a WebGL canvas injected inside
// StreetViewPane's container. Re-query every frame: the panorama is created
// asynchronously and may appear (or be recreated) mid-replay.
function findStreetViewCanvas() {
  const container = document.querySelector('.street-view-container');
  if (!container) return null;
  let best = null;
  for (const canvas of container.querySelectorAll('canvas')) {
    if (
      canvas.width > 0 &&
      canvas.height > 0 &&
      (!best || canvas.width * canvas.height > best.width * best.height)
    ) {
      best = canvas;
    }
  }
  return best;
}

// Google's panorama canvas is WebGL WITHOUT preserveDrawingBuffer, so
// drawImage from it outside its own render cycle reads a cleared buffer —
// that is why recording the canvas directly produced only the 3D tiles.
// Piping the canvas through captureStream + an off-DOM video element
// snapshots each PRESENTED frame instead, which works regardless of the
// drawing buffer. The pipe is rebuilt whenever the panorama's canvas element
// changes (Google can recreate it when the panorama re-initializes).
function getStreetViewVideo() {
  const canvas = findStreetViewCanvas();
  if (!canvas || typeof canvas.captureStream !== 'function') return null;
  if (canvas !== svSourceCanvas || !svVideo) {
    destroyStreetViewPipe();
    svSourceCanvas = canvas;
    svStream = canvas.captureStream(RECORDING_FPS);
    svVideo = document.createElement('video');
    svVideo.muted = true; // muted + playsInline: autoplay always allowed
    svVideo.playsInline = true;
    svVideo.srcObject = svStream;
    svVideo.play().catch(() => {});
  }
  return svVideo;
}

function destroyStreetViewPipe() {
  if (svVideo) {
    try {
      svVideo.pause();
    } catch {
      // Best-effort pause; cleanup continues regardless.
    }
    svVideo.srcObject = null;
    svVideo = null;
  }
  if (svStream) {
    svStream.getTracks().forEach((track) => track.stop());
    svStream = null;
  }
  svSourceCanvas = null;
}

// Draw one output frame: the Cesium canvas (Google 3D tiles) plus, when the
// replayed flight is in the ground phase, the Street View video blended with
// the same crossfade opacity the live view used.
function compositeFrame(cesiumCanvas) {
  const w = mirrorCanvas.width;
  const h = mirrorCanvas.height;

  // Decide whether Street View should be visible in this frame FIRST: while
  // it should be visible but its presented frame has not arrived yet, the
  // frame is SKIPPED entirely — no paint means captureStream emits no new
  // frame, so the clip holds the previous one (like a dropped frame) instead
  // of flashing the Cesium base layer the user is not seeing on screen.
  const pov = replayPov.value;
  const wantStreetView =
    !!pov && pov.showStreetView && pov.streetViewOpacity > 0 && !streetViewBlocked;
  let svVideo = null;
  if (wantStreetView) {
    svVideo = getStreetViewVideo();
    const svReady = svVideo && svVideo.readyState >= 2 && svVideo.videoWidth > 0;
    if (!svReady) {
      const now = performance.now();
      if (!svStarveSince) svStarveSince = now;
      if (now - svStarveSince < SV_STARVE_FALLBACK_MS) return; // drop the frame
      // Starved too long (e.g. the panorama failed to load and Cesium is
      // what is actually on screen): fall through and record the Cesium
      // layer rather than freeze the clip for the rest of the phase.
      if (!svStarveWarned) {
        svStarveWarned = true;
        console.warn('[ScreenCapture] Street View frames unavailable; recording the Cesium layer until they arrive.');
      }
    } else {
      svStarveSince = 0;
      svStarveWarned = false;
    }
  }

  // Layer 1: Cesium. Reading it here is valid because this runs from the
  // scene's postRender event, while the WebGL drawing buffer is still fresh
  // (the viewer is created without preserveDrawingBuffer).
  mirrorCtx.globalAlpha = 1;
  if (cesiumCanvas.width > 0 && cesiumCanvas.height > 0) {
    mirrorCtx.drawImage(cesiumCanvas, 0, 0, w, h);
  } else {
    mirrorCtx.fillStyle = '#000';
    mirrorCtx.fillRect(0, 0, w, h);
  }

  // Layer 2: Street View, blended with the live crossfade opacity.
  if (!wantStreetView || !svVideo) return;
  try {
    mirrorCtx.globalAlpha = Math.min(1, Math.max(0, pov.streetViewOpacity));
    mirrorCtx.drawImage(svVideo, 0, 0, w, h);
    mirrorCtx.globalAlpha = 1;
  } catch (err) {
    // An unreadable source must not kill the recording: latch the failure
    // and record the Cesium layer only for the rest of this capture.
    mirrorCtx.globalAlpha = 1;
    streetViewBlocked = true;
    console.warn('[ScreenCapture] Street View source is not readable; the recording falls back to 3D tiles only.', err);
  }
}

function startCanvasCapture() {
  const viewer = getViewer();
  if (!viewer || !viewer.canvas || typeof viewer.canvas.captureStream !== 'function') {
    console.warn('[ScreenCapture] Cesium viewer is not ready; capture not started.');
    return false;
  }

  try {
    const source = viewer.canvas;

    // Always composite into a 2D mirror canvas — never record a WebGL canvas
    // directly: during replay the visible asset switches between the Cesium
    // canvas (Google 3D tiles) and the Street View canvas (ground imagery),
    // and only a composite can blend both during the crossfade. Downscale
    // only when the window exceeds 1080p (never upscale); even dimensions
    // for codec compatibility.
    const scale = Math.min(1, RECORDING_MAX_WIDTH / source.width);
    mirrorCanvas = document.createElement('canvas');
    mirrorCanvas.width = Math.max(2, Math.round(source.width * scale) & ~1);
    mirrorCanvas.height = Math.max(2, Math.round(source.height * scale) & ~1);
    mirrorCtx = mirrorCanvas.getContext('2d');
    streetViewBlocked = false;
    svStarveSince = 0;
    svStarveWarned = false;

    const mirrorFrame = () => {
      if (!mirrorCtx) return;
      compositeFrame(source);
    };
    mirrorFrame();
    // postRender fires synchronously after Cesium renders, while the WebGL
    // buffer is still valid to sample.
    if (viewer.scene && viewer.scene.postRender) {
      removePostRenderListener = viewer.scene.postRender.addEventListener(mirrorFrame);
    } else {
      const pump = () => {
        mirrorFrame();
        mirrorRafId = requestAnimationFrame(pump);
      };
      mirrorRafId = requestAnimationFrame(pump);
    }

    stream = mirrorCanvas.captureStream(RECORDING_FPS);
    const mimeType = MediaRecorder.isTypeSupported('video/mp4') ? 'video/mp4' : 'video/webm';
    mediaRecorder = new MediaRecorder(stream, {
      mimeType,
      videoBitsPerSecond: RECORDING_BITRATE,
    });
    recordedChunks = [];

    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data);
      }
    };

    mediaRecorder.start(1000);
    return true;
  } catch (err) {
    console.error('[ScreenCapture] Failed to start capture:', err);
    cleanupCapture();
    return false;
  }
}

function stopCanvasCapture(save) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      cleanupCapture();
      resolve();
    };

    if (!mediaRecorder || mediaRecorder.state === 'inactive') {
      finish();
      return;
    }

    const recorder = mediaRecorder;
    // Watchdog: a missing onstop event must never leave the state machine
    // stuck in 'replaying'.
    const watchdog = setTimeout(() => {
      console.warn('[ScreenCapture] MediaRecorder onstop watchdog fired.');
      finish();
    }, 1500);

    recorder.onstop = () => {
      clearTimeout(watchdog);
      const mime = recorder.mimeType || 'video/webm';
      if (save && recordedChunks.length > 0) {
        const ext = mime.includes('mp4') ? 'mp4' : 'webm';
        downloadBlob(new Blob(recordedChunks, { type: mime }), `recording-${timestamp()}.${ext}`);
      }
      finish();
    };

    try {
      recorder.stop();
    } catch (err) {
      clearTimeout(watchdog);
      console.error('[ScreenCapture] MediaRecorder stop failed:', err);
      finish();
    }
  });
}

function cleanupCapture() {
  if (typeof removePostRenderListener === 'function') {
    removePostRenderListener();
    removePostRenderListener = null;
  }
  if (mirrorRafId) {
    cancelAnimationFrame(mirrorRafId);
    mirrorRafId = null;
  }
  mirrorCtx = null;
  mirrorCanvas = null;
  destroyStreetViewPipe();
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  mediaRecorder = null;
  recordedChunks = [];
}

// ---------------------------------------------------------------------------
// Replay (state: replaying)
// ---------------------------------------------------------------------------

function lerp(a, b, f) {
  return a + (b - a) * f;
}

// Shortest-path interpolation for angles in degrees.
function lerpAngle(a, b, f) {
  let d = (b - a) % 360;
  if (d > 180) d -= 360;
  if (d < -180) d += 360;
  return a + d * f;
}

function applyReplaySample(s) {
  if (typeof window.updateCesiumCamera !== 'function') return;
  // Skip corrupt samples instead of letting Cesium throw on bad input.
  const values = [s.lat, s.lon, s.alt, s.heading, s.gimbalYaw, s.gimbalPitch, s.gimbalRoll];
  if (!values.every(Number.isFinite)) return;
  window.updateCesiumCamera({
    lat: s.lat,
    lon: s.lon,
    alt: s.alt,
    heading: s.heading,
    gimbalYaw: s.gimbalYaw,
    gimbalPitch: s.gimbalPitch,
    gimbalRoll: s.gimbalRoll,
  });

  // Publish the replayed POV together with the aerial/street-view switch
  // state, computed exactly like the live flight does from altitude relative
  // to the sampled surface (same thresholds, same crossfade curve).
  const relativeAlt = Math.max(0, s.alt - (Number.isFinite(s.surfaceAlt) ? s.surfaceAlt : 0));
  const svEnabled = isStreetViewEnabled();
  let streetViewOpacity = 0;
  if (svEnabled) {
    if (relativeAlt <= DESCEND_THRESHOLD) streetViewOpacity = 1;
    else if (relativeAlt < ASCEND_THRESHOLD) {
      streetViewOpacity = 1 - (relativeAlt - DESCEND_THRESHOLD) / (ASCEND_THRESHOLD - DESCEND_THRESHOLD);
    }
  }
  replayPov.value = {
    lat: s.lat,
    lon: s.lon,
    relativeAlt,
    headingRad: ((s.heading + s.gimbalYaw) * Math.PI) / 180,
    pitchRad: (s.gimbalPitch * Math.PI) / 180,
    showStreetView: svEnabled && relativeAlt < ASCEND_THRESHOLD,
    streetViewOpacity,
  };
}

function runReplayLoop() {
  // A failure here must never leave the recorder stuck in 'replaying':
  // AerialView skips flight physics and camera sync in that state, so a
  // stuck replay would freeze the scene and disable the Flight/Gimbal disks.
  try {
    const lastSample = samples[samples.length - 1];
    const elapsed = performance.now() - replayStartTs;

    if (elapsed >= lastSample.t) {
      replayRafId = null;
      applyReplaySample(lastSample);
      replayProgress.value = 1;
      finishReplay();
      return;
    }

    // Advance the sample cursor, then interpolate between the two samples
    // bracketing the elapsed time so replay is smooth at 1x real time.
    while (replayIndex < samples.length - 2 && samples[replayIndex + 1].t <= elapsed) {
      replayIndex += 1;
    }
    const a = samples[replayIndex];
    const b = samples[replayIndex + 1];
    const span = Math.max(1, b.t - a.t);
    const f = Math.min(1, Math.max(0, (elapsed - a.t) / span));

    applyReplaySample({
      lat: lerp(a.lat, b.lat, f),
      lon: lerp(a.lon, b.lon, f),
      alt: lerp(a.alt, b.alt, f),
      heading: lerpAngle(a.heading, b.heading, f),
      gimbalYaw: lerpAngle(a.gimbalYaw, b.gimbalYaw, f),
      gimbalPitch: lerp(a.gimbalPitch, b.gimbalPitch, f),
      gimbalRoll: lerp(a.gimbalRoll, b.gimbalRoll, f),
      surfaceAlt: lerp(a.surfaceAlt ?? 0, b.surfaceAlt ?? 0, f),
    });

    replayProgress.value = elapsed / lastSample.t;
    replayRafId = requestAnimationFrame(runReplayLoop);
  } catch (err) {
    console.error('[ScreenCapture] Replay aborted after an error:', err);
    replayRafId = null;
    cancelReplay();
  }
}

async function stopAndReplay() {
  if (recorderState.value !== 'recording') return;

  if (samples.length < 2) {
    // Nothing meaningful recorded — quietly return to idle.
    samples = [];
    recorderState.value = 'idle';
    return;
  }

  recorderState.value = 'replaying';
  replayProgress.value = 0;

  if (!startCanvasCapture()) {
    samples = [];
    recorderState.value = 'idle';
    return;
  }

  replayStartTs = performance.now();
  replayIndex = 0;
  replayRafId = requestAnimationFrame(runReplayLoop);
}

async function finishReplay() {
  await stopCanvasCapture(true); // save the completed clip
  samples = [];
  replayPov.value = null;
  recorderState.value = 'idle';
  replayProgress.value = 0;
}

async function cancelReplay() {
  if (recorderState.value !== 'replaying') return;
  if (replayRafId) {
    cancelAnimationFrame(replayRafId);
    replayRafId = null;
  }
  await stopCanvasCapture(false); // discard the partial clip
  samples = [];
  replayPov.value = null;
  recorderState.value = 'idle';
  replayProgress.value = 0;
}

function toggleRecorder() {
  if (recorderState.value === 'idle') {
    startTelemetryCapture();
  } else if (recorderState.value === 'recording') {
    stopAndReplay();
  } else {
    cancelReplay();
  }
}

// Abort whatever is active and discard everything (view unmount).
function resetRecorder() {
  if (replayRafId) {
    cancelAnimationFrame(replayRafId);
    replayRafId = null;
  }
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try {
      mediaRecorder.stop();
    } catch {
      // Best-effort stop; cleanup continues regardless.
    }
  }
  cleanupCapture();
  samples = [];
  replayPov.value = null;
  recorderState.value = 'idle';
  replayProgress.value = 0;
}

export function useScreenCapture() {
  return {
    recorderState,
    replayProgress,
    replayPov,
    captureScreenshot,
    sampleFrame,
    toggleRecorder,
    cancelReplay,
    resetRecorder,
  };
}

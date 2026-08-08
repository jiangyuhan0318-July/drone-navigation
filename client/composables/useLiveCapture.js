import { computed, ref } from 'vue';

/**
 * Screenshot + screen recording for the REAL drone's live <video> element
 * (a WHEP WebRTC MediaStream). Sibling of useScreenCapture.js — same UX and
 * file-naming, but where that one captures the 3D Cesium canvas (and records
 * telemetry for replay), this one captures plain live video:
 *
 *   Screenshot: current video frame -> canvas -> PNG download
 *   Recorder:   MediaRecorder on video.srcObject -> .webm download
 *
 * The MediaStream is WebRTC-backed, not a cross-origin media file, so the
 * canvas is never tainted and no CORS handling is needed. Both actions are
 * no-ops (with a console warning + false return) while the stream has not
 * delivered a frame yet, so a click can never produce an empty file.
 */

// Module-level state: the capture is a singleton, like the player itself.
const recorderState = ref('idle'); // 'idle' | 'recording'
const isRecorderActive = computed(() => recorderState.value !== 'idle');

let mediaRecorder = null;
let chunks = [];
let detachTrackGuards = null;

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

/** Draw the video's current frame into a canvas and download it as PNG. */
function captureScreenshot(videoEl) {
  if (!videoEl || !videoEl.videoWidth || !videoEl.videoHeight) {
    console.warn('[LiveCapture] No video frame yet; screenshot skipped.');
    return false;
  }
  const canvas = document.createElement('canvas');
  canvas.width = videoEl.videoWidth;
  canvas.height = videoEl.videoHeight;
  canvas.getContext('2d').drawImage(videoEl, 0, 0);
  canvas.toBlob((blob) => {
    if (blob) downloadBlob(blob, `screenshot-${timestamp()}.png`);
  }, 'image/png');
  return true;
}

// Prefer VP9, fall back to whatever the browser's MediaRecorder offers.
function pickMimeType() {
  const candidates = [
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm',
  ];
  return candidates.find((m) => MediaRecorder.isTypeSupported(m)) || '';
}

/** Stop an active recording (idempotent); the download fires in onstop. */
function stopRecorder() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    try { mediaRecorder.stop(); } catch { /* already stopping */ }
  }
}

/**
 * Toggle recording on the video element's live MediaStream.
 * Start: returns false when no stream is attached yet. Stop: always allowed,
 * never traps an active recording behind any caller-side gate.
 */
function toggleRecorder(videoEl) {
  if (recorderState.value === 'recording') {
    stopRecorder();
    return true;
  }
  const stream = videoEl?.srcObject;
  if (!(stream instanceof MediaStream) || !stream.getVideoTracks().length) {
    console.warn('[LiveCapture] No live stream on the video element; recording skipped.');
    return false;
  }

  chunks = [];
  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  mediaRecorder = recorder;

  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  recorder.onstop = () => {
    const type = recorder.mimeType || 'video/webm';
    if (chunks.length) {
      downloadBlob(new Blob(chunks, { type }), `recording-${timestamp()}.webm`);
    }
    chunks = [];
    if (detachTrackGuards) detachTrackGuards();
    if (mediaRecorder === recorder) mediaRecorder = null;
    recorderState.value = 'idle';
  };

  // A WHEP re-handshake (stream switch, reconnect, page teardown) ENDS the
  // tracks — stop cleanly instead of hanging in 'recording' forever.
  const onTrackEnded = () => stopRecorder();
  for (const track of stream.getTracks()) {
    track.addEventListener('ended', onTrackEnded);
  }
  detachTrackGuards = () => {
    for (const track of stream.getTracks()) {
      track.removeEventListener('ended', onTrackEnded);
    }
    detachTrackGuards = null;
  };

  recorderState.value = 'recording';
  // 1 s timeslice: data trickles in, so an abrupt tab close loses at most
  // the last second instead of the whole clip.
  recorder.start(1000);
  return true;
}

export function useLiveCapture() {
  return {
    recorderState,
    isRecorderActive,
    captureScreenshot,
    toggleRecorder,
    stopRecorder,
  };
}

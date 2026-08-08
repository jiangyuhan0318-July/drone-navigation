// Shared WHEP (WebRTC-HTTP Egress Protocol) player for MediaMTX livestreams.
// Used by the Real Drone 'Livestream Host' (self-monitor) and
// 'Livestream Viewer' (watch a broadcast) subpages.
//
// One player instance owns ONE PeerConnection. Its merged MediaStream can be
// attached to ANY <video> element at any time via attach(el) — so switching
// between subpages re-attaches the already-live stream instead of doing the
// WHEP handshake again. Stop only when leaving the page for good.
//
// Usage:
//   const player = createWhepPlayer({ url, logTag: 'live', onProgress });
//   `url` may be a string or a zero-arg getter (resolved at every start /
//   retry, so late-arriving runtime config still takes effect).
//   player.start();            // POSTs the SDP offer, retries on failure
//   player.attach(videoEl);    // render the stream on this element
//   player.attach(otherEl);    // re-render elsewhere (instant, no handshake)
//   player.stop();             // closes the PeerConnection, stops tracks
//
// onProgress(phase) fires with: 'start' | 'offer' | 'handshake' | 'track'.
//
// NOTE: aiortc publishers send video and audio as SEPARATE streams (one per
// track), so tracks are merged into one persistent MediaStream before being
// attached to a <video> element — assigning event.streams[0] directly would
// let the audio stream overwrite the video stream (black screen).
//
// NOTE: the attach()ed render target SURVIVES start()/retry restarts —
// cleanup() must only drop the dead stream from the element, never forget
// the element itself. (Forgetting it once caused a black screen: ontrack
// then had no element to render into until the next subpage switch.)

export function createWhepPlayer({
  url,
  logTag = 'whep',
  retryMs = 5000,
  onProgress = null,
  // No STUN by default: MediaMTX is an ICE-lite server, so host candidates
  // suffice (the client initiates the connectivity checks) — exactly like
  // MediaMTX's own web player. An unreachable STUN server otherwise stalls
  // ICE gathering for tens of seconds on UDP-blackholing networks.
  iceServers = [],
  // Belt & braces: never let ICE gathering hang the handshake.
  iceGatheringTimeoutMs = 3000,
}) {
  let pc = null;
  let mediaStream = null;
  let retryTimer = null;
  let active = false;
  let attachedEl = null;
  let attempt = 0; // handshake attempt counter (reset by stop())

  // String or getter — resolved at each start()/retry attempt.
  const resolveUrl = () => (typeof url === 'function' ? url() : url);

  function log(...args) {
    console.log(`[${logTag}]`, ...args);
  }

  function warn(...args) {
    console.warn(`[${logTag}]`, ...args);
  }

  function report(phase) {
    if (onProgress) {
      try {
        onProgress(phase);
      } catch {
        /* progress callbacks must never break playback */
      }
    }
  }

  // MediaMTX accepts a full (non-trickle) SDP offer, so wait for ICE
  // gathering — but cap the wait so a dead STUN server cannot stall the
  // handshake. Resolves true when the timeout fired (gathering cut short).
  function waitIceGatheringComplete(conn) {
    if (conn.iceGatheringState === 'complete') return Promise.resolve(false);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        conn.removeEventListener('icegatheringstatechange', onState);
        resolve(true);
      }, iceGatheringTimeoutMs);
      const onState = () => {
        if (conn.iceGatheringState === 'complete') {
          clearTimeout(timer);
          conn.removeEventListener('icegatheringstatechange', onState);
          resolve(false);
        }
      };
      conn.addEventListener('icegatheringstatechange', onState);
    });
  }

  /** Render the (possibly still connecting) stream on this <video> element. */
  function attach(el) {
    attachedEl = el;
    if (!el || !mediaStream || !mediaStream.getTracks().length) return;
    if (el.srcObject !== mediaStream) {
      el.srcObject = mediaStream;
      el.play().catch(() => {}); // no-op while muted-autoplay already runs
    }
  }

  /** Stop rendering on the current element; the connection stays alive. */
  function detach() {
    if (attachedEl) attachedEl.srcObject = null;
    attachedEl = null;
  }

  /** True once at least one track has arrived (stream is renderable). */
  function hasTracks() {
    return !!mediaStream && mediaStream.getTracks().length > 0;
  }

  function cleanup() {
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    // The render target SURVIVES a restart — only drop the dead stream from
    // the element; keep attachedEl so the next attempt renders into it.
    if (attachedEl) attachedEl.srcObject = null;
    if (pc) {
      pc.close();
      pc = null;
    }
    if (mediaStream) {
      for (const track of mediaStream.getTracks()) track.stop();
      mediaStream = null;
    }
  }

  function scheduleRetry() {
    if (retryTimer || !active) return; // never retry after stop()
    log(`retry scheduled in ${retryMs / 1000}s (next attempt #${attempt + 1})`);
    retryTimer = setTimeout(() => {
      retryTimer = null;
      start();
    }, retryMs);
  }

  async function start() {
    active = true;
    cleanup();
    report('start');
    attempt += 1;
    // All milestones are timestamped relative to this t0 so slow phases are
    // visible at a glance (compare with MediaMTX's built-in page).
    const t0 = performance.now();
    const since = () => `t+${((performance.now() - t0) / 1000).toFixed(2)}s`;
    log(`${since()} START attempt #${attempt} — ICE servers: ${iceServers.length ? iceServers.map((s) => s.urls).join(', ') : 'none (host candidates only)'}`);
    const conn = new RTCPeerConnection({ iceServers });
    pc = conn;
    conn.addTransceiver('video', { direction: 'recvonly' });
    conn.addTransceiver('audio', { direction: 'recvonly' });
    const stream = new MediaStream();
    mediaStream = stream;
    // Diagnostic: count gathered ICE candidates per type. If the STUN lookup
    // (srflx) is slow or blocked, ICE gathering dominates the startup time.
    const candidateCounts = {};
    conn.onicecandidate = (event) => {
      if (event.candidate) {
        const type = event.candidate.type || 'unknown';
        candidateCounts[type] = (candidateCounts[type] || 0) + 1;
      }
    };
    conn.ontrack = (event) => {
      log(`${since()} incoming track: ${event.track.kind}`);
      stream.addTrack(event.track);
      report('track');
      const el = attachedEl;
      if (el && el.srcObject !== stream) {
        el.srcObject = stream;
        el.play().catch(() => {});
      }
    };
    conn.oniceconnectionstatechange = () => {
      log(`${since()} ICE connection state -> ${conn.iceConnectionState}`);
      if (conn.iceConnectionState === 'failed' && pc === conn) scheduleRetry();
    };
    conn.onconnectionstatechange = () => {
      log(`${since()} connection state -> ${conn.connectionState}`);
    };
    try {
      const tOffer = performance.now();
      const offer = await conn.createOffer();
      await conn.setLocalDescription(offer);
      log(`${since()} local SDP offer set (createOffer took ${((performance.now() - tOffer) / 1000).toFixed(2)}s)`);
      const tIce = performance.now();
      const iceTimedOut = await waitIceGatheringComplete(conn);
      const candSummary = Object.entries(candidateCounts)
        .map(([type, count]) => `${type}=${count}`)
        .join(' ') || 'none';
      if (iceTimedOut) {
        log(`${since()} ICE gathering TIMEOUT after ${(iceGatheringTimeoutMs / 1000).toFixed(1)}s — proceeding with gathered candidates (${candSummary})`);
      } else {
        log(`${since()} ICE gathering COMPLETE (took ${((performance.now() - tIce) / 1000).toFixed(2)}s; candidates: ${candSummary})`);
      }
      log(`${since()} POSTing WHEP SDP offer to ${resolveUrl()} ...`);
      report('offer');
      const tFetch = performance.now();
      const res = await fetch(resolveUrl(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: conn.localDescription.sdp,
      });
      log(`${since()} WHEP response HTTP ${res.status} (TTFB ${((performance.now() - tFetch) / 1000).toFixed(2)}s)`);
      if (!res.ok) {
        const body = (await res.text()).slice(0, 200);
        throw new Error(`HTTP ${res.status}: ${body}`);
      }
      const answerSdp = await res.text();
      await conn.setRemoteDescription({ type: 'answer', sdp: answerSdp });
      log(`${since()} WHEP handshake SUCCEEDED — remote SDP answer applied.`);
      report('handshake');
    } catch (err) {
      warn(`${since()} WHEP handshake FAILED:`, err.message);
      if (pc === conn) scheduleRetry(); // no retry if stop() was called meanwhile
    }
  }

  function stop() {
    active = false;
    attempt = 0;
    log('STOP — PeerConnection closed.');
    detach(); // final teardown also forgets the render target
    cleanup();
  }

  return { start, stop, attach, detach, hasTracks };
}

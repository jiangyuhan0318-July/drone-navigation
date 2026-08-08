/**
 * Splash Screen Video Sequencer
 *
 * Plays sequential video clips from /splash/ while Cesium 3D tiles load.
 * Uses dual-video cross-fade to eliminate black screen between clips.
 * Dismissal is driven by tile readiness, checked every 500 ms:
 *   - When tiles become ready → fade out splash immediately (even mid-clip)
 *   - When a clip ends AND tiles NOT ready → play next clip (loop last)
 *   - Timeout fallback after 60 seconds regardless
 *
 * This is a plain script (not a Vue module) so it executes immediately,
 * before Vue or Cesium JS has finished loading.
 */

(async function () {
  'use strict';

  // ── Splash media config ──
  // The first clip is always played. Remaining clips are shuffled and played
  // without repetition; once all have played, a new shuffle begins.
  const FALLBACK_FIRST_CLIP = '/splash/video_00.mp4';
  const FALLBACK_OTHER_CLIPS = [
    '/splash/vantor_world3d.mp4',
    '/splash/kevtoe_worldview.mp4',
    '/splash/palantir_maven.mp4',
  ];
  let FIRST_CLIP = FALLBACK_FIRST_CLIP;
  let OTHER_CLIPS = FALLBACK_OTHER_CLIPS;
  const MUSIC_URL = '/splash/background_music_00.mp3';
  const SETTINGS_KEY = 'app-settings';
  // Maximum time (ms) a single splash clip is allowed to play before forcing
  // a transition to the next clip. Some source clips are very long (100s),
  // which makes the splash feel stuck.
  const MAX_CLIP_DURATION_MS = 15000;

  function loadAudioVolume() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        const vol = Number(parsed.audioVolume);
        if (!isNaN(vol)) return Math.max(0, Math.min(1, vol));
      }
    } catch {
      // ignore
    }
    return 0.9;
  }

  function saveAudioVolume(vol) {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      parsed.audioVolume = Math.max(0, Math.min(1, vol));
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(parsed));
    } catch {
      // ignore
    }
  }

  function shuffleArray(arr) {
    const copy = arr.slice();
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  function buildPlaylist() {
    return [FIRST_CLIP, ...shuffleArray(OTHER_CLIPS)];
  }

  /**
   * Fetch the auto-generated splash playlist manifest. Falls back to the
   * hardcoded defaults if the fetch fails (e.g., dev mode without running
   * the manifest script). This allows renaming or adding videos without
   * touching the code.
   */
  async function loadPlaylistManifest() {
    try {
      const res = await fetch('/splash/playlist.json', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.firstClip && Array.isArray(data.otherClips)) {
        FIRST_CLIP = data.firstClip;
        OTHER_CLIPS = data.otherClips;
        console.log(`[splash] loaded ${OTHER_CLIPS.length + 1} clips from playlist.json`);
      }
    } catch (e) {
      console.warn('[splash] playlist.json fetch failed, using fallback defaults:', e.message);
    }
  }

  await loadPlaylistManifest();
  let playlist = buildPlaylist();
  let currentClip = 0;

  /** Extract the bare file name from a clip URL, for logging. */
  function clipName(url) {
    return String(url).split('/').pop();
  }

  /**
   * Start a fresh playback cycle after the last clip of the current playlist
   * has finished. Rebuilds the shuffled playlist and guarantees the first
   * clip of the new cycle is NOT the same as the clip that just ended —
   * otherwise that clip would play twice in a row across the cycle boundary
   * (the "repeated video" bug).
   */
  function startNewCycle() {
    const justEnded = playlist[currentClip];
    playlist = buildPlaylist();
    // playlist[0] is FIRST_CLIP (skipped — it already played at startup), so
    // the first clip of the new cycle is playlist[1]. If the shuffle happened
    // to put the just-ended clip there again, swap it with a later clip that
    // differs so the same video never plays back-to-back.
    if (playlist.length > 2 && playlist[1] === justEnded) {
      for (let i = 2; i < playlist.length; i++) {
        if (playlist[i] !== justEnded) {
          const tmp = playlist[1];
          playlist[1] = playlist[i];
          playlist[i] = tmp;
          break;
        }
      }
    }
    currentClip = 1; // Skip FIRST_CLIP; it already played
    preloadNext(currentClip);
    crossFadeToNext();
  }

  // ── i18n translations (customizable, not standard translations) ──
  // Each language has its own custom slogan text.
  // In the future, this can be fetched from an API or config file.
  const i18n = {
    en: {
      slogan: 'The world is wide, let us take off.',
    },
    zh: {
      slogan: '世界很大，我们飞过去看看',
    },
  };

  // ── Detect user language ──
  function detectLanguage() {
    // 1. Check localStorage (set by Settings page)
    const saved = localStorage.getItem('user-lang');
    if (saved && i18n[saved]) return saved;
    // 2. Check browser language
    const browserLang = (navigator.language || 'en').slice(0, 2);
    if (i18n[browserLang]) return browserLang;
    // 3. Default to English
    return 'en';
  }

  const lang = detectLanguage();

  // ── Populate slogan ──
  const sloganEl = document.getElementById('splash-slogan');
  if (sloganEl) {
    sloganEl.textContent = i18n[lang].slogan;
  }

  // ── State ──
  let dismissed = false;
  let tilesReady = false;
  let cesiumReadyFlag = false;
  let googleReadyFlag = false;
  let connectionErrorText = '';
  let firstClipEnded = false;

  // ── Dual-video setup for seamless cross-fade ──
  // Two video elements: one visible (playing), one hidden (buffering next clip).
  const videoA = document.getElementById('splash-video');
  const overlay = document.getElementById('splash-overlay');
  if (!videoA || !overlay) return;

  // ── Connection error overlay ──
  // Centered red banner similar to the collision warning style.
  const connectionErrorEl = document.createElement('div');
  connectionErrorEl.className = 'splash-connection-error';
  connectionErrorEl.style.display = 'none';
  overlay.appendChild(connectionErrorEl);

  function updateConnectionError() {
    if (connectionErrorText) {
      connectionErrorEl.innerHTML = '<span class="splash-connection-error__icon">⚠</span>' +
        '<span class="splash-connection-error__text">' + connectionErrorText + '</span>';
      connectionErrorEl.style.display = 'inline-flex';
    } else {
      connectionErrorEl.style.display = 'none';
    }
  }

  function setConnectionError(text) {
    connectionErrorText = text;
    updateConnectionError();
  }

  // Create a second video element for cross-fade transitions
  const videoB = document.createElement('video');
  videoB.muted = true;
  videoB.playsInline = true;
  videoB.preload = 'auto';
  videoB.style.cssText = videoA.style.cssText;
  // Match the positioning of videoA
  videoB.className = 'splash-video-alt';
  videoB.style.opacity = '0'; // Start hidden
  overlay.insertBefore(videoB, videoA.nextSibling);

  // Track which video is currently playing
  let activeVideo = videoA;
  let standbyVideo = videoB;
  let clipTimer = null;

  function clearClipTimer() {
    if (clipTimer) {
      clearTimeout(clipTimer);
      clipTimer = null;
    }
  }

  function startClipTimer() {
    clearClipTimer();
    clipTimer = setTimeout(() => {
      if (dismissed) return;
      // Simulate a natural clip end: remove listeners, advance, and cross-fade.
      detachActiveListeners(activeVideo);
      if (tilesReady) {
        dismissSplash();
      } else if (currentClip < playlist.length - 1) {
        currentClip++;
        crossFadeToNext();
      } else {
        startNewCycle();
      }
    }, MAX_CLIP_DURATION_MS);
  }

  // ── Background music (loops continuously) ──
  const bgMusic = new Audio(MUSIC_URL);
  bgMusic.loop = true;
  const initialVolume = loadAudioVolume();
  bgMusic.volume = initialVolume;
  bgMusic.play().catch(() => {
    // Browsers may block autoplay until user interaction.
    // The music will start once the user clicks or taps anywhere.
    const startMusic = () => {
      bgMusic.play().catch(() => {});
      document.removeEventListener('click', startMusic);
      document.removeEventListener('touchstart', startMusic);
    };
    document.addEventListener('click', startMusic);
    document.addEventListener('touchstart', startMusic);
  });

  // ── Volume slider ──
  const volumeSlider = document.getElementById('splash-volume-slider');
  if (volumeSlider) {
    volumeSlider.value = Math.round(initialVolume * 100);
    volumeSlider.addEventListener('input', (e) => {
      const vol = Math.max(0, Math.min(1, Number(e.target.value) / 100));
      bgMusic.volume = vol;
      saveAudioVolume(vol);
    });
    // Interacting with the slider also satisfies the browser's autoplay gesture
    // requirement, so start playback if it was blocked.
    const unlockAudio = () => {
      if (bgMusic.paused) {
        bgMusic.play().catch(() => {});
      }
    };
    volumeSlider.addEventListener('click', unlockAudio);
    volumeSlider.addEventListener('touchstart', unlockAudio);
  }

  /**
   * Fade out background music over the given duration (ms).
   */
  function fadeOutMusic(duration = 2000) {
    const startVolume = bgMusic.volume || loadAudioVolume();
    const startTime = performance.now();
    function step(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      bgMusic.volume = Math.max(0, startVolume * (1 - progress));
      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        bgMusic.pause();
        bgMusic.currentTime = 0;
      }
    }
    requestAnimationFrame(step);
  }

  /**
   * Preload the next clip into the standby video element.
   * This starts buffering so the switch is instant.
   */
  function preloadNext(clipIndex) {
    if (clipIndex < playlist.length) {
      const clipUrl = playlist[clipIndex];
      // Fully reset the standby element before loading the next clip,
      // so any stale ended/seek state from the previous clip is cleared.
      standbyVideo.pause();
      standbyVideo.removeAttribute('src');
      standbyVideo.load();
      standbyVideo.src = clipUrl;
      standbyVideo.load();
      standbyVideo.addEventListener(
        'loadedmetadata',
        function onMeta() {
          standbyVideo.currentTime = 0;
          standbyVideo.removeEventListener('loadedmetadata', onMeta);
        },
        { once: true }
      );
      // Permanent log: report when this clip has buffered enough to be shown
      // without stalling ("downloaded & cached, ready to display"). The src
      // guard ignores stale events from a preload that has been superseded.
      standbyVideo.addEventListener(
        'canplay',
        function onCanPlay() {
          standbyVideo.removeEventListener('canplay', onCanPlay);
          if (standbyVideo.src.indexOf(clipUrl) !== -1) {
            console.log('[splash] Cached & ready to display: ' + clipName(clipUrl));
          }
        },
        { once: true }
      );
      standbyVideo.addEventListener(
        'error',
        function onErr(e) {
          console.error('[splash] preload error for', clipUrl, e);
          standbyVideo.removeEventListener('error', onErr);
        },
        { once: true }
      );
    }
  }

  // ── Start the first clip and preload the second ──
  // Wait for 'canplay' before pressing play: on a slow link, calling play()
  // with only a frame or two of buffer stalls the video almost immediately
  // (the "choked splash" symptom). The clips are stream-encoded (~1.5 Mbps,
  // faststart), so 'canplay' fires after roughly a second of buffering.
  videoA.src = playlist[0];
  console.log('[splash] Now playing: ' + clipName(playlist[0]));
  videoA.addEventListener(
    'canplay',
    function onFirstCanPlay() {
      videoA.removeEventListener('canplay', onFirstCanPlay);
      videoA.play().catch(() => {});
    },
    { once: true }
  );
  preloadNext(1); // Start buffering clip 2

  /**
   * Fully stop a video element: pause it, detach its source, and abort any
   * in-flight download. A detached-but-still-loading <video> keeps streaming
   * and decoding in the background, competing with the 3D tile stream.
   */
  function stopVideo(video) {
    if (!video) return;
    video.pause();
    video.removeAttribute('src');
    video.load();
  }

  /**
   * Dismiss the splash overlay with a fade-out transition.
   * Safe to call multiple times; only the first call takes effect.
   */
  function dismissSplash() {
    if (dismissed) return;
    dismissed = true;
    clearClipTimer();
    activeVideo.pause();
    // The standby clip is invisible; hard-stop it now so its download/decode
    // cannot continue after the overlay is gone.
    stopVideo(standbyVideo);
    fadeOutMusic(2000); // Gradually mute music over 2 seconds
    overlay.classList.add('splash-fade-out');
    let finalized = false;
    const finalize = () => {
      if (finalized) return;
      finalized = true;
      stopVideo(activeVideo); // release buffers held by the paused frame
      overlay.remove();
    };
    overlay.addEventListener('transitionend', finalize, { once: true });
    // Fallback in case transitionend never fires (interrupted transition),
    // so the overlay cannot linger invisibly.
    setTimeout(finalize, 2500);
  }

  function attachActiveListeners(video) {
    video.addEventListener('ended', onClipEnded);
  }

  function detachActiveListeners(video) {
    video.removeEventListener('ended', onClipEnded);
  }


  /**
   * Cross-fade from active video to standby video (which has next clip ready).
   */
  function crossFadeToNext() {
    function doFade() {
      if (!standbyVideo.src) {
        console.error('[splash] crossfade aborted: standby video has no src');
        return;
      }
      // Ensure the next clip always starts from the very beginning.
      standbyVideo.currentTime = 0;

      // Permanent log: report the clip that is starting to be displayed.
      console.log('[splash] Now playing: ' + clipName(standbyVideo.currentSrc || standbyVideo.src));

      // Swap visibility
      activeVideo.style.transition = 'opacity 0.4s ease';
      standbyVideo.style.transition = 'opacity 0.4s ease';
      activeVideo.style.opacity = '0';
      standbyVideo.style.opacity = '1';

      // Play the standby video
      const playPromise = standbyVideo.play();
      if (playPromise) {
        playPromise.catch((err) => {
          console.error('[splash] standby play failed:', err);
        });
      }

      // Swap references so activeVideo points to the clip we just started playing.
      const temp = activeVideo;
      activeVideo = standbyVideo;
      standbyVideo = temp;

      // Attach listeners to the new active video.
      attachActiveListeners(activeVideo);

      // Start the per-clip timeout so long clips don't hold the splash.
      startClipTimer();

      // Preload the clip after next into the new standby
      preloadNext(currentClip + 1);
    }

    // Wait until the standby clip is ready to play without stalling.
    if (standbyVideo.readyState >= 3) {
      doFade();
    } else {
      standbyVideo.addEventListener(
        'canplay',
        function onCanPlay() {
          standbyVideo.removeEventListener('canplay', onCanPlay);
          doFade();
        },
        { once: true }
      );
      // Safety timeout: fade anyway after 3s so we don't hang forever.
      setTimeout(() => {
        if (standbyVideo.readyState < 3) {
          console.warn('[splash] standby canplay timeout, fading anyway');
          doFade();
        }
      }, 3000);
    }
  }

  // ── Clip boundary handler ──
  function onClipEnded(e) {
    if (dismissed) return;
    const video = e.target;

    // Remove listeners and the per-clip timeout from the video that just ended.
    detachActiveListeners(video);
    clearClipTimer();

    // Connection errors are only shown after the first clip has finished,
    // so the user gets at least one full video before seeing a red warning.
    if (currentClip === 0) {
      firstClipEnded = true;
      updateConnectionStatus();
    }

    if (tilesReady) {
      // Tiles are loaded — dismiss now (at clip boundary)
      dismissSplash();
    } else if (currentClip < playlist.length - 1) {
      // More clips available — cross-fade to next (already preloaded)
      currentClip++;
      crossFadeToNext();
    } else {
      // End of playlist — start a fresh shuffled cycle (no back-to-back repeat).
      startNewCycle();
    }
  }

  // Attach initial active-video listeners
  attachActiveListeners(videoA);

  // ── Cesium readiness signal ──
  // cesium-main.js dispatches this when tile loading has settled.
  window.addEventListener('cesiumReady', () => {
    tilesReady = true;
    // The periodic readiness check (every 500 ms) will notice this and
    // dismiss the splash immediately, even if the current clip is still
    // playing, so the user reaches the 3D Aerial page as soon as possible.
  });

  // ── Periodic readiness check ──
  // Splash is dismissed only when Cesium tiles are ready AND both core
  // connections (Cesium and Google) are available. If any connection is
  // missing, the splash keeps looping videos and re-checks.
  const CHECK_INTERVAL = 500; // ms
  const readyCheckTimer = setInterval(() => {
    if (tilesReady && cesiumReadyFlag && googleReadyFlag) {
      clearInterval(readyCheckTimer);
      dismissSplash();
    }
  }, CHECK_INTERVAL);

  // ── Timeout fallback: only dismiss after 60 seconds if connections are ready ──
  // If Cesium or Google is still unreachable, stay on the splash screen and
  // keep looping the video clips.
  setTimeout(() => {
    if (tilesReady && cesiumReadyFlag && googleReadyFlag) {
      clearInterval(readyCheckTimer);
      dismissSplash();
    }
  }, 60000);

  // ── Connection monitoring ──
  // The splash stays visible and keeps looping videos until both Cesium and
  // Google are reachable. We re-check every 8 seconds.
  function checkCesium() {
    if (cesiumReadyFlag) return true;
    const ok = typeof window !== 'undefined' && window.Cesium && !!window.cesiumViewer;
    if (ok) {
      cesiumReadyFlag = true;
      console.log('[splash] Cesium connection OK');
    }
    return ok;
  }

  async function checkGoogle() {
    if (googleReadyFlag) return true;
    if (typeof window === 'undefined' || !window.__loadGoogleMapsForSplash) {
      return false;
    }
    try {
      await window.__loadGoogleMapsForSplash();
      googleReadyFlag = true;
      console.log('[splash] Google connection OK');
      return true;
    } catch (err) {
      console.warn('[splash] Google connection failed:', err);
      return false;
    }
  }

  async function updateConnectionStatus() {
    if (dismissed) return;
    const cesiumOk = checkCesium();
    const googleOk = await checkGoogle();

    if (cesiumOk && googleOk) {
      setConnectionError('');
    } else if (firstClipEnded) {
      if (!cesiumOk && !googleOk) {
        setConnectionError('Error: cannot connect to Cesium and Google.');
      } else if (!cesiumOk) {
        setConnectionError('Error: cannot connect to Cesium.');
      } else {
        setConnectionError('Error: cannot connect to Google.');
      }
    }
  }

  // Listen for the Cesium ready signal from cesium-main.js.
  window.addEventListener('cesiumReady', () => {
    cesiumReadyFlag = true;
    updateConnectionStatus();
  });

  // Initial check and periodic re-check.
  updateConnectionStatus();
  setInterval(updateConnectionStatus, 8000);
})();

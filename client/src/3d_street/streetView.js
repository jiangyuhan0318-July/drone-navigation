import config from '../../config.json';

const CALLBACK_NAME = '__gmapsStreetViewInit';
const API_KEY = config.googleApiKey ?? '';

// Must match SWITCH_ALTITUDE - HYSTERESIS in useAltitudeGate.js
const STREET_VIEW_MAX_ALT = 8.0;

let mapsPromise = null;

/**
 * Dynamically load the Google Maps JavaScript API if it is not already present.
 * The same API key used for Google 3D Tiles can be reused, but the Maps JS API
 * must be enabled in the Google Cloud console.
 */
export function loadGoogleMaps() {
  if (mapsPromise) return mapsPromise;

  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Google Maps can only be loaded in a browser'));
  }

  if (window.google?.maps?.StreetViewPanorama) {
    mapsPromise = Promise.resolve(window.google.maps);
    return mapsPromise;
  }

  if (!API_KEY) {
    mapsPromise = Promise.reject(new Error('Missing googleApiKey in client/config.json'));
    return mapsPromise;
  }

  mapsPromise = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      delete window[CALLBACK_NAME];
      reject(new Error('Google Maps JavaScript API load timed out. Check that the API key is valid and Maps JavaScript API is enabled.'));
    }, 15000);

    window[CALLBACK_NAME] = () => {
      clearTimeout(timeout);
      if (window.google?.maps?.StreetViewPanorama) {
        resolve(window.google.maps);
      } else {
        reject(new Error('Google Maps initialized but Street View is unavailable'));
      }
      delete window[CALLBACK_NAME];
    };

    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${API_KEY}&callback=${CALLBACK_NAME}&loading=async`;
    script.async = true;
    script.onerror = () => {
      clearTimeout(timeout);
      delete window[CALLBACK_NAME];
      reject(new Error('Failed to load Google Maps JavaScript API. Verify the API key and that Maps JavaScript API is enabled.'));
    };
    document.head.appendChild(script);
  });

  return mapsPromise;
}

/**
 * Convert a Cesium-style heading (radians clockwise from north) to a Google
 * Street View heading (degrees clockwise from north, 0..360).
 * Applies a 180° offset to compensate for the opposite yaw convention between
 * Google Photorealistic 3D Tiles (aerial) and Street View panorama imagery.
 */
export function cesiumHeadingToStreetView(headingRad) {
  let deg = (headingRad * 180) / Math.PI + 180;
  deg = ((deg % 360) + 360) % 360;
  return deg;
}

/**
 * Convert a Cesium-style pitch (radians from horizontal, positive up) to a
 * Google Street View pitch (degrees from horizontal, positive up).
 * Street View clamps the effective range to roughly +/- 80 degrees.
 */
export function cesiumPitchToStreetView(pitchRad) {
  let deg = (pitchRad * 180) / Math.PI;
  return Math.max(-80, Math.min(80, deg));
}

/**
 * Map drone altitude (0..8 m) to a Street View zoom level (0..1).
 * Capped at 1.0 to avoid aggressive magnification that looks like a
 * horizontal zoom rather than a vertical ascent.
 */
export function altitudeToStreetViewZoom(altitudeM) {
  const t = Math.max(0, Math.min(1, altitudeM / STREET_VIEW_MAX_ALT));
  return t * 1; // 0 at ground, 1 at STREET_VIEW_MAX_ALT
}

/**
 * Compute a pitch offset (degrees) to add to the drone's gimbal pitch
 * when rendering Street View. Tilts the view upward as altitude rises
 * to better simulate a rising viewpoint (more sky/horizon, less street).
 */
export function altitudeToStreetViewPitchOffset(altitudeM) {
  const t = Math.max(0, Math.min(1, altitudeM / STREET_VIEW_MAX_ALT));
  return t * 30; // 0° at ground, +30° at STREET_VIEW_MAX_ALT
}

/**
 * Pre-warm the Street View cache at a given location by fetching panorama
 * metadata and creating a hidden panorama to pre-load tile images.
 * Returns a Promise that resolves when warming is complete or times out.
 */
export async function prewarmStreetView(lat, lon) {
  try {
    const maps = await loadGoogleMaps();

    // Step 1: Fetch panorama metadata
    const service = new maps.StreetViewService();
    await service.getPanorama({
      location: { lat, lng: lon },
      radius: 50,
      source: maps.StreetViewSource.OUTDOOR,
    });

    // Step 2: Create a hidden off-screen panorama to pre-load tile images
    const hiddenContainer = document.createElement('div');
    hiddenContainer.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:256px;height:256px;overflow:hidden;';
    document.body.appendChild(hiddenContainer);

    const panorama = new maps.StreetViewPanorama(hiddenContainer, {
      position: { lat, lng: lon },
      pov: { heading: 0, pitch: 0 },
      zoom: 1,
      addressControl: false,
      clickToGo: false,
      disableDefaultUI: true,
      fullscreenControl: false,
      linksControl: false,
      motionTracking: false,
      motionTrackingControl: false,
      panControl: false,
      scrollwheel: false,
      showRoadLabels: false,
      streetViewControl: false,
      zoomControl: false,
      enableCloseButton: false,
    });

    // Step 3: Wait for tiles to load or timeout
    await new Promise((resolve) => {
      const timeout = setTimeout(() => {
        cleanup();
        resolve();
      }, 2000);

      function cleanup() {
        clearTimeout(timeout);
      }

      panorama.addListener('status_changed', () => {
        cleanup();
        // Give tiles a moment to finish loading
        setTimeout(resolve, 300);
      });
    });

    // Step 4: Destroy the hidden panorama
    if (hiddenContainer.parentNode) {
      hiddenContainer.parentNode.removeChild(hiddenContainer);
    }
  } catch (e) {
    // Silently ignore — pre-warming is best-effort.
  }
}

/**
 * Create a Street View panorama attached to the given container element.
 * Returns an object with helpers to update the view.
 */
export async function createStreetView(container, options = {}) {
  const maps = await loadGoogleMaps();
  const { lat, lon, heading = 0, pitch = 0, zoom = 0 } = options;

  const panorama = new maps.StreetViewPanorama(container, {
    position: { lat, lng: lon },
    pov: {
      heading: cesiumHeadingToStreetView(heading),
      pitch: cesiumPitchToStreetView(pitch),
    },
    zoom: zoom,
    // Hide default Street View UI so it feels like a drone camera feed.
    addressControl: false,
    clickToGo: false,
    disableDefaultUI: true,
    fullscreenControl: false,
    linksControl: false,
    motionTracking: false,
    motionTrackingControl: false,
    panControl: false,
    scrollwheel: false,
    showRoadLabels: false,
    streetViewControl: false,
    zoomControl: false,
    // Allow panning only if the caller opts in.
    enableCloseButton: false,
  });

  panorama.addListener('status_changed', () => {
    const status = panorama.getStatus();
    if (status === maps.StreetViewStatus.UNKNOWN_ERROR) {
      console.warn('[StreetView] Unknown error loading panorama');
    } else if (status === maps.StreetViewStatus.ZERO_RESULTS) {
      console.warn('[StreetView] No panorama found near', { lat, lon });
    }
  });

  return {
    panorama,
    setPosition(lat, lon) {
      panorama.setPosition({ lat, lng: lon });
    },
    setPov(headingRad, pitchRad) {
      panorama.setPov({
        heading: cesiumHeadingToStreetView(headingRad),
        pitch: cesiumPitchToStreetView(pitchRad),
      });
    },
    setZoom(zoom) {
      panorama.setZoom(Math.max(0, Math.min(5, zoom)));
    },
    setVisible(visible) {
      // Setting the container display is handled by the Vue wrapper;
      // this helper can force a resize if needed.
      if (visible && panorama) {
        maps.event.trigger(panorama, 'resize');
      }
    },
    destroy() {
      // There is no explicit destroy API; the panorama is garbage-collected
      // when the container is removed from the DOM.
    },
  };
}

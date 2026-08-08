import { ref } from 'vue';

const googleReady = ref(false);
const cesiumReady = ref(false);
const googleError = ref('');
const cesiumError = ref('');

let googleCheckPromise = null;

/**
 * Check whether the Google Maps JavaScript API can be loaded.
 * Caches the promise so multiple callers share one check.
 */
export async function checkGoogleConnection() {
  if (typeof window === 'undefined') return false;
  if (window.google?.maps?.Map) {
    googleReady.value = true;
    googleError.value = '';
    return true;
  }
  if (!googleCheckPromise) {
    googleCheckPromise = import('../src/2d_map/googleMaps.js')
      .then((mod) => mod.loadGoogleMaps())
      .then(() => {
        googleReady.value = true;
        googleError.value = '';
        return true;
      })
      .catch((err) => {
        googleReady.value = false;
        googleError.value = err.message || 'Cannot connect to Google.';
        googleCheckPromise = null;
        return false;
      });
  }
  return googleCheckPromise;
}

/**
 * Check whether Cesium and the 3D viewer are available.
 */
export async function checkCesiumConnection() {
  if (typeof window === 'undefined') return false;
  if (window.Cesium && window.cesiumViewer) {
    cesiumReady.value = true;
    cesiumError.value = '';
    return true;
  }
  cesiumReady.value = false;
  cesiumError.value = 'Cannot connect to Cesium.';
  return false;
}

/**
 * Reactive connection status for Vue views.
 */
export function useConnectionStatus() {
  return {
    googleReady,
    cesiumReady,
    googleError,
    cesiumError,
    checkGoogleConnection,
    checkCesiumConnection,
  };
}

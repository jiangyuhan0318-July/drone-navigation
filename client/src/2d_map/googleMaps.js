import config from '../../config.json';

const CALLBACK_NAME = '__gmaps2DMapInit';
const API_KEY = config.googleApiKey ?? '';

let mapsPromise = null;

/**
 * Dynamically load the Google Maps JavaScript API if it is not already present.
 */
export function loadGoogleMaps() {
  if (mapsPromise) return mapsPromise;

  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Google Maps can only be loaded in a browser'));
  }

  if (window.google?.maps?.Map) {
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
      mapsPromise = null;
      reject(new Error('Google Maps JavaScript API load timed out'));
    }, 15000);

    window[CALLBACK_NAME] = () => {
      clearTimeout(timeout);
      delete window[CALLBACK_NAME];
      if (window.google?.maps?.Map) {
        resolve(window.google.maps);
      } else {
        mapsPromise = null;
        reject(new Error('Google Maps initialized but Map is unavailable'));
      }
    };

    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${API_KEY}&callback=${CALLBACK_NAME}&loading=async&libraries=places`;
    script.async = true;
    script.onerror = () => {
      clearTimeout(timeout);
      delete window[CALLBACK_NAME];
      mapsPromise = null;
      reject(new Error('Failed to load Google Maps JavaScript API'));
    };
    document.head.appendChild(script);
  });

  return mapsPromise;
}

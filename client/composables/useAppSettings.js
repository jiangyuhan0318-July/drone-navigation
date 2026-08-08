/**
 * useAppSettings.js – singleton reactive store for global app settings.
 * Persisted to localStorage under key 'app-settings'.
 */
import { reactive, watch } from 'vue';

const STORAGE_KEY = 'app-settings';

const defaults = {
  fontFamily: 'Calibri',
  fontSize: '16px',
  takeoffAltitude: 100,
  safetyBuffer: 8,
  defaultLat: 37.4286,
  defaultLon: -122.1699,
  defaultAlt: 150,
  defaultYaw: 180,
  defaultPitch: 0,
  defaultRoll: 0,
  audioVolume: 0.9,
  enterpriseProxy: '',
};

/** Hydrate from localStorage, falling back to defaults. */
function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaults, ...JSON.parse(raw) };
  } catch {
    /* corrupted storage – use defaults */
  }
  return { ...defaults };
}

const state = reactive(loadSettings());

/** Persist on every change. */
watch(
  state,
  (next) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  },
  { deep: true },
);

export function useAppSettings() {
  function setFontFamily(val) {
    state.fontFamily = val;
  }

  function setFontSize(val) {
    state.fontSize = val;
    /* Apply to html root so that rem-based sizes cascade correctly. */
    document.documentElement.style.fontSize = val;
  }

  function setTakeoffAltitude(val) {
    const n = Math.max(20, Math.min(10000, Number(val) || 200));
    state.takeoffAltitude = n;
  }

  function setSafetyBuffer(val) {
    const n = Math.max(2, Math.min(100, Number(val) || 18));
    state.safetyBuffer = n;
  }

  function setDefaultLat(val) {
    const n = Number(val);
    if (!isNaN(n) && n >= -90 && n <= 90) state.defaultLat = n;
  }

  function setDefaultLon(val) {
    const n = Number(val);
    if (!isNaN(n) && n >= -180 && n <= 180) state.defaultLon = n;
  }

  function setDefaultAlt(val) {
    const n = Math.max(0, Math.min(10000, Number(val) || 150));
    state.defaultAlt = n;
  }

  function setDefaultYaw(val) {
    const n = Number(val) || 0;
    state.defaultYaw = ((n % 360) + 360) % 360;
  }

  function setDefaultPitch(val) {
    const n = Number(val) || 0;
    state.defaultPitch = Math.max(-90, Math.min(90, n));
  }

  function setDefaultRoll(val) {
    const n = Number(val) || 0;
    state.defaultRoll = Math.max(-90, Math.min(90, n));
  }

  function setAudioVolume(val) {
    const n = Number(val);
    if (!isNaN(n)) state.audioVolume = Math.max(0, Math.min(1, n));
  }

  function setEnterpriseProxy(val) {
    state.enterpriseProxy = String(val || '');
  }

  function resetFontDefaults() {
    state.fontFamily = defaults.fontFamily;
    state.fontSize = defaults.fontSize;
    document.documentElement.style.fontSize = defaults.fontSize;
  }

  function resetFlightDefaults() {
    state.takeoffAltitude = defaults.takeoffAltitude;
    state.safetyBuffer = defaults.safetyBuffer;
    state.defaultLat = defaults.defaultLat;
    state.defaultLon = defaults.defaultLon;
    state.defaultAlt = defaults.defaultAlt;
    state.defaultYaw = defaults.defaultYaw;
    state.defaultPitch = defaults.defaultPitch;
    state.defaultRoll = defaults.defaultRoll;
  }

  function resetMediaDefaults() {
    state.audioVolume = defaults.audioVolume;
  }

  function resetNetworkDefaults() {
    state.enterpriseProxy = defaults.enterpriseProxy;
  }

  function resetToDefaults() {
    Object.assign(state, defaults);
    document.documentElement.style.fontSize = defaults.fontSize;
  }

  return {
    settings: state,
    setFontFamily,
    setFontSize,
    setTakeoffAltitude,
    setSafetyBuffer,
    setDefaultLat,
    setDefaultLon,
    setDefaultAlt,
    setDefaultYaw,
    setDefaultPitch,
    setDefaultRoll,
    resetFontDefaults,
    resetFlightDefaults,
    resetMediaDefaults,
    resetNetworkDefaults,
    resetToDefaults,
  };
}

import { reactive } from 'vue';
import { useAppSettings } from './useAppSettings.js';

const { settings } = useAppSettings();

const drone = reactive({
  lat: settings.defaultLat,
  lon: settings.defaultLon,
  alt: settings.defaultAlt,
  heading: settings.defaultYaw,
});

const gimbal = reactive({
  yaw: 0.0,
  pitch: settings.defaultPitch,
  roll: settings.defaultRoll,
});

export function useDrone() {
  function setDroneLocation(lat, lon, altitude = null) {
    drone.lat = lat;
    drone.lon = lon;
    if (altitude !== null) {
      drone.alt = altitude;
    }
  }

  return { drone, gimbal, setDroneLocation };
}

import { useDrone } from './useDrone.js';
import { useFlightCommands } from './useFlightCommands.js';

const MOVEMENT_SPEED = 0.0002; // degrees per frame at full deflection
const ALTITUDE_SPEED = 20.0; // meters per second at full deflection
const ROTATION_SPEED = 60.0; // degrees per second at full deflection
const ZOOM_RATE = 2.5; // zoom levels per second at full deflection (exponential H-mode)

export function useFlightPhysics() {
  const { drone } = useDrone();
  const { flightCmd, activeFlightMode, flight } = useFlightCommands();

  function computeDesiredEnuMove(dt, allowAltitude = true, options = {}) {
    if (activeFlightMode.value === 'M') {
      // World-aligned movement: W=north, S=south, A=west, D=east
      const latRad = (drone.lat * Math.PI) / 180;
      const metersPerDegLat = 111320;
      const metersPerDegLon = metersPerDegLat * Math.cos(latRad);

      const dNorthDeg = flightCmd.vy * MOVEMENT_SPEED * dt;
      const dEastDeg = flightCmd.vx * MOVEMENT_SPEED * dt;

      const dNorthM = dNorthDeg * metersPerDegLat;
      const dEastM = dEastDeg * metersPerDegLon;

      return { x: dEastM, y: dNorthM, z: 0 };
    }

    if (activeFlightMode.value === 'H' && allowAltitude) {
      if (options.exponentialAltitude) {
        // Match Google Maps native wheel: zoom level changes linearly with input,
        // so altitude (20971520 / 2^zoom) changes exponentially with time.
        // Up/positive vz means climb -> altitude increases -> zoom out.
        const dz = flightCmd.vz * ZOOM_RATE * dt;
        const newAlt = drone.alt * Math.pow(2, dz);
        return { x: 0, y: 0, z: newAlt - drone.alt };
      }
      return { x: 0, y: 0, z: flightCmd.vz * ALTITUDE_SPEED * dt };
    }

    return null;
  }

  function applyEnuMove(enuMove) {
    if (!enuMove) return;
    const latRad = (drone.lat * Math.PI) / 180;
    const metersPerDegLat = 111320;
    const metersPerDegLon = metersPerDegLat * Math.cos(latRad);

    drone.lat += enuMove.y / metersPerDegLat;
    drone.lon += enuMove.x / metersPerDegLon;
    drone.alt += enuMove.z;
  }

  function updateTelemetry(allowAltitude = true, options = {}) {
    if (activeFlightMode.value === 'M') {
      flight.vx = flightCmd.vx;
      flight.vy = flightCmd.vy;
      flight.yaw = 0;
      flight.vz = 0;
    } else if (activeFlightMode.value === 'R') {
      flight.vx = 0;
      flight.vy = 0;
      flight.yaw = flightCmd.yaw;
      flight.vz = 0;
    } else if (activeFlightMode.value === 'H' && allowAltitude) {
      flight.vx = 0;
      flight.vy = 0;
      flight.yaw = 0;
      flight.vz = flightCmd.vz;
      if (options.exponentialAltitude) {
        // Report the instantaneous vertical speed in m/s for telemetry.
        flight.vz = flightCmd.vz * ZOOM_RATE * Math.LN2 * drone.alt;
      }
    }
  }

  function step(dt, { allowAltitude = true, applyMovement = true, exponentialAltitude = false } = {}) {
    if (!applyMovement) return;

    const options = { exponentialAltitude };

    if (activeFlightMode.value === 'R') {
      drone.heading += flightCmd.yaw * ROTATION_SPEED * dt;
    } else {
      const enuMove = computeDesiredEnuMove(dt, allowAltitude, options);
      applyEnuMove(enuMove);
    }
    updateTelemetry(allowAltitude, options);
  }

  return {
    step,
    computeDesiredEnuMove,
    applyEnuMove,
    updateTelemetry,
  };
}

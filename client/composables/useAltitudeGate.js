import { ref, computed } from 'vue';
import { useAppSettings } from '@shared-composables/useAppSettings.js';
import { useTilesetSource } from '@shared-composables/useTilesetSource.js';
import { prewarmStreetView } from '@/3d_street/streetView.js';

/* global Cesium */

const { settings } = useAppSettings();

export const SWITCH_ALTITUDE = 10.0;  // meters: center of the switch threshold (test: 15, 20, etc.)
const HYSTERESIS = 2.0;               // meters: half-width of the hysteresis band
export const DESCEND_THRESHOLD = SWITCH_ALTITUDE - HYSTERESIS; // switch to street view
export const ASCEND_THRESHOLD = SWITCH_ALTITUDE + HYSTERESIS;  // switch back to aerial view
const AUTO_SPEED = 8.0;         // meters per second for auto takeoff/landing
const AUTO_TOLERANCE = 0.2;     // meters: stop auto when within this distance
const PRE_TAKEOFF_DELAY = 2500; // ms: hold during PRE_TAKEOFF for tile caching
const PRE_LANDING_DELAY = 1500; // ms: hold during PRE_LANDING for panorama caching

export const PHASES = {
  IDLE: 'IDLE',
  PRE_TAKEOFF: 'PRE_TAKEOFF',
  ASCENDING: 'ASCENDING',
  CRUISING: 'CRUISING',
  PRE_LANDING: 'PRE_LANDING',
  DESCENDING: 'DESCENDING',
};

/**
 * Composable that tracks the drone's altitude relative to the 3D tileset
 * surface, manages a hysteresis-based aerial/ground state, and drives
 * automatic takeoff/landing sequences with pre-cache delay phases.
 */
export function useAltitudeGate(drone) {
  const { getActiveTileset, activeSource } = useTilesetSource();
  const surfaceAlt = ref(0);
  const isOnGround = ref(true);
  const flightPhase = ref(PHASES.IDLE);
  const lastSequence = ref('landing'); // tracks last auto sequence: 'takeoff' or 'landing'
  const isPausedByCollision = ref(false);
  let phaseTimer = null;

  const isTransitioning = computed(() => {
    const p = flightPhase.value;
    return p !== PHASES.IDLE && p !== PHASES.CRUISING;
  });

  /**
   * Sample the 3D tileset surface directly beneath the drone.
   * Returns the surface altitude in meters above the ellipsoid, or null if
   * the scene is not ready or nothing was hit.
   */
  function sampleSurfaceAltitude(viewer) {
    if (!viewer) return null;
    const position = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, drone.alt);
    const down = Cesium.Cartesian3.negate(
      Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(position, new Cesium.Cartesian3()),
      new Cesium.Cartesian3()
    );
    const ray = new Cesium.Ray(position, down);
    let hit = null;
    try {
      hit = viewer.scene.pickFromRay(ray);
    } catch {
      return null; // transient raycast failure while tiles stream — keep last estimate
    }
    if (hit && hit.position) {
      const cartographic = Cesium.Cartographic.fromCartesian(hit.position);
      return cartographic.height;
    }
    return null;
  }

  /**
   * Update the surface altitude estimate and the ground/airborne state.
   * Should be called once per frame before movement logic runs.
   */
  function update(viewer) {
    const sampled = sampleSurfaceAltitude(viewer);
    if (sampled !== null) {
      surfaceAlt.value = sampled;
    }

    const relativeAlt = drone.alt - surfaceAlt.value;

    // Hysteresis: only change state when crossing the appropriate threshold.
    if (relativeAlt <= DESCEND_THRESHOLD) {
      isOnGround.value = true;
    } else if (relativeAlt >= ASCEND_THRESHOLD) {
      isOnGround.value = false;
    }

    return {
      relativeAlt,
      surfaceAlt: surfaceAlt.value,
    };
  }

  /**
   * Move drone.alt toward a target altitude at AUTO_SPEED.
   * Returns true when the target is reached.
   */
  function stepToward(targetAlt, dt) {
    const delta = targetAlt - drone.alt;
    if (Math.abs(delta) <= AUTO_TOLERANCE) {
      drone.alt = targetAlt;
      return true;
    }
    const step = Math.sign(delta) * AUTO_SPEED * dt;
    drone.alt += Math.abs(step) > Math.abs(delta) ? delta : step;
    return false;
  }

  /**
   * Start an automatic takeoff with a pre-cache delay phase.
   * Phase: IDLE -> PRE_TAKEOFF (delay) -> ASCENDING
   * Returns false (no sequence started) when the drone is already at/above
   * the takeoff altitude — the caller surfaces a reminder for that case.
   *
   * opts.cameraPrewarm: allow the tile pre-warm to teleport the camera (the
   * caller must guarantee the Cesium canvas is currently covered — otherwise
   * the teleport is visible as a tremble; see prewarmTiles).
   */
  function startTakeoff(viewer, { cameraPrewarm = true } = {}) {
    update(viewer); // refresh surfaceAlt first
    const target = surfaceAlt.value + settings.takeoffAltitude;
    if (drone.alt >= target - AUTO_TOLERANCE) {
      // Already at/above the takeoff altitude: nothing to climb to.
      flightPhase.value = PHASES.CRUISING;
      isOnGround.value = false;
      lastSequence.value = 'takeoff';
      return false;
    }
    flightPhase.value = PHASES.PRE_TAKEOFF;
    isOnGround.value = false; // unlock ground clamp immediately
    lastSequence.value = 'takeoff';
    prewarmTiles(viewer, cameraPrewarm);
    clearTimeout(phaseTimer);
    phaseTimer = setTimeout(() => {
      flightPhase.value = PHASES.ASCENDING;
    }, PRE_TAKEOFF_DELAY);
    return true;
  }

  /**
   * Start an automatic landing with a pre-cache delay phase.
   * Phase: CRUISING -> PRE_LANDING (delay) -> DESCENDING
   */
  function startLanding(viewer) {
    update(viewer); // refresh surfaceAlt first
    flightPhase.value = PHASES.PRE_LANDING;
    lastSequence.value = 'landing';
    // Only pre-warm Street View on the Google-tiles (aerial) source. On OSM
    // Buildings the drone stays on the 3D tiles all the way to the ground, and
    // loading Street View would spin up a second WebGL context that fights
    // Cesium's (the uniform3fv warnings).
    if (activeSource.value !== 'osm') {
      prewarmStreetView(drone.lat, drone.lon);
    }
    clearTimeout(phaseTimer);
    phaseTimer = setTimeout(() => {
      flightPhase.value = PHASES.DESCENDING;
    }, PRE_LANDING_DELAY);
  }

  /**
   * Cast a vertical ray (up or down) from the drone to check for obstacles
   * in the 3D tileset. Returns true if an obstacle is within the safety buffer.
   */
  function checkVerticalCollision(viewer, ascending) {
    if (!viewer) return false;
    const tileset = getActiveTileset();
    if (!tileset) return false;

    const position = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, drone.alt);
    const surfaceNormal = Cesium.Ellipsoid.WGS84.geodeticSurfaceNormal(position, new Cesium.Cartesian3());
    const direction = ascending
      ? surfaceNormal
      : Cesium.Cartesian3.negate(surfaceNormal, new Cesium.Cartesian3());

    const ray = new Cesium.Ray(position, direction);
    let result = null;
    try {
      result = viewer.scene.pickFromRay(ray);
    } catch {
      return false; // transient raycast failure — assume no obstacle this frame
    }
    if (!result || !result.position) return false;

    const hitObject = result.object;
    const isTilesetHit =
      hitObject === tileset ||
      (hitObject && hitObject.tileset === tileset) ||
      (hitObject && hitObject.primitive === tileset);
    if (!isTilesetHit) return false;

    // For landing (descending): compute the altitude of the hit point.
    // If the hit is at or below the expected ground surface, it IS the
    // ground — not an obstacle. Only flag hits above the surface.
    if (!ascending) {
      const hitCartographic = Cesium.Cartographic.fromCartesian(result.position);
      const hitAlt = hitCartographic ? hitCartographic.height : 0;
      if (hitAlt <= surfaceAlt.value + 1.0) return false;
    }

    const distance = Cesium.Cartesian3.distance(position, result.position);
    const buffer = settings.safetyBuffer;
    return distance <= buffer;
  }

  /**
   * Run the automatic takeoff/landing step. Returns true if the sequence
   * completed this frame. No-op during PRE_TAKEOFF / PRE_LANDING delay phases.
   */
  function stepAuto(dt, viewer) {
    update(viewer);

    if (flightPhase.value === PHASES.ASCENDING) {
      // Check for obstacles above before ascending.
      // On collision, pause the sequence and wait for the user to move.
      if (checkVerticalCollision(viewer, true)) {
        isPausedByCollision.value = true;
        return false;
      }
      isPausedByCollision.value = false;
      const target = surfaceAlt.value + settings.takeoffAltitude;
      // The user-driven takeoff/stop/landing switcher can offer 'takeoff' at
      // any altitude: when already at/above the target there is nothing to
      // climb to — complete immediately instead of descending toward it.
      if (drone.alt >= target - AUTO_TOLERANCE || stepToward(target, dt)) {
        flightPhase.value = PHASES.CRUISING;
        isOnGround.value = false;
        return true;
      }
      return false;
    }

    if (flightPhase.value === PHASES.DESCENDING) {
      // Check for obstacles below before descending.
      // On collision, pause the sequence and wait for the user to move.
      if (checkVerticalCollision(viewer, false)) {
        isPausedByCollision.value = true;
        return false;
      }
      isPausedByCollision.value = false;
      const target = surfaceAlt.value;
      if (stepToward(target, dt)) {
        flightPhase.value = PHASES.IDLE;
        isOnGround.value = true;
        return true;
      }
      return false;
    }

    return false;
  }

  /**
   * Clamp the drone to the surface when it is on the ground. This keeps a
   * landed drone on a roof or slope when the user moves horizontally.
   */
  function snapToGround() {
    drone.alt = surfaceAlt.value;
  }

  /**
   * STOP action of the takeoff/stop/landing switcher: abort any in-progress
   * auto sequence (including a pending pre-cache timer) and hold the current
   * altitude (CRUISING). A completed or never-started sequence keeps its IDLE
   * phase so a grounded drone stays grounded. Inside the bottom ground band
   * the per-frame ground clamp settles the drone onto the surface, so a
   * low-altitude stop behaves like an early landing / takeoff abort.
   */
  function stopAuto() {
    clearTimeout(phaseTimer);
    phaseTimer = null;
    isPausedByCollision.value = false;
    if (isTransitioning.value) {
      flightPhase.value = PHASES.CRUISING;
    }
  }

  /**
   * Pre-warm the Cesium tile cache at the drone's position and target altitude.
   * Teleports the VISIBLE camera to targetAlt and sweeps pitch from 0 to -30
   * deg to cache a wider cone of tiles before the drone ascends.
   *
   * WARNING: this moves the real camera. The dashboard re-asserts the drone
   * pose every animation frame (window.updateCesiumCamera), so each teleport
   * snaps back one frame later — when the Cesium canvas is visible this reads
   * as a short "tremble". Pass allowTeleport=true ONLY when the canvas is
   * fully covered (Street View overlay, .cesium-hidden = opacity 0 — the
   * canvas keeps rendering, so the warm poses still trigger tile requests).
   * When skipped, tiles simply stream in progressively during the slow
   * (8 m/s) ascent, which is visually fine.
   */
  function prewarmTiles(viewer, allowTeleport = true) {
    if (!viewer || !allowTeleport) return;
    const camera = viewer.camera;
    const savedPosition = camera.position.clone();
    const savedHeading = camera.heading;
    const savedPitch = camera.pitch;
    const savedRoll = camera.roll;

    const targetAlt = surfaceAlt.value + settings.takeoffAltitude;
    const warmPosition = Cesium.Cartesian3.fromDegrees(drone.lon, drone.lat, targetAlt);

    // Sweep pitch angles to cache a wider tile cone
    const pitchSweep = [0, -Math.PI / 12, -Math.PI / 6]; // 0, -15, -30 degrees
    const sweepInterval = 400; // ms between sweeps

    // Initial position at pitch 0
    camera.setView({
      destination: warmPosition,
      orientation: { heading: savedHeading, pitch: pitchSweep[0], roll: 0 },
    });
    viewer.scene.requestRender();

    // Sweep additional pitch angles during the hold
    for (let i = 1; i < pitchSweep.length; i++) {
      setTimeout(() => {
        if (viewer && !viewer.isDestroyed()) {
          camera.setView({
            destination: warmPosition,
            orientation: { heading: savedHeading, pitch: pitchSweep[i], roll: 0 },
          });
          viewer.scene.requestRender();
        }
      }, sweepInterval * i);
    }

    // Restore original camera after all sweeps
    setTimeout(() => {
      if (viewer && !viewer.isDestroyed()) {
        camera.setView({
          destination: savedPosition,
          orientation: { heading: savedHeading, pitch: savedPitch, roll: savedRoll },
        });
      }
    }, sweepInterval * pitchSweep.length);
  }

  return {
    surfaceAlt,
    isOnGround,
    flightPhase,
    lastSequence,
    isPausedByCollision,
    isTransitioning,
    update,
    startTakeoff,
    startLanding,
    stepAuto,
    snapToGround,
    stopAuto,
    prewarmTiles,
  };
}

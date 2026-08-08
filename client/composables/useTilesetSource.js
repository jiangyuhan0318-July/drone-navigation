/**
 * useTilesetSource.js – singleton that manages the active 3D data source of
 * the shared Cesium viewer.
 *
 * The `3D Aerial` and `3D Mesh` subpages of the 3D Exploration page are
 * identical in every respect (flight disk, gimbal disk, sidebars, physics)
 * except for the 3D dataset rendered:
 *   - 'google' → Google Photorealistic 3D Tiles (created by cesium-main.js)
 *   - 'osm'    → OSM Buildings (Cesium Ion) over World Terrain
 *
 * This composable swaps the tilesets on the single global viewer and exposes
 * the currently active tileset so collision / ground raycasts always target
 * the dataset that is actually on screen.
 */
import { ref } from 'vue';

/* global Cesium */

// ── Module-level singleton state (shared by every consumer) ──────────────
const activeSource = ref('google'); // 'google' | 'osm'
const isSwitching = ref(false);

let osmTileset = null; // lazily created Cesium3DTileset (OSM Buildings)
let worldTerrain = null; // cached CesiumTerrainProvider used for OSM context
let worldImageryProvider = null; // cached Bing Maps aerial imagery for the OSM globe

function getViewer() {
  return window.cesiumViewer || null;
}

function getGoogleTilesetRef() {
  return window.getGoogleTileset ? window.getGoogleTileset() : null;
}

/**
 * The 3D tileset that collision / ground raycasts should target for the
 * currently active data source. Returns null if it is not (yet) available.
 */
function getActiveTileset() {
  if (activeSource.value === 'osm') return osmTileset;
  return getGoogleTilesetRef();
}

/**
 * Neutral image-based-lighting spherical harmonic coefficients (order:
 * L0,0, L1,-1, L1,0, L1,1, L2,-2, L2,-1, L2,0, L2,1, L2,2). Built lazily
 * because `Cesium` is only available after the CDN script loads, and shared
 * across tilesets (Cesium only reads the array, never mutates it).
 */
let neutralSH = null;
function getNeutralSphericalHarmonics() {
  if (!neutralSH) {
    neutralSH = [
      new Cesium.Cartesian3(0.50, 0.50, 0.50), // L0,0 — base ambient irradiance
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L1,-1
      new Cesium.Cartesian3(0.20, 0.20, 0.20), // L1,0 — sky is brighter overhead
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L1,1
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L2,-2
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L2,-1
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L2,0
      new Cesium.Cartesian3(0.0, 0.0, 0.0),    // L2,1
      new Cesium.Cartesian3(0.0, 0.0, 0.0)     // L2,2
    ];
  }
  return neutralSH;
}

/**
 * Give a 3D tileset an explicit image-based-lighting spherical harmonic
 * coefficient set. The tileset's PBR shaders expect a vec3[9] uniform
 * (model_sphericalHarmonicCoefficients) for diffuse IBL. Every model's shader
 * captures, ONCE at pipeline-build time:
 *   model.imageBasedLighting.sphericalHarmonicCoefficients
 *     ?? model.environmentMapManager.sphericalHarmonicCoefficients
 * Without an explicit set, the shader captures whatever the tileset's
 * DynamicEnvironmentMapManager returns — and the manager recomputes its
 * coefficients ON THE GPU (irradiance-map readback), which leaves the array
 * EMPTY on GPUs where that readback never completes. The captured empty array
 * is then fed to uniform3fv in every pass (main AND pick), producing
 * "WebGL: INVALID_VALUE: uniform3fv: no array" every frame.
 *
 * Two pins are therefore applied, both BEFORE the tileset enters the scene:
 *  1. Mutate tileset.imageBasedLighting.sphericalHarmonicCoefficients (the
 *     read-only getter returns the tileset's own ImageBasedLighting instance;
 *     assigning a new ImageBasedLighting to the property would throw, exactly
 *     like the Scene.imageBasedLighting mistake did at startup).
 *  2. Pin the tileset's environmentMapManager sphericalHarmonicCoefficients
 *     via an own-property getter that shadows the prototype getter. This does
 *     NOT depend on the tileset→model IBL hand-off (the manager reference is
 *     assigned to each model directly) and leaves the manager otherwise fully
 *     functional (specular radiance maps keep updating).
 *
 * Exported because it must be applied to EVERY 3D tileset in the app — the
 * Google Photorealistic tileset (cesium-main.js) AND the OSM Buildings
 * tileset (here). Fixing only one leaves the other's models throwing in
 * every view that raycasts them.
 */
export function applyNeutralSphericalHarmonics(tileset) {
  try {
    const sh = getNeutralSphericalHarmonics();
    const ibl = tileset.imageBasedLighting;
    if (ibl) {
      ibl.sphericalHarmonicCoefficients = sh;
    } else {
      console.warn('[TilesetSource] Tileset has no imageBasedLighting instance; skipping SH override.');
    }
    const mgr = tileset.environmentMapManager;
    if (mgr) {
      Object.defineProperty(mgr, 'sphericalHarmonicCoefficients', {
        get: () => sh,
        configurable: true,
      });
    } else {
      console.warn('[TilesetSource] Tileset has no environmentMapManager; skipping manager SH pin.');
    }
  } catch (e) {
    console.warn('[TilesetSource] Failed to set spherical harmonics:', e);
  }
}

/**
 * Pin the SCENE-level spherical-harmonic feed. The tileset pins above only
 * cover Model shaders; the globe surface shader (visible only in 3D Mesh
 * mode, where globe.show = true) and other atmosphere-lit passes read the
 * vec3[9] automatic uniform czm_sphericalHarmonicCoefficients via
 * uniformState ← frameState, and Cesium's scene-level coefficients are
 * computed on the GPU — they can come back EMPTY on GPUs where the readback
 * never completes, producing the same "uniform3fv: no array" for every globe
 * draw (main AND pick passes). Own-property getters (with no-op setters so
 * Cesium's per-frame writes are harmlessly swallowed) pin every read to the
 * explicit neutral set.
 */
export function pinSceneSphericalHarmonics(scene) {
  try {
    const sh = getNeutralSphericalHarmonics();
    const pin = (obj) => {
      if (!obj) return;
      Object.defineProperty(obj, 'sphericalHarmonicCoefficients', {
        get: () => sh,
        set: () => {}, // swallow Cesium's per-frame writes
        configurable: true,
      });
    };
    pin(scene.context && scene.context.uniformState);
    pin(scene._frameState);
  } catch (e) {
    console.warn('[TilesetSource] Failed to pin scene spherical harmonics:', e);
  }
}

/** Show OSM Buildings: hide Google tiles, enable globe + World Terrain. */
async function activateOsm(viewer) {
  // Hide (do NOT remove) the Google tileset: scene.primitives has
  // destroyPrimitives = true by default, so primitives.remove() would
  // DESTROY it and it could never render again when switching back.
  // Toggling .show keeps it alive and tile-cached while Cesium skips all
  // traversal, requests and rendering for it.
  const google = getGoogleTilesetRef();
  if (google) google.show = false;

  // OSM Buildings need a visible globe + terrain for ground context.
  viewer.scene.globe.show = true;

  // Drape real satellite/aerial imagery (Bing Maps via Cesium Ion) over the
  // globe so the 3D Mesh view reads as "satellite imagery + mesh buildings"
  // rather than the stylized NaturalEarthII map set at viewer creation. The
  // globe is hidden in Google/aerial mode, so this only affects 3D Mesh.
  if (!worldImageryProvider) {
    try {
      worldImageryProvider = await Cesium.createWorldImageryAsync();
    } catch (e) {
      console.warn('[TilesetSource] World Imagery failed to load:', e);
    }
  }
  if (worldImageryProvider) {
    viewer.imageryLayers.removeAll();
    viewer.imageryLayers.addImageryProvider(worldImageryProvider);
  }

  if (!worldTerrain) {
    try {
      worldTerrain = await Cesium.createWorldTerrainAsync();
    } catch (e) {
      console.warn('[TilesetSource] World Terrain failed to load:', e);
    }
  }
  if (worldTerrain) viewer.terrainProvider = worldTerrain;

  if (!osmTileset) {
    osmTileset = await Cesium.createOsmBuildingsAsync();
    // Set BEFORE primitives.add below, so every OSM model pipeline captures
    // the explicit coefficients when its shader is built (see doc comment).
    applyNeutralSphericalHarmonics(osmTileset);
    // Add once and keep it in the scene; visibility is toggled via .show
    // (see the Google-tileset note above about remove() destroying).
    viewer.scene.primitives.add(osmTileset);
  }
  osmTileset.show = true;
  console.log('[TilesetSource] OSM Buildings active.');
}

/** Restore Google Photorealistic 3D Tiles and the default globe state. */
function activateGoogle(viewer) {
  // Toggle .show instead of primitives.remove()/add() — remove() would
  // DESTROY the tileset (scene.primitives.destroyPrimitives defaults to
  // true), leaving the aerial view permanently blank after one mesh visit.
  if (osmTileset) osmTileset.show = false;

  const google = getGoogleTilesetRef();
  if (google) google.show = true;

  // Google photorealistic tiles cover the whole scene; hide the base globe
  // and restore a flat ellipsoid (matches the cesium-main.js default).
  viewer.scene.globe.show = false;
  viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
  console.log('[TilesetSource] Google Photorealistic 3D Tiles active.');
}

export function useTilesetSource() {
  /**
   * Switch the viewer's 3D data source ('google' | 'osm'). Safe to call
   * repeatedly; a switch already in progress is ignored. On failure the
   * scene falls back to Google tiles so it is never left empty.
   */
  async function setSource(source) {
    const viewer = getViewer();
    if (!viewer || isSwitching.value || source === activeSource.value) return;
    isSwitching.value = true;
    try {
      if (source === 'osm') {
        await activateOsm(viewer);
        activeSource.value = 'osm';
      } else {
        activateGoogle(viewer);
        activeSource.value = 'google';
      }
    } catch (e) {
      console.error(`[TilesetSource] Failed to switch to "${source}":`, e);
      if (source === 'osm') {
        activateGoogle(viewer);
        activeSource.value = 'google';
      }
    } finally {
      isSwitching.value = false;
    }
  }

  return { activeSource, isSwitching, setSource, getActiveTileset };
}

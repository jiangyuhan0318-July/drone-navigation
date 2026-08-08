# Drone Navigation Client

A multi-view drone navigation dashboard with a shared component architecture.

## Architecture

```
client/                     # Vite project root
├── index.html              # Entry point (Cesium CDN, splash overlay, Vue mount)
├── vite.config.js          # Vite config with @shared and @shared-composables aliases
├── style.css               # Global styles (splash screen, layout)
├── src/                    # Application source code
│   ├── App.vue             # Root Vue component
│   ├── main.js             # Vue app initialization
│   ├── router/             # Vue Router routes
│   ├── views/              # Page components (AerialView, Map2DView, Satellite2DView, ChatView, SettingsView)
│   ├── components/         # App-specific components (CollisionWarning, StreetViewPane)
│   ├── composables/        # App-specific composables (useAltitudeGate)
│   ├── config/             # IconConfig.js — centralized SVG icon registry
│   ├── 2d_map/             # Google Maps 2D map module (MapView.vue)
│   ├── 3d_street/          # Google Street View panorama module (streetView.js)
│   ├── cesium-main.js      # Cesium viewer init, Google 3D Tiles, camera sync
│   └── dronePhysics.js     # Keyboard-driven drone physics (WASD + arrows)
├── components/             # Shared UI components (@shared alias)
│   ├── _ViewComposer.vue
│   ├── _DiskBase.vue
│   ├── AppDock.vue
│   ├── DockButton.vue
│   ├── FlightController.vue
│   ├── GimbalController.vue
│   ├── HUD.vue
│   └── ConfigurableIcon.vue
├── composables/            # Shared reactive state (@shared-composables alias)
│   ├── useDrone.js
│   ├── useFlightCommands.js
│   ├── useFlightPhysics.js
│   ├── useCameraCommands.js
│   ├── useCameraPhysics.js
│   ├── useDockRegistry.js
│   └── useAppSettings.js
├── public/                 # Static assets (splash videos, PWA install page)
├── icons/                  # SVG icons used by ConfigurableIcon
├── assets/                 # Shared media and documents
└── config.json             # API keys (gitignored)
```

Pages are composed with `_ViewComposer.vue`, which provides:

- Configurable left/right docks.
- Flight and gimbal control disks (built on `_DiskBase.vue`).
- The HUD dashboard (toggleable via `showHud` prop).
- A `disabled` prop to lock joysticks during auto takeoff/landing.
- `background` and `top-overlay` slots for page-specific content.

Each page registers its own dock buttons through `useDockRegistry()` (a module-level singleton), so third-party plugins can add sidebar items by calling `registerLeft()` or `registerRight()` inside their setup code.

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | `AerialView.vue` | 3D photorealistic aerial view (Cesium) with collision detection, auto takeoff/landing, and Street View fallback when grounded. |
| `/map` | `Map2DView.vue` | 2D Google Map with a centered drone icon. |
| `/satellite` | `Satellite2DView.vue` | 2D Google Satellite view. |
| `/chat` | `ChatView.vue` | Mission-control chat interface. |

## Key features

### Collision detection (`AerialView.vue`)

Raycasts against the Google Photorealistic 3D tileset in the drone's movement direction. When an obstacle is detected within a safety buffer (2 m + speed × 2 s lookahead), movement is projected along the surface normal to prevent the drone from passing through buildings or terrain. A red warning banner (`CollisionWarning.vue`) flashes at the top of the screen while movement is restricted.

### Auto takeoff / landing (`useAltitudeGate.js`)

A hysteresis-based altitude gate manages ground/air state:

- **Descend threshold**: ≤ 15 m above surface → considered on ground.
- **Ascend threshold**: ≥ 18 m above surface → considered airborne.
- **Auto sequence**: moves altitude at 8 m/s toward the target (surface altitude for landing, surface + 15 m for takeoff).

Flight controls are locked during the transition. When the drone is on the ground, the Cesium globe is hidden and a Google Street View panorama (`StreetViewPane.vue`) is shown instead, synced to drone position, heading, and gimbal angles.

### Street View ground mode (`src/3d_street/`)

Dynamically loads the Google Maps JavaScript API and creates a `StreetViewPanorama` inside `StreetViewPane.vue`. The panorama's position, heading, pitch, and zoom are kept in sync with the drone state. Zoom is mapped from altitude (0 m → wide FOV, 15 m → narrow elevated FOV) to give an immersive ground-level feel.

### Cesium fallback (`cesium-main.js`)

If Google Photorealistic 3D Tiles fail to load (invalid API key, network error, etc.), the app falls back to **Cesium World Terrain** + **OSM Buildings** and re-enables the base globe so the scene is never blank.

### Icon configuration (`config/IconConfig.js`)

All SVG icons live in `client/icons/` and are mapped by key in `IconConfig.js` using Vite's `import.meta.glob`. The `ConfigurableIcon.vue` component resolves a key (e.g. `MENU_CONTROL_STICK`) to the corresponding raw SVG markup. To add or swap an icon, update the mapping in `IconConfig.js` — no component changes needed.

## Prerequisite

This project needs two external credentials. Set them in `config.json` (this file is gitignored; use `config.example.json` as a template).

### 1. Google Maps API key

Required APIs to enable on the same key:

- **Map Tiles API** — loads Google Photorealistic 3D Tiles in Cesium.
- **Maps JavaScript API** — loads the interactive Street View panorama during takeoff/landing and the 2D map toggle.
- **Places API (New)** — fetches nearby points of interest when selecting a waypoint origin on the 2D map or satellite view. The 2D map uses the new `google.maps.places.Place.searchNearby` API.
- **Geocoding API** — converts latitude/longitude to a human-readable address for waypoint details.
- **Maps Elevation API** — samples terrain elevation for route and altitude planning.
- **Routes API** — computes routes between waypoints (required for the **Search route** button in the waypoint panel).
- **Roads API** — snaps coordinates to the nearest road for accurate ground routes.

#### Step-by-step

1. Go to the Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or select an existing one.
3. Set up a billing account if you have not already:
   - Open the navigation menu → **Billing** → **Manage billing accounts**.
   - Follow the prompts to add a payment method.
   - Link the billing account to your project.
   - Google Maps Platform has a monthly free tier; you will only be charged if usage exceeds it.
4. Enable the required APIs:
   - Open the navigation menu → **APIs & Services** → **Library**.
   - Search for and enable **Map Tiles API**.
   - Search for and enable **Maps JavaScript API**.
   - Search for and enable **Places API (New)**.
   - Search for and enable **Geocoding API**.
   - Search for and enable **Maps Elevation API**.
   - Search for and enable **Routes API** (required for **Search route**).
   - Search for and enable **Roads API**.
5. Create an API key:
   - Go to **APIs & Services** → **Credentials**.
   - Click **Create credentials** → **API key**.
   - Optional but recommended: click the key and restrict it:
     - Under **Application restrictions**, add your dev/prod domains (e.g., `localhost:5173/*` for local development).
     - Under **API restrictions**, select only the APIs you enabled (**Map Tiles API**, **Maps JavaScript API**, **Places API (New)**, **Geocoding API**, **Maps Elevation API**, **Routes API**, and **Roads API**).
6. Copy the key and paste it into `config.json` as `googleApiKey`.

#### Google Maps APIs to enable

| API | Purpose in this project |
|---|---|
| **Map Tiles API** | Loads Google Photorealistic 3D Tiles in Cesium. |
| **Maps JavaScript API** | Loads the interactive 2D map and Street View panorama. |
| **Places API (New)** | Fetches nearby points of interest for waypoint origin selection. The code uses the new `google.maps.places.Place.searchNearby` API. |
| **Geocoding API** | Converts latitude/longitude to a human-readable address. |
| **Maps Elevation API** | Samples terrain elevation for route and altitude planning. |
| **Routes API** | Computes routes between waypoints (required for **Search route**). |
| **Roads API** | Snaps coordinates to the nearest road for accurate ground routes. |

### 2. Cesium ion access token

Required for Cesium to fetch terrain, imagery, and 3D tile endpoints.

#### Step-by-step

1. Go to Cesium ion: https://ion.cesium.com/
2. Sign up for a free account or log in.
3. Open **Access Tokens** from the top menu.
4. Click **Create token**.
   - Give it a name (e.g., `drone-navigation`).
   - Leave the default scopes or restrict them as needed.
5. Copy the generated token and paste it into `config.json` as `cesiumIonToken`.

### Final config file

Create `config.json` from the example:

```bash
cp config.example.json config.json
```

Then edit it:

```json
{
  "googleApiKey": "YOUR_GOOGLE_MAPS_API_KEY",
  "cesiumIonToken": "YOUR_CESIUM_ION_ACCESS_TOKEN",
  "_note": "The Google API key must have Map Tiles API, Maps JavaScript API, Places API (New), Geocoding API, Maps Elevation API, Routes API, and Roads API enabled for 3D aerial tiles, Street View, the 2D map toggle, waypoint POI lookup, address geocoding, elevation sampling, route computation, and road snapping."
}
```

Do not commit this file; it is already excluded by `.gitignore`.

## Running the app

```bash
cd client
npm install
npm run dev
```

Open http://localhost:5173.

- `/` — 3D aerial view with collision detection, auto takeoff/landing, flight/gimbal disks, and the HUD.
- `/map` — 2D Google Map centered on the drone.
- `/satellite` — 2D Google Satellite view.
- `/chat` — Mission-control chat interface.
- `/settings` — App settings (language, font, flight configuration).

Use the left and right sidebar docks to toggle disks, navigate between pages, take off/land, or open chat.

## Adding a plugin dock button

Plugins (or new pages) can register sidebar items through the shared dock registry:

```js
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';

const { registerLeft, registerRight } = useDockRegistry();

registerLeft({
  id: 'my-plugin',
  icon: 'MENU_CONTROL_STICK',
  title: 'My Plugin',
  active: false,
  onClick: () => { /* ... */ },
});
```

Items are reactive arrays, so registration/unregistration is reflected immediately in `AppDock.vue`.

## Build

```bash
cd client
npm run build
```

The output goes to `client/dist/`.

### Adding more Google APIs later

If a new feature needs another Google Maps Platform API (for example Geocoding API, Places API, or Roads API), follow the same steps:

1. Open the navigation menu → **APIs & Services** → **Library**.
2. Search for the API by name.
3. Click **Enable**.
4. Go to **APIs & Services** → **Credentials**, click your API key, and add the new API under **API restrictions**.
5. Rebuild and restart the app.

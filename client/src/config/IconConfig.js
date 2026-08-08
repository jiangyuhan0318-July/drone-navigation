// Configurable icon mapping.
// All SVG source files live in client/icons/ and are imported as raw strings
// via Vite's import.meta.glob. Add or update keys here to change the icons
// used across the application without touching components.

const svgModules = import.meta.glob('../../icons/*.svg', {
  query: '?raw',
  import: 'default',
  eager: true,
});

const pngModules = import.meta.glob('../../icons/*.png', {
  import: 'default',
  eager: true,
});

export const IconMap = {
  // Sidebar menu icons
  MENU_CONTROL_STICK: '../../icons/steer.svg',
  MENU_LOCATION: '../../icons/location.svg',
  MENU_3D_VIEW: '../../icons/drone.svg',
  MENU_SETTINGS: '../../icons/settings.svg',
  MENU_CAMERA: '../../icons/camera.svg',
  MENU_CHAT: '../../icons/chat.svg',
  MENU_TAKEOFF: '../../icons/takeoff.svg',
  MENU_LANDING: '../../icons/landing.svg',
  MENU_STOP: '../../icons/stop.svg',
  MENU_RED_STOP: '../../icons/red_stop.svg',
  MENU_ROUTER: '../../icons/router.svg',
  MENU_RECORDER: '../../icons/recorder.svg',
  MENU_CONTACTS: '../../icons/contacts.svg',
  MENU_GALLARY: '../../icons/gallary.svg',
  MENU_CUSTOMER_SERVICE: '../../icons/customer_service.svg',
  MENU_PHOTO: '../../icons/photo.svg',
  MENU_HELICOPTER: '../../icons/helicopter.svg',
  MENU_MESH: '../../icons/mesh.svg',
  MENU_MAP: '../../icons/map.svg',
  MENU_SATELLITE: '../../icons/satellite.svg',
  MENU_ARCHIVE: '../../icons/archive.svg',
  MENU_NOTE: '../../icons/note.svg',
  MENU_TOOL: '../../icons/tool.svg',
  MENU_FINGER_TAP: '../../icons/finger-tap.svg',
  MENU_REMOTE_CONTROLLER: '../../icons/remote_controller.svg',
  MENU_DRONE_PLUS: '../../icons/drone_plus.svg',
  MENU_LIVESTREAM_VIEWER: '../../icons/livestream_viewer.svg',
  MENU_LIVESTREAM_HOST: '../../icons/livestream_host.svg',
  MENU_WINDOW_SIZE: '../../icons/window_size.svg',
  MENU_ACCOUNT: '../../icons/account.svg',
  MENU_WALLET: '../../icons/wallet.svg',
  MENU_CONTENT: '../../icons/content.svg',
  MENU_SAVE: '../../icons/save.svg',

  // Auth form icons (password visibility toggle)
  PASSWORD_SHOW: '../../icons/view.svg',
  PASSWORD_HIDE: '../../icons/hide.svg',
  // Legacy alias, kept for backward compatibility
  MENU_GAMEPAD: '../../icons/control-stick.svg',

  // Joystick / flight control glyphs
  FLIGHT_MOVE: '../../icons/flight-move.svg',
  FLIGHT_ROTATE: '../../icons/flight-rotate.svg',
  FLIGHT_HEIGHT: '../../icons/flight-height.svg',

  // Camera / gimbal control glyphs
  CAMERA_ROTATE: '../../icons/camera-rotate.svg',
  CAMERA_PITCH: '../../icons/pitch-indicator.svg',

  // Chat icons
  CHAT_BACK: '../../icons/back.svg',
  CHAT_SEND: '../../icons/send.svg',
  CHAT_ATTACHMENT: '../../icons/attachment.svg',

  // Chat avatars
  AGENT_OPENCLAW: '../../icons/openclaw.svg',
  USER_PORTRAIT: '../../icons/portrait_photo.png',
};

/**
 * Resolve a configured icon key to its raw SVG markup.
 * @param {string} key - A key from IconMap.
 * @returns {string} The SVG markup, or an empty string if not found.
 */
export function getIconSvg(key) {
  const path = IconMap[key];
  return path && svgModules[path] ? svgModules[path] : '';
}

export function getIconImageUrl(key) {
  const path = IconMap[key];
  return path && pngModules[path] ? pngModules[path] : '';
}

/**
 * List all available icon keys. Useful for debugging or dynamic pickers.
 * @returns {string[]}
 */
export function getIconKeys() {
  return Object.keys(IconMap);
}

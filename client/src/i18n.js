import { createI18n } from 'vue-i18n';

/**
 * Decentralized i18n initializer.
 *
 * Translation files are placed next to their components using the naming
 * pattern `[ComponentName].[locale].i18n.json`.  This module uses Vite's
 * `import.meta.glob` to discover them automatically at build time and
 * aggregate them into the vue-i18n messages graph.
 *
 * Keys from each file are namespaced under the lower-cased component name
 * (derived from the file basename) to avoid collisions:
 *   e.g. `HUD.en.i18n.json` -> namespace `hud`, keys `hud.flight`, `hud.camera`.
 */

// Discover all translation JSON files anywhere under client/.
// Two patterns: one for src/ (views, components, 2d_map) and one for shared components/.
const modules = import.meta.glob(
  ['./**/*.i18n.json', '../components/**/*.i18n.json'],
  { eager: true }
);

/**
 * Build the aggregated messages object from discovered modules.
 *
 * Each key in `modules` looks like:
 *   `../../components/HUD.en.i18n.json`
 *
 * We extract:
 *   - component name: `HUD`  -> namespace `hud`
 *   - locale:         `en`
 */
function buildMessages() {
  const messages = {};

  for (const [path, mod] of Object.entries(modules)) {
    // path example: ../../components/HUD.en.i18n.json
    const filename = path.split('/').pop(); // HUD.en.i18n.json
    // Split on dots: ["HUD", "en", "i18n", "json"]
    const parts = filename.split('.');
    if (parts.length < 4) continue;

    const componentName = parts[0]; // e.g. "HUD", "_ViewComposer"
    const locale = parts[1];        // e.g. "en", "zh"

    // Derive a safe namespace: strip leading underscores, lowercase.
    const namespace = componentName.replace(/^_+/, '').toLowerCase();

    const translations = mod.default ?? mod;

    if (!messages[locale]) messages[locale] = {};
    if (!messages[locale][namespace]) messages[locale][namespace] = {};

    Object.assign(messages[locale][namespace], translations);
  }

  return messages;
}

const messages = buildMessages();

const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem('user-lang') || 'en',
  fallbackLocale: 'en',
  messages,
});

export default i18n;

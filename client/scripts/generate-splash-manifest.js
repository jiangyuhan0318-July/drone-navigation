/**
 * Splash video manifest generator
 *
 * Scans public/splash/*.mp4 and writes playlist.json with the discovered clips.
 * Run via `npm run prebuild` or `npm run predev` to keep the manifest in sync
 * with the actual video files.
 */
import { readdirSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SPLASH_DIR = join(__dirname, '..', 'public', 'splash');
const OUT = join(SPLASH_DIR, 'playlist.json');

const files = readdirSync(SPLASH_DIR)
  .filter(f => f.endsWith('.mp4'))
  .sort();

const firstClip = '/splash/video_00.mp4';
const otherClips = files
  .filter(f => f !== 'video_00.mp4')
  .map(f => `/splash/${f}`);

writeFileSync(OUT, JSON.stringify({ firstClip, otherClips }, null, 2));
console.log(`[splash-manifest] wrote ${otherClips.length + 1} clips to ${OUT}`);

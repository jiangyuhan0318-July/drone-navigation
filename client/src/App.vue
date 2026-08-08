<script setup>
import { RouterView } from 'vue-router';
import { watchEffect, onMounted } from 'vue';
import { useAppSettings } from '@shared-composables/useAppSettings.js';

const { settings } = useAppSettings();

/**
 * Google Fonts mapping.
 * Fonts not available locally on Linux are loaded via Google Fonts CDN.
 * Calibri is not on Google Fonts — Lato is the closest web-font substitute.
 * SimHei and PingFang SC are not on Google Fonts — they are only available
 * when the user has them installed locally.
 */
const GOOGLE_FONTS = {
  'Calibri':      'Lato',
  'Segoe UI':     'Roboto',
  'Tahoma':       'Open Sans',
  'Verdana':      'Lora',
  'Noto Sans SC': 'Noto Sans SC',
  'Microsoft YaHei': 'Noto Sans SC',
};

let loadedFonts = new Set();

function loadGoogleFont(family) {
  const gFont = GOOGLE_FONTS[family];
  if (!gFont || loadedFonts.has(gFont)) return;
  loadedFonts.add(gFont);
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(gFont)}:wght@300;400;500;600;700&display=swap`;
  document.head.appendChild(link);
}

onMounted(() => {
  /* Apply initial font-size to html root for rem cascading. */
  document.documentElement.style.fontSize = settings.fontSize;
  loadGoogleFont(settings.fontFamily);
});

watchEffect(() => {
  loadGoogleFont(settings.fontFamily);
});

/**
 * Build a CSS font-family stack that includes the Google Font fallback
 * so the font renders correctly even when not installed locally.
 */
function buildFontFamily(selected) {
  const gFont = GOOGLE_FONTS[selected];
  const parts = [`'${selected}'`];
  if (gFont && gFont !== selected) parts.push(`'${gFont}'`);
  parts.push('sans-serif');
  return parts.join(', ');
}
</script>

<template>
  <div
    id="app"
    :style="{
      fontFamily: buildFontFamily(settings.fontFamily),
      fontSize: settings.fontSize,
    }"
  >
    <RouterView />
  </div>
</template>

<style>
/* Reset that keeps the Vue overlay and Cesium canvas aligned. */
#app {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  pointer-events: none; /* let the active view decide where it captures input */
  font-family: Calibri, 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}
</style>

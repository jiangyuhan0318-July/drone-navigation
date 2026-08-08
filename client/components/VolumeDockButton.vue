<script setup>
// Dock-embedded volume control: the splash-style vertical pill, rendered as
// a right-sidebar dock item (the view pins it to the bottom with spacer
// items). Pure UI — the mute state and the target <video> element live in
// the parent view, which feeds them in via props/events. The slider drives
// the app-wide Media setting (useAppSettings singleton), same as before.
import { useAppSettings } from '@shared-composables/useAppSettings.js';
import audioIconUrl from '../icons/audio.svg?url';

defineProps({
  muted: { type: Boolean, default: true },
  title: { type: String, default: '' },
});
const emit = defineEmits(['toggleMute', 'volumeInput']);

const { settings } = useAppSettings();
</script>

<template>
  <div class="dock-volume" :title="title">
    <img
      :src="audioIconUrl"
      alt="Audio"
      class="dock-volume__icon"
      :style="{ opacity: muted ? 0.35 : 0.9 }"
      @click="emit('toggleMute')"
    />
    <input
      v-model.number="settings.audioVolume"
      type="range"
      class="dock-volume__slider"
      min="0"
      max="1"
      step="0.01"
      :aria-label="title"
      @input="emit('volumeInput')"
    />
  </div>
</template>

<style scoped>
/* Same look as the splash page volume widget (#splash-volume in style.css),
   sized to sit inside the 72px dock column. */
.dock-volume {
  display: flex;
  flex-direction: column;
  align-items: center;
  align-self: center; /* do not stretch to the dock column width */
  width: 44px;
  height: 116px;
  padding-top: 10px;
  background: rgba(0, 0, 0, 0.35);
  border-radius: 22px;
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.dock-volume__icon {
  width: 22px;
  height: 22px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: opacity 0.15s ease;
}

/* Vertical slider via the standard writing-mode (the splash slider's
   'appearance: slider-vertical' is deprecated). direction: rtl puts
   maximum volume at the top. */
.dock-volume__slider {
  writing-mode: vertical-lr;
  direction: rtl;
  width: 28px;
  height: 70px;
  margin: 0;
  cursor: pointer;
  opacity: 0.85;
  transition: opacity 0.2s ease;
}

.dock-volume__slider:hover {
  opacity: 1;
}
</style>

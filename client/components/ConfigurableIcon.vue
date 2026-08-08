<script setup>
import { computed } from 'vue';
import { getIconSvg, getIconImageUrl } from '@/config/IconConfig.js';

const props = defineProps({
  name: {
    type: String,
    required: true,
  },
  size: {
    type: [String, Number],
    default: 24,
  },
  color: {
    type: String,
    default: 'currentColor',
  },
});

const svgMarkup = computed(() => {
  const raw = getIconSvg(props.name);
  if (!raw) return '';
  // Strip fixed dimensions so the SVG scales to the container and inherits color.
  return raw
    .replace(/width="[^"]*"/gi, '')
    .replace(/height="[^"]*"/gi, '');
});

const imageUrl = computed(() => getIconImageUrl(props.name));

const isImage = computed(() => !!imageUrl.value);

const style = computed(() => ({
  width: typeof props.size === 'number' ? `${props.size}px` : props.size,
  height: typeof props.size === 'number' ? `${props.size}px` : props.size,
  color: props.color,
}));
</script>

<template>
  <span
    class="configurable-icon"
    :style="style"
  >
    <img
      v-if="isImage"
      :src="imageUrl"
      :alt="name"
      class="configurable-icon__img"
      draggable="false"
    />
    <span v-else v-html="svgMarkup"></span>
  </span>
</template>

<style scoped>
.configurable-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 0;
  pointer-events: none !important;
}

.configurable-icon :deep(svg) {
  width: 100%;
  height: 100%;
}

.configurable-icon__img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  -webkit-user-drag: none;
  user-select: none;
  pointer-events: none !important;
}
</style>

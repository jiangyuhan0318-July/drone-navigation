<script setup>
import DiskBase from './_DiskBase.vue';

defineProps({
  size: { type: Number, default: 224 },
  sensitivity: { type: Number, default: 1 },
  disabled: { type: Boolean, default: false },
});

defineEmits(['move', 'stop', 'modeChange']);
</script>

<template>
  <DiskBase
    mode="camera"
    :size="size"
    :sensitivity="sensitivity"
    enable-mode-cycle
    :disabled="disabled"
    @move="$emit('move', $event)"
    @stop="$emit('stop')"
    @modeChange="$emit('modeChange', $event)"
  />
</template>

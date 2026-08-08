<script setup>
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import ConfigurableIcon from './ConfigurableIcon.vue';

const props = defineProps({
  icon: { type: String, required: true },
  title: { type: String, default: '' },
  titleKey: { type: String, default: '' },
  active: { type: Boolean, default: false },
  danger: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  size: { type: Number, default: 32 },
});

const emit = defineEmits(['click']);
const { t } = useI18n();

const resolvedTitle = computed(() => {
  if (props.titleKey) return t(props.titleKey);
  return props.title;
});

function handleClick() {
  if (props.disabled) return;
  emit('click');
}
</script>

<template>
  <button
    class="dock-btn"
    :class="{ 'dock-btn--active': active, 'dock-btn--danger': danger }"
    :title="resolvedTitle"
    :disabled="disabled"
    @click="handleClick"
  >
    <ConfigurableIcon :name="icon" :size="size" />
  </button>
</template>

<style scoped>
.dock-btn {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  border: 1px solid rgba(156, 163, 175, 0.4);
  background: rgba(255, 255, 255, 1);
  backdrop-filter: blur(8px);
  color: rgba(55, 65, 81, 0.9);
  opacity: 0.5;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: opacity 0.15s ease, background 0.15s ease, transform 0.1s ease, border-color 0.15s ease, color 0.15s ease;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
}

.dock-btn:hover {
  opacity: 0.7;
}

.dock-btn--active {
  border-width: 2px;
  border-color: #4ade80;
  color: #4ade80;
}

.dock-btn--active.dock-btn--danger {
  border-color: #ef4444;
  color: #ef4444;
}

.dock-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.dock-btn:active:not(:disabled) {
  transform: scale(0.96);
}

@media (max-width: 768px) {
  .dock-btn {
    width: 48px;
    height: 48px;
  }
}
</style>

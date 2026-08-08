<script setup>
import DockButton from './DockButton.vue';
import { useWaypointPicker } from '@shared-composables/useWaypointPicker.js';

const props = defineProps({
  position: {
    type: String,
    default: 'left',
    validator: (value) => ['left', 'right'].includes(value),
  },
  items: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['itemClick']);

const { stopPicking, closePanel } = useWaypointPicker();

function handleItemClick(item) {
  if (item.disabled) return;
  // Any sidebar interaction cancels waypoint map-picking mode and hides the waypoint panel.
  stopPicking();
  closePanel();
  if (typeof item.onClick === 'function') {
    item.onClick();
  }
  emit('itemClick', item.id);
}
</script>

<template>
  <aside
    class="app-dock"
    :class="position === 'left' ? 'app-dock--left' : 'app-dock--right'"
  >
    <div class="app-dock__inner">
      <template v-for="item in items" :key="item.id">
        <!-- Custom component rendering (e.g., LanguageSelector) -->
        <component v-if="typeof item.render === 'function'" :is="item.render()" />
        <!-- Standard dock button -->
        <DockButton
          v-else
          :icon="item.icon"
          :title="item.title"
          :title-key="item.titleKey"
          :active="item.active"
          :danger="item.danger"
          :disabled="item.disabled"
          @click="handleItemClick(item)"
        />
      </template>
    </div>
  </aside>
</template>

<style scoped>
.app-dock {
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 72px;
  padding: 8px 0;
  z-index: 10;
  pointer-events: auto;
}

.app-dock--left {
  align-items: flex-start;
}

.app-dock--right {
  align-items: flex-end;
}

.app-dock__inner {
  display: flex;
  flex-direction: column;
  gap: 16px;
  /* Span the full dock height so that views can register invisible
     flex-spacer items (render: () => h('div', { style: 'flex: 1 1 auto' }))
     to pin trailing items (e.g. the volume pill) to the very bottom.
     justify-content: center keeps the classic centered look for pages
     that register no spacers — a no-op when spacers absorb the space. */
  height: 100%;
  justify-content: center;
}

@media (max-width: 768px) {
  .app-dock {
    width: 56px;
  }
}
</style>

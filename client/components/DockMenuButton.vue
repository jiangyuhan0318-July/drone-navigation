<script setup>
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue';
import DockButton from './DockButton.vue';
import PageMenu from './PageMenu.vue';
import { useWaypointPicker } from '@shared-composables/useWaypointPicker.js';

const props = defineProps({
  icon: { type: String, required: true },
  title: { type: String, default: '' },
  titleKey: { type: String, default: '' },
  pages: { type: Array, default: () => [] },
  onBeforeOpen: { type: Function, default: null },
});

const emit = defineEmits(['navigate']);

const isOpen = ref(false);
const wrapperRef = ref(null);
const menuRef = ref(null);
const menuStyle = ref({});

const EDGE_MARGIN = 24;

const { stopPicking, closePanel } = useWaypointPicker();

function computeMenuPosition() {
  if (!wrapperRef.value || !menuRef.value) return;

  const btnRect = wrapperRef.value.getBoundingClientRect();
  const menuEl = menuRef.value.$el || menuRef.value;
  const menuHeight = menuEl.offsetHeight;
  const vh = window.innerHeight;

  // Center menu on button
  const btnCenter = btnRect.top + btnRect.height / 2;
  let top = btnCenter - menuHeight / 2;

  // Clamp to viewport with margin
  const minTop = EDGE_MARGIN;
  const maxTop = vh - menuHeight - EDGE_MARGIN;
  top = Math.max(minTop, Math.min(maxTop, top));

  // Convert to wrapper-local coordinates
  const localTop = top - btnRect.top;
  menuStyle.value = { top: `${localTop}px` };
}

function toggleMenu() {
  if (!isOpen.value) {
    if (props.onBeforeOpen) {
      props.onBeforeOpen();
    }
    stopPicking();
    closePanel();
  }
  isOpen.value = !isOpen.value;
}

function handleClickOutside(e) {
  if (wrapperRef.value && !wrapperRef.value.contains(e.target)) {
    isOpen.value = false;
  }
}

function handleNavigate(page) {
  isOpen.value = false;
  emit('navigate', page);
}

watch(isOpen, async (open) => {
  if (open) {
    await nextTick();
    computeMenuPosition();
  }
});

onMounted(() => {
  document.addEventListener('pointerdown', handleClickOutside);
});

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleClickOutside);
});
</script>

<template>
  <div ref="wrapperRef" class="dock-menu-wrapper">
    <DockButton
      :icon="icon"
      :title="title"
      :title-key="titleKey"
      :active="isOpen"
      @click="toggleMenu"
    />
    <Transition name="menu-fade">
      <PageMenu
        v-if="isOpen"
        ref="menuRef"
        :pages="pages"
        :style="menuStyle"
        @navigate="handleNavigate"
      />
    </Transition>
  </div>
</template>

<style scoped>
.dock-menu-wrapper {
  position: relative;
}

.dock-menu-wrapper > :deep(.page-menu) {
  position: absolute;
  left: calc(100% + 8px);
  z-index: 100;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
}

.menu-fade-enter-active,
.menu-fade-leave-active {
  transition: opacity 0.15s ease;
}

.menu-fade-enter-from,
.menu-fade-leave-to {
  opacity: 0;
}
</style>

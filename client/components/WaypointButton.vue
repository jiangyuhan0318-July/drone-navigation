<script setup>
import DockButton from '@shared/DockButton.vue';
import WaypointPanel from './WaypointPanel.vue';
import { useWaypointPicker } from '@shared-composables/useWaypointPicker.js';

const props = defineProps({
  onBeforeOpen: { type: Function, default: null },
  onSearchWaypoints: { type: Function, default: null },
  onSearchRoutes: { type: Function, default: null },
});

const {
  isPanelOpen,
  openPanel,
  closePanel,
  stopPicking,
  startPicking,
  activeWaypointId,
  setInputFocused,
} = useWaypointPicker();

function toggle() {
  if (isPanelOpen.value) {
    closePanel();
  } else {
    if (props.onBeforeOpen) {
      props.onBeforeOpen();
    }
    stopPicking();
    openPanel();
  }
}

function handlePanelClose() {
  // Close the panel and enter map-picking mode. The panel will be reopened
  // automatically after the user picks a location on the map.
  // If no waypoint is active, make the origin input the active target.
  if (activeWaypointId.value === null) {
    setInputFocused(true);
  }
  closePanel();
  startPicking();
}
</script>

<template>
  <div class="waypoint-btn-wrapper">
    <DockButton
      icon="MENU_LOCATION"
      title-key="aerialview.waypoint"
      :active="isPanelOpen"
      @click="toggle"
    />
    <Transition name="waypoint-fade">
      <WaypointPanel
        v-if="isPanelOpen"
        @close="handlePanelClose"
        @searchWaypoints="props.onSearchWaypoints"
        @searchRoutes="props.onSearchRoutes"
      />
    </Transition>
  </div>
</template>

<style scoped>
.waypoint-btn-wrapper {
  position: relative;
}

.waypoint-fade-enter-active,
.waypoint-fade-leave-active {
  transition: opacity 0.15s ease;
}

.waypoint-fade-enter-from,
.waypoint-fade-leave-to {
  opacity: 0;
}
</style>

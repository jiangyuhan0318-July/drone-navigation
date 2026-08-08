<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { useI18n } from 'vue-i18n';
import ConfigurableIcon from '@shared/ConfigurableIcon.vue';
import { useWaypointPicker } from '@shared-composables/useWaypointPicker.js';

const { t } = useI18n();

const emit = defineEmits(['close', 'searchWaypoints', 'searchRoutes']);

const {
  nearbyPois,
  selectedPoi,
  selectPoi,
  waypoints: destinations,
  originDraft,
  activeWaypointId,
  inputFocused,
  isPicking,
  routeResult,
  routeError,
  setActiveWaypointId,
  setInputFocused,
  commitOrigin,
  clearRouteResult,
  setRouteError,
  clearRouteError,
} = useWaypointPicker();

const containerRef = ref(null);
const leftPanelWidth = ref(50);
const isDragging = ref(false);

function onFingerTapClick() {
  emit('close');
}

function onInputFocus(id) {
  setActiveWaypointId(id);
  setInputFocused(true);
}

function onSearchRoutes() {
  clearRouteError();
  if (destinations.value.length < 2) {
    setRouteError(t('aerialview.waypoint_route_need_more'));
    return;
  }
  emit('searchRoutes');
}

function onPoiClick(poi) {
  const name = poi.name || '';
  if (activeWaypointId.value === null) {
    originDraft.value = name;
  } else {
    const wp = destinations.value.find((w) => w.id === activeWaypointId.value);
    if (wp) wp.name = name;
  }
  selectPoi(poi);
}

function deleteActiveWaypoint() {
  if (!inputFocused.value) return;
  if (activeWaypointId.value === null) {
    originDraft.value = '';
  } else {
    const index = destinations.value.findIndex((w) => w.id === activeWaypointId.value);
    if (index !== -1) {
      destinations.value.splice(index, 1);
    }
    activeWaypointId.value = null;
  }
  setInputFocused(false);
}

function startDrag(e) {
  isDragging.value = true;
  e.preventDefault();
}

function onDrag(e) {
  if (!isDragging.value || !containerRef.value) return;
  const rect = containerRef.value.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const pct = (x / rect.width) * 100;
  leftPanelWidth.value = Math.max(25, Math.min(75, pct));
}

function stopDrag() {
  isDragging.value = false;
}

onMounted(() => {
  document.addEventListener('mousemove', onDrag);
  document.addEventListener('mouseup', stopDrag);

  // Restore the active input visual state when the panel is reopened.
  // If a previously active waypoint no longer exists, fall back to the origin input.
  if (activeWaypointId.value !== null) {
    const wp = destinations.value.find((w) => w.id === activeWaypointId.value);
    if (!wp) {
      setActiveWaypointId(null);
    }
  }
  setInputFocused(true);
});

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onDrag);
  document.removeEventListener('mouseup', stopDrag);
  commitOrigin();
});
</script>

<template>
  <div ref="containerRef" class="waypoint-panel">
    <div
      class="waypoint-panel__col waypoint-panel__col--left"
      :style="{ width: `${leftPanelWidth}%` }"
    >
      <div class="waypoint-panel__scroll">
        <div class="waypoint-section">
          <h3 class="waypoint-section__title">{{ t('aerialview.waypoint_destination') }}</h3>
          <div class="waypoint-list">
            <input
              v-for="wp in destinations"
              :key="wp.id"
              v-model="wp.name"
              type="text"
              class="waypoint-list__input"
              :class="{ 'waypoint-list__input--active': activeWaypointId === wp.id && inputFocused }"
              @focus="onInputFocus(wp.id)"
            />
          </div>
        </div>

        <div class="waypoint-section">
          <div class="waypoint-origin">
            <input
              v-model="originDraft"
              type="text"
              class="waypoint-origin__input"
              :class="{ 'waypoint-origin__input--active': activeWaypointId === null && inputFocused }"
              :placeholder="t('aerialview.waypoint_origin_placeholder')"
              @focus="onInputFocus(null)"
              @keydown.enter.prevent="commitOrigin"
            />
            <button
              class="waypoint-origin__tag"
              :class="{ 'waypoint-origin__tag--active': isPicking }"
              :title="t('aerialview.waypoint_tag_title')"
              @click.stop="onFingerTapClick"
            >
              <ConfigurableIcon name="MENU_FINGER_TAP" :size="20" />
            </button>
          </div>
        </div>
      </div>

      <button class="waypoint-action waypoint-action--primary waypoint-action--takeoff">
        {{ t('aerialview.waypoint_go_to_origin') }}
      </button>
    </div>

    <div class="waypoint-panel__divider" @mousedown="startDrag" />

    <div class="waypoint-panel__col waypoint-panel__col--right">
      <div class="waypoint-actions">
        <button class="waypoint-action waypoint-action--primary">
          {{ t('aerialview.waypoint_increase_index') }}
        </button>
        <button class="waypoint-action waypoint-action--primary" @click="deleteActiveWaypoint">
          {{ t('aerialview.waypoint_delete') }}
        </button>
        <button class="waypoint-action waypoint-action--primary" @click="emit('searchWaypoints')">
          {{ t('aerialview.waypoint_search_waypoint') }}
        </button>
        <button class="waypoint-action waypoint-action--primary" @click="onSearchRoutes">
          {{ t('aerialview.waypoint_search_routes') }}
        </button>
      </div>

      <div class="waypoint-detail">
        <p v-if="routeError" class="waypoint-warning">{{ routeError }}</p>

        <div v-else-if="routeResult" class="waypoint-route">
          <div class="waypoint-route__summary">
            <span class="waypoint-route__total">
              {{ routeResult.routes[0].legs.reduce((sum, leg) => sum + (leg.distance?.value || 0), 0) / 1000 }} km
            </span>
            <span class="waypoint-route__total">
              {{ Math.round(routeResult.routes[0].legs.reduce((sum, leg) => sum + (leg.duration?.value || 0), 0) / 60) }} min
            </span>
          </div>
          <ol class="waypoint-route__list">
            <li
              v-for="(leg, legIndex) in routeResult.routes[0].legs"
              :key="legIndex"
              class="waypoint-route__leg"
            >
              <div class="waypoint-route__leg-header">
                <strong>{{ leg.start_address }}</strong> → {{ leg.end_address }}
                <span class="waypoint-route__leg-meta">{{ leg.distance?.text }} · {{ leg.duration?.text }}</span>
              </div>
              <ol class="waypoint-route__steps">
                <li
                  v-for="(step, stepIndex) in leg.steps"
                  :key="stepIndex"
                  class="waypoint-route__step"
                >
                  <span class="waypoint-route__instruction" v-html="step.instructions"></span>
                  <span class="waypoint-route__step-meta">{{ step.distance?.text }}</span>
                </li>
              </ol>
            </li>
          </ol>
        </div>

        <div v-else class="waypoint-poi">
          <ul v-if="nearbyPois.length" class="waypoint-poi__list">
            <li
              v-for="poi in nearbyPois"
              :key="poi.place_id"
              class="waypoint-poi__item"
              :class="{ 'waypoint-poi__item--active': selectedPoi?.place_id === poi.place_id }"
            >
              <button class="waypoint-poi__header" @click="onPoiClick(poi)">
                <span class="waypoint-poi__name">{{ poi.name }}</span>
                <span class="waypoint-poi__expand">{{ selectedPoi?.place_id === poi.place_id ? '−' : '+' }}</span>
              </button>
              <div v-if="selectedPoi?.place_id === poi.place_id" class="waypoint-poi__body">
                <p v-if="poi.vicinity" class="waypoint-poi__row">
                  <strong>{{ t('aerialview.waypoint_poi_vicinity') }}:</strong> {{ poi.vicinity }}
                </p>
                <p v-if="poi.rating" class="waypoint-poi__row">
                  <strong>{{ t('aerialview.waypoint_poi_rating') }}:</strong> {{ poi.rating }} / 5
                </p>
                <p v-if="poi.types?.length" class="waypoint-poi__row">
                  <strong>{{ t('aerialview.waypoint_poi_types') }}:</strong> {{ poi.types.join(', ') }}
                </p>
              </div>
            </li>
          </ul>
          <p v-else class="waypoint-poi__empty">{{ t('aerialview.waypoint_poi_no_results') }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.waypoint-panel {
  position: fixed;
  top: 5vh;
  bottom: 5vh;
  left: calc(24px + 56px + 8px);
  right: calc(24px + 56px + 8px);
  z-index: 100;
  display: flex;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(6px);
  border: 2px solid rgba(255, 255, 255, 0.45);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2), inset 0 0 20px rgba(255, 255, 255, 0.08);
  color: #374151;
  font-size: 0.9rem;
  overflow: hidden;
}

@media (max-width: 768px) {
  .waypoint-panel {
    left: calc(24px + 48px + 8px);
    right: calc(24px + 48px + 8px);
  }
}

.waypoint-panel__col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;
  overflow: auto;
}

.waypoint-panel__col--left {
  flex: 0 0 auto;
  overflow: hidden;
}

.waypoint-panel__col--right {
  flex: 1 1 0;
  padding-right: 8px;
  overflow: scroll;
}

.waypoint-panel__scroll {
  flex: 1 1 auto;
  min-height: 0;
  min-width: 0;
  padding-right: 8px;
  overflow: scroll;
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
}

.waypoint-panel__scroll::-webkit-scrollbar,
.waypoint-panel__col--right::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.waypoint-panel__scroll::-webkit-scrollbar-track,
.waypoint-panel__col--right::-webkit-scrollbar-track {
  background: transparent;
}

.waypoint-panel__scroll::-webkit-scrollbar-thumb,
.waypoint-panel__col--right::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 3px;
}

.waypoint-panel__col--right {
  scrollbar-width: thin;
  scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
}

.waypoint-panel__divider {
  width: 4px;
  flex: 0 0 auto;
  background: rgba(0, 0, 0, 0.12);
  margin: 4px 0;
  border-radius: 2px;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.waypoint-panel__divider:hover {
  background: rgba(0, 0, 0, 0.25);
}

.waypoint-section__title {
  margin: 0 0 6px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  text-align: center;
  color: #4b5563;
}

.waypoint-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.waypoint-list__input {
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: #ffffff;
  color: #374151;
  font-weight: 400;
  font-size: 0.9rem;
  outline: none;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.08);
  transition: background 0.15s ease, border-color 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.waypoint-list__input::placeholder {
  color: #9ca3af;
}

.waypoint-list__input:focus {
  background: #e5e7eb;
  border-color: rgba(0, 0, 0, 0.2);
}

.waypoint-list__input--active {
  background: #e5e7eb;
  border-color: rgba(0, 0, 0, 0.2);
}

.waypoint-origin {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
}

.waypoint-origin__input {
  flex: 1 1 auto;
  min-width: 0;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: #ffffff;
  color: #374151;
  font-size: 0.85rem;
  font-weight: 400;
  outline: none;
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.08);
  transition: background 0.15s ease, border-color 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.waypoint-origin__input::placeholder {
  color: #9ca3af;
}

.waypoint-origin__input:focus,
.waypoint-origin__input--active {
  background: #e5e7eb;
  border-color: rgba(0, 0, 0, 0.2);
}

.waypoint-origin__tag {
  --tag-color-from: #f9fafb;
  --tag-color-to: #374151;

  flex: 0 0 auto;
  width: calc(0.85rem + 25px);
  height: calc(0.85rem + 25px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--tag-color-from);
  cursor: pointer;
  animation: tag-flash 1s ease-in-out infinite;
  transition: opacity 0.15s ease, border-color 0.15s ease;
}

.waypoint-origin__tag--active {
  --tag-color-from: #22c55e;
  --tag-color-to: #15803d;
  border-color: #22c55e;
}

.waypoint-origin__tag :deep(.configurable-icon) {
  width: 100% !important;
  height: 100% !important;
}

.waypoint-origin__tag:hover {
  opacity: 0.8;
}

.waypoint-origin__tag:active {
  --tag-color-from: #22c55e;
  --tag-color-to: #22c55e;
}

@keyframes tag-flash {
  0%, 100% {
    opacity: 1;
    color: var(--tag-color-from);
  }
  50% {
    opacity: 0.7;
    color: var(--tag-color-to);
  }
}

.waypoint-actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.waypoint-action {
  width: 100%;
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: #ffffff;
  color: #374151;
  font-size: 0.85rem;
  font-weight: 600;
  text-align: center;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.waypoint-action:hover {
  background: #e5e7eb;
}

.waypoint-action--takeoff {
  flex: 0 0 auto;
}

.waypoint-action--primary {
  background: #e5e7eb;
  border-color: rgba(0, 0, 0, 0.12);
  color: #374151;
}

.waypoint-action--primary:hover {
  background: #d1d5db;
}

.waypoint-action--primary:active {
  background: rgba(74, 222, 128, 0.18);
  border-color: rgba(74, 222, 128, 0.55);
  color: #22c55e;
}

.waypoint-detail {
  padding: 12px;
  border-radius: 6px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: #ffffff;
}

.waypoint-poi {
  width: 100%;
}

.waypoint-poi__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.waypoint-poi__item {
  flex: 0 0 auto;
  min-height: 2.25rem;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  overflow: hidden;
  background: #ffffff;
}

.waypoint-poi__item--active {
  border-color: rgba(74, 222, 128, 0.55);
}

.waypoint-poi__header {
  width: 100%;
  height: 2.25rem;
  min-height: 2.25rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px;
  border: none;
  background: transparent;
  color: #374151;
  font-size: 0.8rem;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.waypoint-poi__header:hover {
  background: #f3f4f6;
}

.waypoint-poi__name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.waypoint-poi__expand {
  flex: 0 0 auto;
  color: #9ca3af;
  font-weight: 700;
}

.waypoint-poi__body {
  padding: 6px 8px;
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  background: #f9fafb;
  font-size: 0.75rem;
  color: #4b5563;
}

.waypoint-poi__row {
  margin: 0 0 4px;
}

.waypoint-poi__row:last-child {
  margin-bottom: 0;
}

.waypoint-poi__row strong {
  color: #374151;
}

.waypoint-poi__empty {
  margin: 0;
  padding: 12px 0;
  text-align: center;
  color: #9ca3af;
  font-size: 0.8rem;
  min-height: calc(2.55rem + 48px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.waypoint-warning {
  margin: 0 0 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(220, 20, 60, 0.1);
  border: 1px solid rgba(220, 20, 60, 0.25);
  color: #b91c1c;
  font-size: 0.8rem;
  text-align: center;
}

.waypoint-route {
  width: 100%;
}

.waypoint-route__summary {
  display: flex;
  gap: 12px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
}

.waypoint-route__total {
  font-weight: 700;
  color: #374151;
  font-size: 0.85rem;
}

.waypoint-route__list,
.waypoint-route__steps {
  list-style: none;
  margin: 0;
  padding: 0;
}

.waypoint-route__leg {
  margin-bottom: 10px;
}

.waypoint-route__leg-header {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-bottom: 6px;
  font-size: 0.8rem;
  color: #374151;
}

.waypoint-route__leg-meta {
  font-size: 0.75rem;
  color: #6b7280;
}

.waypoint-route__step {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 4px 0;
  border-bottom: 1px solid rgba(0, 0, 0, 0.06);
  font-size: 0.75rem;
  color: #4b5563;
}

.waypoint-route__step:last-child {
  border-bottom: none;
}

.waypoint-route__instruction {
  flex: 1 1 auto;
  min-width: 0;
}

.waypoint-route__instruction :deep(b) {
  color: #374151;
}

.waypoint-route__step-meta {
  flex: 0 0 auto;
  color: #9ca3af;
  white-space: nowrap;
}
</style>

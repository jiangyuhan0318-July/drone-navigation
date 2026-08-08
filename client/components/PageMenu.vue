<script setup>
import { ref, computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRouter, useRoute } from 'vue-router';

const props = defineProps({
  pages: {
    type: Array,
    default: () => [],
  },
});

const emit = defineEmits(['navigate']);

const { t } = useI18n();
const router = useRouter();
const route = useRoute();

const flashId = ref(null);
let flashTimer = null;

const activeRoute = computed(() => route.path);

function resolveName(page) {
  if (page.nameKey) return t(page.nameKey);
  return page.name;
}

function handlePageClick(page) {
  // Pages without a route do nothing when clicked
  if (!page.route) return;

  if (page.route === route.path) {
    emit('navigate', page);
    return;
  }

  // Flash the selected item yellow
  flashId.value = page.id;
  clearTimeout(flashTimer);
  flashTimer = setTimeout(() => {
    flashId.value = null;
    router.push(page.route);
    emit('navigate', page);
  }, 600);
}

function isActive(page) {
  return page.route === activeRoute.value;
}
</script>

<template>
  <div class="page-menu">
    <button
      v-for="page in pages"
      :key="page.id"
      class="page-menu-item"
      :class="{
        'page-menu-item--active': isActive(page),
        'page-menu-item--flash': flashId === page.id,
      }"
      @click="handlePageClick(page)"
    >
      {{ resolveName(page) }}
    </button>
  </div>
</template>

<style scoped>
.page-menu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 6px;
  min-width: 140px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.18);
  backdrop-filter: blur(6px);
  border: 2px solid rgba(255, 255, 255, 0.45);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2), inset 0 0 20px rgba(255, 255, 255, 0.08);
}

.page-menu-item {
  display: block;
  width: 100%;
  padding: 8px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
  font-size: 0.9rem;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
  white-space: nowrap;
}

.page-menu-item:hover {
  background: rgba(255, 255, 255, 0.1);
}

.page-menu-item--active {
  background: rgba(255, 255, 255, 0.12);
}

.page-menu-item--flash {
  color: #4ade80 !important;
}
</style>

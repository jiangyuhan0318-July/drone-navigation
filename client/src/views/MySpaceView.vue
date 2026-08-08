<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted, h } from 'vue';
import { useI18n } from 'vue-i18n';
import { useSettingsSave } from '@shared-composables/useSettingsSave.js';
import { useRoute, useRouter } from 'vue-router';
import ViewComposer from '@shared/_ViewComposer.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import DockMenuButton from '@shared/DockMenuButton.vue';
import AccountLoginPanel from '@/views/AccountLoginPanel.vue';

const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const { leftItems, registerLeft, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { saveNotice, saveSettings } = useSettingsSave();

/* ─── Left-column width drag (same geometry as Extensions/Settings) ─── */
const LEFT_MIN = 180;
const LEFT_MAX = 400;
const LEFT_DEFAULT = 220;
const leftWidth = ref(LEFT_DEFAULT);
const isDragging = ref(false);

function onDividerPointerDown(e) {
  e.preventDefault();
  isDragging.value = true;
  document.addEventListener('pointermove', onDividerPointerMove);
  document.addEventListener('pointerup', onDividerPointerUp);
}

function onDividerPointerMove(e) {
  if (!isDragging.value) return;
  const panel = document.querySelector('.myspace-page');
  if (!panel) return;
  const rect = panel.getBoundingClientRect();
  const x = e.clientX - rect.left;
  leftWidth.value = Math.min(LEFT_MAX, Math.max(LEFT_MIN, x));
}

function onDividerPointerUp() {
  isDragging.value = false;
  document.removeEventListener('pointermove', onDividerPointerMove);
  document.removeEventListener('pointerup', onDividerPointerUp);
}

/* ─── Subpages + hard-coded fake menus (testing phase) ─── */
// Account / Wallet / Content switch in place with an Extensions-style layout
// (left nav + draggable divider + right panel with breadcrumb, no search box).
// The Settings dock button is the relocated entrance of the /settings page.
const SUBPAGES = [
  {
    id: 'account',
    icon: 'MENU_ACCOUNT',
    labelKey: 'aerialview.subpage_account',
    menu: [
      { id: 'login', labelKey: 'aerialview.myspace_menu_login' },
      { id: 'avatar', labelKey: 'aerialview.myspace_menu_avatar' },
    ],
  },
  {
    id: 'wallet',
    icon: 'MENU_WALLET',
    labelKey: 'aerialview.subpage_wallet',
    menu: [
      { id: 'balance', labelKey: 'aerialview.myspace_menu_balance' },
      { id: 'topup', labelKey: 'aerialview.myspace_menu_topup' },
      { id: 'history', labelKey: 'aerialview.myspace_menu_history' },
    ],
  },
  {
    id: 'content',
    icon: 'MENU_CONTENT',
    labelKey: 'aerialview.subpage_content',
    menu: [
      { id: 'poi', labelKey: 'aerialview.myspace_menu_poi' },
      { id: 'routes', labelKey: 'aerialview.myspace_menu_routes' },
      { id: 'indoor', labelKey: 'aerialview.myspace_menu_indoor' },
    ],
  },
];

const activeSubpage = ref('account');

// Each subpage remembers its own selected menu item.
const selectedMenus = reactive({
  account: 'login',
  wallet: 'balance',
  content: 'poi',
});

const currentSubpage = computed(() => SUBPAGES.find((s) => s.id === activeSubpage.value));
const currentMenu = computed(() => currentSubpage.value?.menu || []);
const selectedMenuId = computed(() => selectedMenus[activeSubpage.value]);

const breadcrumb = computed(() => {
  const sub = currentSubpage.value;
  if (!sub) return t('aerialview.page_myspace');
  const item = sub.menu.find((m) => m.id === selectedMenus[sub.id]);
  return `${t('aerialview.page_myspace')} > ${t(sub.labelKey)}${item ? ' > ' + t(item.labelKey) : ''}`;
});

function selectMenu(id) {
  selectedMenus[activeSubpage.value] = id;
}

/* ─── Deep-link support: /myspace?sub=wallet (used by the Settings page dock) ─── */
function applyQueryParams() {
  const sub = route.query.sub;
  if (sub && SUBPAGES.some((s) => s.id === sub)) {
    activeSubpage.value = sub;
  }
}

watch(() => route.query, applyQueryParams);

// Keep the subpage selector buttons in sync with the active subpage.
watch(activeSubpage, (val) => {
  for (const sub of SUBPAGES) {
    const btn = leftItems.find((i) => i.id === `subpage_${sub.id}`);
    if (btn) btn.active = val === sub.id;
  }
});

/* ─── Page + dock registration ─── */
onMounted(() => {
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  // Invisible flex spacers: the top/bottom pair splits the free space
  // equally, so the 5 navigation buttons stay vertically CENTERED while
  // the Save button (registered last) is pinned to the very bottom.
  registerLeft({ id: 'dock_spacer_top', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerLeft({
    id: 'router',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'aerialview.pages',
      pages,
    }),
  });

  for (const sub of SUBPAGES) {
    registerLeft({
      id: `subpage_${sub.id}`,
      icon: sub.icon,
      titleKey: sub.labelKey,
      active: activeSubpage.value === sub.id,
      onClick: () => { activeSubpage.value = sub.id; },
    });
  }

  // The Settings page keeps its own route/layout — this button only moves
  // its entrance from the Pages popup into the My Space dock.
  registerLeft({
    id: 'subpage_settings',
    icon: 'MENU_TOOL',
    titleKey: 'aerialview.subpage_settings',
    onClick: () => { router.push('/settings'); },
  });

  // Save button pinned to the VERY BOTTOM of the left dock: the invisible
  // flex spacer absorbs the free space above it (same trick as the
  // RealDroneView volume pill). Action is a testing-phase stub for now.
  registerLeft({ id: 'dock_spacer_bottom', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerLeft({
    id: 'save',
    icon: 'MENU_SAVE',
    titleKey: 'aerialview.save',
    onClick: () => { saveSettings(); },
  });

  applyQueryParams();
});

onUnmounted(() => {
  clear();
  unregisterPage('aerial');
  unregisterPage('realdrone');
  unregisterPage('map');
  unregisterPage('myspace');
  unregisterPage('chat');
  unregisterPage('extensions');
});
</script>

<template>
  <ViewComposer
    :left-items="leftItems"
    :right-items="[]"
    :show-flight="false"
    :show-camera="false"
    :show-hud="false"
    :flight="{ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }"
    :camera="{ mode: '-', yaw: 0, pitch: 0, roll: 0 }"
  >
    <template #background>
      <div class="myspace-page">
        <!-- Left sidebar: fake menu of the active subpage -->
        <nav
          class="myspace-sidebar"
          :style="{ width: leftWidth + 'px' }"
        >
          <div
            v-for="item in currentMenu"
            :key="item.id"
            class="myspace-sidebar__item"
            :class="{ 'myspace-sidebar__item--active': selectedMenuId === item.id }"
            @click="selectMenu(item.id)"
          >
            {{ t(item.labelKey) }}
          </div>
        </nav>

        <!-- Divider (draggable) -->
        <div
          class="myspace-divider"
          @pointerdown="onDividerPointerDown"
        />

        <!-- Right content area -->
        <div class="myspace-content">
          <!-- Save-flow notice (useSettingsSave): saved / login reminder -->
          <div
            v-if="saveNotice"
            class="save-notice"
            :class="`save-notice--${saveNotice}`"
          >
            {{ t(`aerialview.save_notice_${saveNotice}`) }}
          </div>

          <!-- Breadcrumb -->
          <div class="myspace-breadcrumb">{{ breadcrumb }}</div>

          <!-- Separator -->
          <div class="myspace-separator" />

          <!-- Subpage body (Account -> Login is live; others land later) -->
          <div class="myspace-body">
            <AccountLoginPanel
              v-if="activeSubpage === 'account' && selectedMenuId === 'login'"
            />
          </div>
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.myspace-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
}

/* ─── Left sidebar ─── */
.myspace-sidebar {
  flex-shrink: 0;
  padding: 20px 0;
  overflow-y: auto;
  background: #f5f5f7;
}

.myspace-sidebar__item {
  padding: 9px 20px;
  font-size: 0.9rem;
  font-weight: 500;
  color: #1d1d1f;
  cursor: pointer;
  border-radius: 6px;
  margin: 2px 8px;
  transition: background 0.15s ease, color 0.15s ease;
}

.myspace-sidebar__item:hover {
  background: rgba(0, 0, 0, 0.04);
}

.myspace-sidebar__item--active {
  background: #007aff;
  color: #ffffff;
}

.myspace-sidebar__item--active:hover {
  background: #0066d6;
}

/* ─── Divider ─── */
.myspace-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.myspace-divider:hover,
.myspace-divider:active {
  background: #007aff;
}

/* ─── Right content ─── */
.myspace-content {
  flex: 1;
  min-width: 0;
  padding: 24px 32px;
  overflow-y: auto;
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.myspace-breadcrumb {
  font-size: 0.8rem;
  font-weight: 500;
  color: #6e6e73;
  margin-bottom: 16px;
}

/* Save-flow notice banner (useSettingsSave) */
.save-notice {
  margin-bottom: 16px;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.4;
}
.save-notice--saved,
.save-notice--login_required {
  background: #eef7ee;
  color: #1e7a1e;
  border: 1px solid #cbe8cb;
}
.save-notice--save_failed {
  background: #fff0f0;
  color: #c41e1e;
  border: 1px solid #ffd2d2;
}

.myspace-separator {
  height: 1px;
  background: #e5e5ea;
  margin-bottom: 1.5em;
  flex-shrink: 0;
}

.myspace-body {
  flex: 1;
  min-height: 0;
}
</style>

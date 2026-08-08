<script setup>
import { ref, onMounted, onUnmounted, h, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useSettingsSave } from '@shared-composables/useSettingsSave.js';
import { useRouter } from 'vue-router';
import ViewComposer from '@shared/_ViewComposer.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useProxyConfig } from '@shared-composables/useProxyConfig.js';
import DockMenuButton from '@shared/DockMenuButton.vue';
import { useAppSettings } from '@shared-composables/useAppSettings.js';

const { t, locale } = useI18n();
const router = useRouter();
const { leftItems, registerLeft, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { saveNotice, saveSettings } = useSettingsSave();
const { httpProxy, httpsProxy, noProxy } = useProxyConfig();
const { settings, setFontFamily, setFontSize, setTakeoffAltitude, setSafetyBuffer, setDefaultLat, setDefaultLon, setDefaultAlt, setDefaultYaw, setDefaultPitch, setDefaultRoll, setEnterpriseProxy, resetFontDefaults, resetFlightDefaults, resetMediaDefaults, resetNetworkDefaults } = useAppSettings();

/* ─── Left-column width drag ─── */
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
  const panel = document.querySelector('.settings-page');
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

/* ─── Selected setting ─── */
const selectedId = ref('language');

const SETTINGS_LIST = [
  { id: 'language', labelKey: 'aerialview.settings_language' },
  { id: 'font', labelKey: 'aerialview.settings_font' },
  { id: 'media', labelKey: 'aerialview.settings_media' },
  { id: 'network', labelKey: 'aerialview.settings_network' },
  { id: 'flight', labelKey: 'aerialview.settings_flight' },
];

/* ─── Font options ─── */
const FONT_FAMILIES = [
  { label: 'Calibri', value: 'Calibri' },
  { label: 'Segoe UI', value: 'Segoe UI' },
  { label: 'Tahoma', value: 'Tahoma' },
  { label: 'Verdana', value: 'Verdana' },
  { label: 'Arial', value: 'Arial' },
  { label: 'Noto Sans SC', value: 'Noto Sans SC' },
  { label: 'Microsoft YaHei', value: 'Microsoft YaHei' },
  { label: 'SimHei', value: 'SimHei' },
  { label: 'PingFang SC', value: 'PingFang SC' },
];

const FONT_SIZES = [
  { label: '12px', value: '12px' },
  { label: '14px', value: '14px' },
  { label: '16px', value: '16px' },
  { label: '18px', value: '18px' },
  { label: '20px', value: '20px' },
  { label: '24px', value: '24px' },
];

/* ─── Locale persistence (same logic as LanguageSelector.vue) ─── */
watch(locale, (newLocale) => {
  localStorage.setItem('user-lang', newLocale);
});

/* ─── Page + dock registration ─── */
onMounted(() => {
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  // Invisible flex spacers: the top/bottom pair keeps the 5 navigation
  // buttons vertically centered while the Save button (registered last)
  // is pinned to the very bottom — identical to the My Space dock.
  registerLeft({ id: 'dock_spacer_top', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerLeft({
    id: 'router',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'aerialview.pages',
      pages,
    }),
  });

  // Same My Space dock group as MySpaceView (Pages -> Account -> Wallet ->
  // Content -> Settings) so the sidebar stays consistent; Account/Wallet/
  // Content deep-link into the matching My Space subpage, Settings is the
  // current page (highlighted, no action).
  const MYSPACE_SUBPAGES = [
    { id: 'account', icon: 'MENU_ACCOUNT', labelKey: 'aerialview.subpage_account' },
    { id: 'wallet', icon: 'MENU_WALLET', labelKey: 'aerialview.subpage_wallet' },
    { id: 'content', icon: 'MENU_CONTENT', labelKey: 'aerialview.subpage_content' },
  ];
  for (const sub of MYSPACE_SUBPAGES) {
    registerLeft({
      id: `subpage_${sub.id}`,
      icon: sub.icon,
      titleKey: sub.labelKey,
      onClick: () => { router.push(`/myspace?sub=${sub.id}`); },
    });
  }
  registerLeft({
    id: 'subpage_settings',
    icon: 'MENU_TOOL',
    titleKey: 'aerialview.subpage_settings',
    active: true,
  });

  // Save button pinned to the VERY BOTTOM of the left dock (stub action
  // for now — will persist settings via the FastAPI backend).
  registerLeft({ id: 'dock_spacer_bottom', render: () => h('div', { style: 'flex: 1 1 auto' }) });
  registerLeft({
    id: 'save',
    icon: 'MENU_SAVE',
    titleKey: 'aerialview.save',
    onClick: () => { saveSettings(); },
  });
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
      <div class="settings-page">
        <!-- Left sidebar -->
        <nav
          class="settings-sidebar"
          :style="{ width: leftWidth + 'px' }"
        >
          <div
            v-for="item in SETTINGS_LIST"
            :key="item.id"
            class="settings-sidebar__item"
            :class="{ 'settings-sidebar__item--active': selectedId === item.id }"
            @click="selectedId = item.id"
          >
            {{ t(item.labelKey) }}
          </div>
        </nav>

        <!-- Divider (draggable) -->
        <div
          class="settings-divider"
          @pointerdown="onDividerPointerDown"
        />

        <!-- Right content area -->
        <div class="settings-content">
          <!-- Save-flow notice (useSettingsSave): saved / login reminder -->
          <div
            v-if="saveNotice"
            class="save-notice"
            :class="`save-notice--${saveNotice}`"
          >
            {{ t(`aerialview.save_notice_${saveNotice}`) }}
          </div>
          <!-- Breadcrumb (this page lives under My Space now) -->
          <div class="settings-breadcrumb">{{ t('aerialview.page_myspace') }} &gt; {{ t('aerialview.subpage_settings') }}</div>

          <!-- Language -->
          <div v-if="selectedId === 'language'" class="settings-section">
            <h2 class="settings-section__title">{{ t('aerialview.settings_language') }}</h2>
            <div class="settings-row">
              <select v-model="locale" class="settings-select">
                <option value="en">English</option>
                <option value="zh">中文</option>
              </select>
            </div>
          </div>

          <!-- Font -->
          <div v-if="selectedId === 'font'" class="settings-section">
            <h2 class="settings-section__title">{{ t('aerialview.settings_font') }}</h2>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_font_style') }}</label>
              <select
                :value="settings.fontFamily"
                class="settings-select settings-select--wide"
                @change="setFontFamily($event.target.value)"
              >
                <option
                  v-for="ff in FONT_FAMILIES"
                  :key="ff.value"
                  :value="ff.value"
                  :style="{ fontFamily: ff.value }"
                >
                  {{ ff.label }}
                </option>
              </select>
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_font_size') }}</label>
              <select
                :value="settings.fontSize"
                class="settings-select settings-select--wide"
                @change="setFontSize($event.target.value)"
              >
                <option
                  v-for="fs in FONT_SIZES"
                  :key="fs.value"
                  :value="fs.value"
                >
                  {{ fs.label }}
                </option>
              </select>
            </div>

            <div class="settings-row settings-row--actions">
              <button class="settings-button settings-button--secondary" @click="resetFontDefaults">
                {{ t('aerialview.settings_reset_defaults') }}
              </button>
            </div>
          </div>

          <!-- Media -->
          <div v-if="selectedId === 'media'" class="settings-section">
            <h2 class="settings-section__title">{{ t('aerialview.settings_media') }}</h2>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_audio_volume') }}</label>
              <input
                v-model.number="settings.audioVolume"
                type="range"
                class="settings-slider"
                min="0"
                max="1"
                step="0.01"
              />
              <span class="settings-value">{{ Math.round(settings.audioVolume * 100) }}%</span>
            </div>

            <div class="settings-row settings-row--actions">
              <button class="settings-button settings-button--secondary" @click="resetMediaDefaults">
                {{ t('aerialview.settings_reset_defaults') }}
              </button>
            </div>
          </div>

          <!-- Network -->
          <div v-if="selectedId === 'network'" class="settings-section">
            <h2 class="settings-section__title">{{ t('aerialview.settings_network') }}</h2>

            <h3 class="settings-subsection__title">{{ t('aerialview.settings_enterprise_proxy') }}</h3>

            <p class="settings-reminder">
              {{ t('aerialview.settings_proxy_reminder_prefix') }}
              <router-link to="/extensions?cat=software&ext=simple-squid-proxy" class="settings-reminder__link">
                {{ t('aerialview.settings_proxy_reminder_link') }}
              </router-link>
              {{ t('aerialview.settings_proxy_reminder_suffix') }}
            </p>

            <div class="settings-row">
              <label class="settings-row__label">HTTP_PROXY</label>
              <span class="settings-value--readonly">{{ httpProxy }}</span>
            </div>

            <div class="settings-row">
              <label class="settings-row__label">HTTPS_PROXY</label>
              <span class="settings-value--readonly">{{ httpsProxy }}</span>
            </div>

            <div class="settings-row">
              <label class="settings-row__label">NO_PROXY</label>
              <span class="settings-value--readonly">{{ noProxy }}</span>
            </div>
          </div>

          <!-- Flight -->
          <div v-if="selectedId === 'flight'" class="settings-section">
            <h2 class="settings-section__title">{{ t('aerialview.settings_flight') }}</h2>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_takeoff_altitude') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.takeoffAltitude"
                min="20"
                max="10000"
                step="10"
                @change="setTakeoffAltitude($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_safety_buffer') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.safetyBuffer"
                min="2"
                max="100"
                step="1"
                @change="setSafetyBuffer($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_lat') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultLat"
                min="-90"
                max="90"
                step="0.0001"
                @change="setDefaultLat($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_lon') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultLon"
                min="-180"
                max="180"
                step="0.0001"
                @change="setDefaultLon($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_alt') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultAlt"
                min="0"
                max="10000"
                step="10"
                @change="setDefaultAlt($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_yaw') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultYaw"
                min="0"
                max="360"
                step="1"
                @change="setDefaultYaw($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_pitch') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultPitch"
                min="-90"
                max="90"
                step="1"
                @change="setDefaultPitch($event.target.value)"
              />
            </div>

            <div class="settings-row">
              <label class="settings-row__label">{{ t('aerialview.settings_default_roll') }}</label>
              <input
                type="number"
                class="settings-input settings-input--narrow"
                :value="settings.defaultRoll"
                min="-90"
                max="90"
                step="1"
                @change="setDefaultRoll($event.target.value)"
              />
            </div>

            <div class="settings-row settings-row--actions">
              <button class="settings-button settings-button--secondary" @click="resetFlightDefaults">
                {{ t('aerialview.settings_reset_defaults') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.settings-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
}

/* ─── Left sidebar ─── */
.settings-sidebar {
  flex-shrink: 0;
  padding: 20px 0;
  overflow-y: auto;
  background: #f5f5f7;
}

.settings-sidebar__item {
  padding: 9px 20px;
  font-size: 0.9rem;
  font-weight: 500;
  color: #1d1d1f;
  cursor: pointer;
  border-radius: 6px;
  margin: 2px 8px;
  transition: background 0.15s ease, color 0.15s ease;
}

.settings-sidebar__item:hover {
  background: rgba(0, 0, 0, 0.04);
}

.settings-sidebar__item--active {
  background: #007aff;
  color: #ffffff;
}

.settings-sidebar__item--active:hover {
  background: #0066d6;
}

/* ─── Divider ─── */
.settings-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.settings-divider:hover,
.settings-divider:active {
  background: #007aff;
}

/* ─── Right content ─── */
.settings-content {
  flex: 1;
  min-width: 0;
  padding: 24px 32px;
  overflow-y: auto;
  background: #ffffff;
}

.settings-breadcrumb {
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

.settings-section {
  display: flex;
  flex-direction: column;
  min-height: 100%;
}

.settings-section__title {
  margin: 0 0 20px 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #1d1d1f;
}

.settings-row {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}

.settings-row__label {
  flex: 0 0 calc(100% / 3);
  font-size: 0.875rem;
  font-weight: 500;
  color: #6e6e73;
}

.settings-select {
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #d2d2d7;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 0.875rem;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.settings-select--wide {
  flex: 1;
}

.settings-select:hover {
  border-color: #007aff;
}

.settings-input {
  flex: 1;
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #d2d2d7;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 0.875rem;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.settings-input--narrow {
  flex: 0 0 auto;
  width: 120px;
}

.settings-input:hover {
  border-color: #007aff;
}

.settings-input:focus {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

.settings-row--actions {
  margin-top: auto;
  margin-bottom: 24px;
}

.settings-button {
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #d2d2d7;
  background: #ffffff;
  color: #1d1d1f;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.settings-button:hover {
  background: #f5f5f7;
  border-color: #007aff;
}

.settings-button--secondary {
  border-color: rgba(0, 0, 0, 0.12);
  background: #e5e7eb;
  color: #374151;
}

.settings-button--secondary:hover {
  background: #d1d5db;
}

.settings-slider {
  flex: 1;
  min-width: 120px;
  cursor: pointer;
}

.settings-value {
  flex: 0 0 auto;
  min-width: 42px;
  text-align: right;
  font-size: 0.875rem;
  color: #6e6e73;
}

.settings-subsection__title {
  margin: 0 0 12px 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1d1d1f;
}

.settings-reminder {
  margin: 0 0 20px 0;
  font-size: 0.82rem;
  color: #6e6e73;
  line-height: 1.5;
}

.settings-reminder__link {
  color: #007aff;
  text-decoration: none;
  font-weight: 500;
}

.settings-reminder__link:hover {
  text-decoration: underline;
}

.settings-value--readonly {
  flex: 1;
  padding: 7px 12px;
  border-radius: 6px;
  background: #f5f5f7;
  border: 1px solid #e5e5ea;
  font-size: 0.82rem;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
  color: #374151;
  word-break: break-all;
}
</style>

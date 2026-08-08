<script setup>
import { ref, computed, onMounted, onUnmounted, h, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';
import ViewComposer from '@shared/_ViewComposer.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useProxyConfig } from '@shared-composables/useProxyConfig.js';
import DockMenuButton from '@shared/DockMenuButton.vue';

const { t } = useI18n();
const { leftItems, registerLeft, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { proxyConfig, OS_OPTIONS } = useProxyConfig();
const route = useRoute();

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
  const panel = document.querySelector('.extensions-page');
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

/* ─── Selected category ─── */
const selectedId = ref('scenic');
const searchQuery = ref('');

/* ─── Extension registry ─── */
const manifestModules = import.meta.glob('/extensions/**/manifest.md', { eager: true, query: '?raw', import: 'default' });

const EXTENSIONS_DATA = {
  software: {
    subcategories: [
      {
        id: 'network',
        labelKey: 'aerialview.extensions_sub_network',
        items: [
          {
            id: 'simple-squid-proxy',
            labelKey: 'aerialview.extensions_simple_squid_proxy',
            manifestPath: '/extensions/software/network/simple-squid-proxy/manifest.md',
          },
        ],
      },
    ],
  },
};

/* ─── Parse manifest markdown ─── */
function parseManifest(ext) {
  const raw = manifestModules[ext.manifestPath] || '';
  const lines = raw.split('\n');
  let title = '';
  let content = '';
  if (lines.length > 0 && lines[0].startsWith('# ')) {
    title = lines[0].replace(/^#\s+/, '').trim();
    content = lines.slice(1).join('\n').trim();
  } else {
    content = raw.trim();
  }
  return { title, content };
}

/* ─── Render full manifest as HTML ─── */
function renderManifestHtml(ext) {
  const raw = manifestModules[ext.manifestPath] || '';
  // Skip the first H1 title line
  const lines = raw.split('\n');
  const body = lines[0]?.startsWith('# ') ? lines.slice(1).join('\n') : raw;

  let html = '';
  let inCode = false;
  let codeLang = '';
  let codeLines = [];

  const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  body.split('\n').forEach((line) => {
    if (line.startsWith('```')) {
      if (inCode) {
        html += `<pre class="md-code"><code>${esc(codeLines.join('\n'))}</code></pre>`;
        codeLines = [];
        inCode = false;
      } else {
        inCode = true;
        codeLang = line.slice(3).trim();
      }
      return;
    }
    if (inCode) {
      codeLines.push(line);
      return;
    }

    // Headings
    if (line.startsWith('#### ')) { html += `<h4 class="md-h4">${esc(line.slice(5))}</h4>`; return; }
    if (line.startsWith('### ')) { html += `<h3 class="md-h3">${esc(line.slice(4))}</h3>`; return; }
    if (line.startsWith('## ')) { html += `<h2 class="md-h2">${esc(line.slice(3))}</h2>`; return; }

    // Horizontal rule
    if (/^---+$/.test(line.trim())) { html += '<hr class="md-hr" />'; return; }

    // Table rows
    if (line.startsWith('|')) {
      const cells = line.split('|').filter(c => c.trim());
      if (cells.every(c => /^[-\s]+$/.test(c))) return; // skip separator row
      const tag = line.includes('----') ? 'td' : 'td';
      html += `<div class="md-table-row">${cells.map(c => `<span class="md-table-cell">${c.trim().replace(/`([^`]+)`/g, '<code>$1</code>')}</span>`).join('')}</div>`;
      return;
    }

    // List items
    if (/^\d+\.\s/.test(line)) {
      const text = line.replace(/^\d+\.\s/, '').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
      html += `<div class="md-li">${text}</div>`;
      return;
    }
    if (line.startsWith('- ')) {
      const text = line.slice(2).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
      html += `<div class="md-li">• ${text}</div>`;
      return;
    }
    if (line.startsWith('  - ')) {
      const text = line.slice(4).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
      html += `<div class="md-li md-li--sub">• ${text}</div>`;
      return;
    }

    // Empty line
    if (!line.trim()) { html += '<div class="md-spacer"></div>'; return; }

    // Regular paragraph
    const text = line.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    html += `<p class="md-p">${text}</p>`;
  });

  return html;
}

/* ─── Detail view state ─── */
const activeExtension = ref(null);

/* ─── Deep-link support: /extensions?cat=software&ext=simple-squid-proxy ─── */
function applyQueryParams() {
  const cat = route.query.cat;
  const ext = route.query.ext;
  if (cat && EXTENSIONS_LIST.some((c) => c.id === cat)) {
    selectedId.value = cat;
  }
  if (ext) {
    const subs = EXTENSIONS_DATA[cat]?.subcategories || [];
    for (const sub of subs) {
      const item = sub.items.find((i) => i.id === ext);
      if (item) {
        activeExtension.value = { ...item, subcategoryLabel: t(sub.labelKey) };
        return;
      }
    }
  }
}

watch(() => route.query, applyQueryParams);

function openExtension(ext) {
  activeExtension.value = ext;
}

function closeExtension() {
  activeExtension.value = null;
}

function selectCategory(id) {
  selectedId.value = id;
  activeExtension.value = null;
}

/* ─── Breadcrumb ─── */
const EXTENSIONS_LIST = [
  { id: 'scenic', labelKey: 'aerialview.extensions_scenic' },
  { id: 'swarm', labelKey: 'aerialview.extensions_swarm' },
  { id: 'real_drone', labelKey: 'aerialview.extensions_real_drone' },
  { id: 'hardware', labelKey: 'aerialview.extensions_hardware' },
  { id: 'software', labelKey: 'aerialview.extensions_software' },
];

const breadcrumb = computed(() => {
  const selected = EXTENSIONS_LIST.find((c) => c.id === selectedId.value);
  const catLabel = selected ? t(selected.labelKey) : '';
  if (activeExtension.value) {
    const ext = activeExtension.value;
    const subLabel = ext.subcategoryLabel || '';
    const extLabel = t(ext.labelKey);
    return `Extensions > ${catLabel} > ${subLabel} > ${extLabel}`;
  }
  return `Extensions > ${catLabel}`;
});

/* ─── Current category data ─── */
const currentSubcategories = computed(() => {
  const data = EXTENSIONS_DATA[selectedId.value];
  return data?.subcategories || [];
});

/* ─── Page + dock registration ─── */
onMounted(() => {
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  registerLeft({
    id: 'router',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'aerialview.pages',
      pages,
    }),
  });

  // Handle deep-link query params (e.g. /extensions?cat=software&ext=simple-squid-proxy)
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
      <div class="extensions-page">
        <!-- Left sidebar -->
        <nav
          class="extensions-sidebar"
          :style="{ width: leftWidth + 'px' }"
        >
          <div
            v-for="item in EXTENSIONS_LIST"
            :key="item.id"
            class="extensions-sidebar__item"
            :class="{ 'extensions-sidebar__item--active': selectedId === item.id }"
            @click="selectCategory(item.id)"
          >
            {{ t(item.labelKey) }}
          </div>
        </nav>

        <!-- Divider (draggable) -->
        <div
          class="extensions-divider"
          @pointerdown="onDividerPointerDown"
        />

        <!-- Right content area -->
        <div class="extensions-content">
          <!-- Breadcrumb -->
          <div class="extensions-breadcrumb">
            <span
              v-if="activeExtension"
              class="extensions-breadcrumb__back"
              @click="closeExtension"
            >&larr;</span>
            {{ breadcrumb }}
          </div>

          <!-- Search bar (visible in list view only, above separator) -->
          <div v-if="!activeExtension" class="extensions-search-bar">
            <svg class="extensions-search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              v-model="searchQuery"
              type="text"
              class="extensions-search-input"
              :placeholder="t('aerialview.extensions_search_placeholder')"
            />
          </div>

          <!-- Separator -->
          <div class="extensions-separator" />

          <!-- Detail view (manifest) -->
          <div v-if="activeExtension" class="extensions-manifest">

            <!-- Proxy config widgets (for simple-squid-proxy) -->
            <div v-if="activeExtension.id === 'simple-squid-proxy'" class="proxy-config">

              <!-- OS -->
              <div class="proxy-row">
                <label class="proxy-row__label">OS</label>
                <select v-model="proxyConfig.os" class="proxy-select">
                  <option v-for="opt in OS_OPTIONS" :key="opt" :value="opt">{{ opt }}</option>
                </select>
              </div>

              <!-- Login -->
              <div class="proxy-row">
                <label class="proxy-row__label">Login</label>
                <input v-model="proxyConfig.login" type="text" class="proxy-input proxy-input--wide" />
              </div>

              <!-- Password -->
              <div class="proxy-row">
                <label class="proxy-row__label">Password</label>
                <input v-model="proxyConfig.password" type="text" class="proxy-input proxy-input--wide" />
              </div>

              <!-- HTTP Proxy -->
              <div class="proxy-row">
                <label class="proxy-row__label">HTTP Proxy</label>
                <input v-model="proxyConfig.httpHost" type="text" class="proxy-input proxy-input--port-width" />
                <input :value="proxyConfig.httpPort" type="number" class="proxy-input proxy-input--host-width" @input="proxyConfig.httpPort = Number($event.target.value)" />
              </div>

              <!-- HTTPS Proxy -->
              <div class="proxy-row">
                <label class="proxy-row__label">HTTPS Proxy</label>
                <input v-model="proxyConfig.httpsHost" type="text" class="proxy-input proxy-input--port-width" />
                <input :value="proxyConfig.httpsPort" type="number" class="proxy-input proxy-input--host-width" @input="proxyConfig.httpsPort = Number($event.target.value)" />
              </div>

              <!-- Socks Host -->
              <div class="proxy-row">
                <label class="proxy-row__label">Socks Host</label>
                <input v-model="proxyConfig.socksHost" type="text" class="proxy-input proxy-input--port-width" />
                <input :value="proxyConfig.socksPort" type="number" class="proxy-input proxy-input--host-width" @input="proxyConfig.socksPort = Number($event.target.value)" />
              </div>

              <!-- Ignore Hosts -->
              <div class="proxy-row">
                <label class="proxy-row__label">Ignore Hosts</label>
                <input v-model="proxyConfig.ignoreHosts" type="text" class="proxy-input proxy-input--wide" />
              </div>

              <div class="extensions-separator" />
            </div>

            <!-- Manifest title and content below second separator -->
            <h2 class="extensions-manifest__title">{{ parseManifest(activeExtension).title }}</h2>
            <div class="manifest-body" v-html="renderManifestHtml(activeExtension)"></div>
          </div>

          <!-- List view -->
          <div v-else class="extensions-results">
            <!-- Subcategories -->
            <div
              v-for="sub in currentSubcategories"
              :key="sub.id"
              class="extensions-subcategory"
            >
              <h3 class="extensions-subcategory__title">{{ t(sub.labelKey) }}</h3>
              <div
                v-for="ext in sub.items"
                :key="ext.id"
                class="extensions-item"
                @click="openExtension({ ...ext, subcategoryLabel: t(sub.labelKey) })"
              >
                {{ t(ext.labelKey) }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.extensions-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
}

/* ─── Left sidebar ─── */
.extensions-sidebar {
  flex-shrink: 0;
  padding: 20px 0;
  overflow-y: auto;
  background: #f5f5f7;
}

.extensions-sidebar__item {
  padding: 9px 20px;
  font-size: 0.9rem;
  font-weight: 500;
  color: #1d1d1f;
  cursor: pointer;
  border-radius: 6px;
  margin: 2px 8px;
  transition: background 0.15s ease, color 0.15s ease;
}

.extensions-sidebar__item:hover {
  background: rgba(0, 0, 0, 0.04);
}

.extensions-sidebar__item--active {
  background: #007aff;
  color: #ffffff;
}

.extensions-sidebar__item--active:hover {
  background: #0066d6;
}

/* ─── Divider ─── */
.extensions-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.extensions-divider:hover,
.extensions-divider:active {
  background: #007aff;
}

/* ─── Right content ─── */
.extensions-content {
  flex: 1;
  min-width: 0;
  padding: 24px 32px;
  overflow-y: auto;
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.extensions-breadcrumb {
  font-size: 0.8rem;
  font-weight: 500;
  color: #6e6e73;
  margin-bottom: 16px;
}

.extensions-search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid #d2d2d7;
  background: #f5f5f7;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.extensions-search-bar:focus-within {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
  background: #ffffff;
}

.extensions-search-icon {
  flex-shrink: 0;
  color: #6e6e73;
}

.extensions-search-input {
  flex: 1;
  border: none;
  background: transparent;
  font-size: 0.875rem;
  color: #1d1d1f;
  outline: none;
}

.extensions-search-input::placeholder {
  color: #8e8e93;
}

.extensions-separator {
  height: 1px;
  background: #e5e5ea;
  margin-top: 16px;
  margin-bottom: 1.5em;
  flex-shrink: 0;
}

.extensions-results {
  flex: 1;
  min-height: 0;
}

.extensions-breadcrumb__back {
  cursor: pointer;
  margin-right: 8px;
  color: #007aff;
  font-weight: 600;
}

.extensions-breadcrumb__back:hover {
  text-decoration: underline;
}

.extensions-subcategory {
  margin-bottom: 24px;
}

.extensions-subcategory__title {
  margin: 0 0 12px 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1d1d1f;
}

.extensions-item {
  padding: 10px 16px;
  font-size: 0.875rem;
  font-weight: 500;
  color: #1d1d1f;
  cursor: pointer;
  border-radius: 6px;
  margin-bottom: 4px;
  transition: background 0.15s ease;
}

.extensions-item:hover {
  background: #f5f5f7;
  color: #007aff;
}

.extensions-manifest {
  flex: 1;
  min-height: 0;
}

.extensions-manifest__title {
  margin: 0 0 20px 0;
  font-size: 1.25rem;
  font-weight: 700;
  color: #1d1d1f;
  text-align: center;
}

/* ─── Proxy config widgets ─── */
.proxy-config {
  margin-top: 0;
}

.proxy-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.proxy-row__label {
  flex: 0 0 110px;
  font-size: 0.875rem;
  font-weight: 500;
  color: #1d1d1f;
}

.proxy-select {
  flex: 1;
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #d2d2d7;
  background: #f5f5f5;
  color: #1d1d1f;
  font-size: 0.875rem;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.proxy-select:focus {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

.proxy-input {
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #d2d2d7;
  background: #f5f5f5;
  color: #1d1d1f;
  font-size: 0.875rem;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.proxy-input:focus {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

.proxy-input--host-width {
  flex: 1;
  min-width: 0;
}

.proxy-input--port-width {
  flex: 0 0 80px;
  text-align: center;
}

.proxy-input--wide {
  flex: 1;
  min-width: 0;
}

/* ─── Manifest body (rendered markdown) ─── */
.manifest-body {
  margin-top: 16px;
  font-size: 0.875rem;
  color: #374151;
  line-height: 1.6;
  user-select: text;
}

.manifest-body :deep(.md-h2) {
  margin: 24px 0 8px 0;
  font-size: 1.1rem;
  font-weight: 700;
  color: #1d1d1f;
}

.manifest-body :deep(.md-h3) {
  margin: 18px 0 6px 0;
  font-size: 1rem;
  font-weight: 600;
  color: #1d1d1f;
}

.manifest-body :deep(.md-h4) {
  margin: 14px 0 4px 0;
  font-size: 0.9rem;
  font-weight: 600;
  color: #1d1d1f;
}

.manifest-body :deep(.md-p) {
  margin: 0 0 4px 0;
}

.manifest-body :deep(.md-li) {
  margin: 2px 0;
  padding-left: 16px;
}

.manifest-body :deep(.md-li--sub) {
  padding-left: 32px;
}

.manifest-body :deep(.md-code) {
  margin: 8px 0;
  padding: 12px 16px;
  background: #f5f5f7;
  border-radius: 6px;
  border: 1px solid #e5e5ea;
  overflow-x: auto;
  font-size: 0.8rem;
  line-height: 1.5;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
}

.manifest-body :deep(.md-code code) {
  background: none;
  padding: 0;
  font-size: inherit;
}

.manifest-body :deep(.md-hr) {
  border: none;
  height: 1px;
  background: #e5e5ea;
  margin: 20px 0;
}

.manifest-body :deep(.md-table-row) {
  display: flex;
  gap: 16px;
  margin: 2px 0;
}

.manifest-body :deep(.md-table-cell) {
  flex: 1;
}

.manifest-body :deep(code) {
  background: #f0f0f3;
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 0.82rem;
  font-family: 'SF Mono', 'Menlo', 'Consolas', monospace;
}

.manifest-body :deep(.md-spacer) {
  height: 8px;
}

.manifest-body :deep(strong) {
  color: #1d1d1f;
  font-weight: 600;
}
</style>

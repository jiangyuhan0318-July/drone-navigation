<script setup>
import { ref, computed, h, nextTick, watch, onMounted, onBeforeUnmount } from 'vue';
import { useI18n } from 'vue-i18n';
import ViewComposer from '@shared/_ViewComposer.vue';
import ConfigurableIcon from '@shared/ConfigurableIcon.vue';
import DockMenuButton from '@shared/DockMenuButton.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useOpenClaw } from '@shared-composables/useOpenClaw.js';
import { useDroneTelemetry } from '@shared-composables/useDroneTelemetry.js';
import { useStreamConfig } from '@shared-composables/useStreamConfig.js';
import { createWhepPlayer } from '@shared-composables/useWhepPlayer.js';

const { t } = useI18n();
const { leftItems, registerLeft, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { status, error, messages, isConnected, sendMessage } = useOpenClaw();
const { telemetry } = useDroneTelemetry();
const { streams } = useStreamConfig();

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

/* ─── Chat ─── */
const input = ref('');
const messagesRef = ref(null);

function handleSend() {
  const text = input.value.trim();
  if (!text) return;
  sendMessage(text);
  input.value = '';
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSend();
  }
}

watch(messages, () => {
  nextTick().then(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight;
    }
  });
}, { deep: true });

/* ─── Flight gate (human-only switch, server-enforced) ─── */
const gateEnabled = ref(false);
const gateBusy = ref(false);

async function loadGate() {
  try {
    const res = await fetch(`${API_BASE}/api/copilot/gate`);
    if (res.ok) gateEnabled.value = (await res.json()).enabled;
  } catch { /* backend down — keep last state */ }
}

async function toggleGate() {
  gateBusy.value = true;
  try {
    const res = await fetch(`${API_BASE}/api/copilot/gate`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !gateEnabled.value }),
    });
    if (res.ok) gateEnabled.value = (await res.json()).enabled;
  } finally {
    gateBusy.value = false;
  }
}

/* ─── Livestream (primary stream, e.g. the webcam/drone camera) ─── */
const videoRef = ref(null);
const primaryWhepUrl = computed(() => streams.value[0]?.whep_url || '');
const player = createWhepPlayer({
  url: () => primaryWhepUrl.value,
  logTag: 'copilot-live',
});

onMounted(() => {
  registerPage({ id: 'copilot', nameKey: 'copilotview.page_copilot', route: '/copilot' });
  registerLeft({
    id: 'pages',
    render: () => h(DockMenuButton, { icon: 'MENU_ROUTER', titleKey: 'copilotview.nav_pages', pages }),
  });
  loadGate();
  nextTick(() => {
    if (videoRef.value) player.attach(videoRef.value);
    if (primaryWhepUrl.value) player.start();
  });
});

watch(primaryWhepUrl, (url) => {
  if (url && videoRef.value) player.start();
});

onBeforeUnmount(() => {
  player.stop();
  clear();
  unregisterPage('copilot');
});

/* ─── Formatting helpers ─── */
const fmt = (v, digits = 2) => (v == null ? '--' : Number(v).toFixed(digits));
</script>

<template>
  <ViewComposer
    :left-items="leftItems"
    :right-items="rightItems"
    :show-flight="false"
    :show-camera="false"
    :show-hud="false"
    :flight="{ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }"
    :camera="{ mode: '-', yaw: 0, pitch: 0, roll: 0 }"
  >
    <template #background>
      <div class="copilot-page">
        <!-- ─── Left: chat ─── -->
        <section class="copilot-chat">
          <header class="chat-header">
            <h1 class="chat-header-title">{{ t('copilotview.page_title') }}</h1>
            <span class="chat-status" :class="`chat-status--${status}`">
              {{ isConnected ? t('copilotview.online') : t(`copilotview.status_${status}`) }}
            </span>
          </header>

          <div ref="messagesRef" class="messages">
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="message-wrapper"
              :class="`message-wrapper--${msg.sender}`"
            >
              <span v-if="msg.sender === 'bot'" class="chat-avatar chat-avatar--agent">
                <ConfigurableIcon name="AGENT_OPENCLAW" :size="32" />
              </span>
              <div class="message-bubble" :class="`message-bubble--${msg.sender}`">
                <p v-if="msg.text" class="message-text">{{ msg.text }}</p>
                <span class="message-time">{{ msg.time }}</span>
              </div>
              <span v-if="msg.sender === 'user'" class="chat-avatar chat-avatar--user">
                <ConfigurableIcon name="USER_PORTRAIT" :size="40" />
              </span>
            </div>
            <div v-if="error" class="message-wrapper message-wrapper--system">
              <div class="message-bubble message-bubble--system">
                <p class="message-text">{{ error }}</p>
              </div>
            </div>
          </div>

          <footer class="chat-inputbar">
            <textarea
              v-model="input"
              class="chat-input"
              :placeholder="t('copilotview.type_a_message')"
              rows="1"
              :disabled="!isConnected"
              @keydown="handleKeydown"
            />
            <button
              class="send-btn"
              :title="t('copilotview.send')"
              :disabled="!isConnected || !input.trim()"
              @click="handleSend"
            >
              <ConfigurableIcon name="CHAT_SEND" :size="18" />
            </button>
          </footer>
        </section>

        <!-- ─── Divider ─── -->
        <div class="copilot-divider" />

        <!-- ─── Right: gate + telemetry + livestream ─── -->
        <aside class="copilot-side">
          <div class="panel">
            <div class="panel-row">
              <span class="panel-label">{{ t('copilotview.flight_gate') }}</span>
              <button
                class="gate-btn"
                :class="gateEnabled ? 'gate-btn--on' : 'gate-btn--off'"
                :disabled="gateBusy"
                @click="toggleGate"
              >
                {{ gateEnabled ? t('copilotview.gate_on') : t('copilotview.gate_off') }}
              </button>
            </div>
            <p class="gate-hint">{{ t('copilotview.gate_hint') }}</p>
          </div>

          <div class="panel">
            <span class="panel-label">{{ t('copilotview.telemetry') }}</span>
            <div class="telemetry-grid">
              <div class="telemetry-item">
                <span class="telemetry-key">Link</span>
                <span class="telemetry-val" :class="{ 'is-stale': !telemetry.linked }">
                  {{ telemetry.linked ? `${fmt(telemetry.hz, 0)} Hz` : '--' }}
                </span>
              </div>
              <div class="telemetry-item">
                <span class="telemetry-key">X / Y / Z</span>
                <span class="telemetry-val" :class="{ 'is-stale': !telemetry.linked }">
                  {{ telemetry.linked
                    ? `${fmt(telemetry.position.x)} / ${fmt(telemetry.position.y)} / ${fmt(telemetry.position.z)}`
                    : '--' }}
                </span>
              </div>
              <div class="telemetry-item">
                <span class="telemetry-key">Roll / Pitch / Yaw</span>
                <span class="telemetry-val" :class="{ 'is-stale': !telemetry.linked }">
                  {{ telemetry.linked
                    ? `${fmt(telemetry.attitude.roll)}° / ${fmt(telemetry.attitude.pitch)}° / ${fmt(telemetry.attitude.yaw)}°`
                    : '--' }}
                </span>
              </div>
              <div class="telemetry-item">
                <span class="telemetry-key">Battery</span>
                <span class="telemetry-val" :class="{
                  'is-stale': !telemetry.linked,
                  'is-low': telemetry.linked && telemetry.battery.voltage != null && telemetry.battery.voltage < 3.5,
                }">
                  {{ !telemetry.linked || telemetry.battery.voltage == null
                    ? '--'
                    : `${fmt(telemetry.battery.voltage)} V${telemetry.battery.voltage < 3.5 ? ' (低)' : ''}` }}
                </span>
              </div>
            </div>
          </div>

          <div class="panel panel--video">
            <span class="panel-label">{{ t('copilotview.livestream') }}</span>
            <video
              ref="videoRef"
              class="copilot-video"
              autoplay
              playsinline
              muted
            />
            <p v-if="!primaryWhepUrl" class="gate-hint">{{ t('copilotview.no_stream') }}</p>
          </div>
        </aside>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.copilot-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
}

/* ─── Chat (left) ─── */
.copilot-chat {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  overflow: hidden;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  border-bottom: 1px solid rgba(229, 231, 235, 0.8);
  background: rgba(255, 255, 255, 0.7);
}

.chat-header-title {
  font-size: 1.125rem;
  font-weight: 700;
  margin: 0;
  color: #1d1d1f;
}

.chat-status {
  font-size: 0.75rem;
  font-weight: 600;
  color: #16a34a;
  display: flex;
  align-items: center;
  gap: 6px;
}

.chat-status::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}

.chat-status--connecting {
  color: #d97706;
}

.chat-status--connecting::before {
  background: #f59e0b;
}

.chat-status--error,
.chat-status--closed,
.chat-status--idle {
  color: #dc2626;
}

.chat-status--error::before,
.chat-status--closed::before,
.chat-status--idle::before {
  background: #ef4444;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-wrapper {
  display: flex;
  width: 100%;
  align-items: flex-end;
  gap: 10px;
}

.message-wrapper--user {
  justify-content: flex-end;
}

.message-wrapper--bot,
.message-wrapper--system {
  justify-content: flex-start;
}

.chat-avatar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chat-avatar--agent {
  width: 36px;
  height: 36px;
}

.chat-avatar--user {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: 1px solid rgba(156, 163, 175, 0.4);
  background: #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.message-bubble {
  max-width: 60%;
  padding: 12px 16px;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.message-bubble--user {
  background: #3b82f6;
  color: white;
  border-bottom-right-radius: 4px;
}

.message-bubble--bot {
  background: #f3f4f6;
  color: #1f2937;
  border-bottom-left-radius: 4px;
}

.message-bubble--system {
  background: #dbeafe;
  color: #1e40af;
  border-radius: 999px;
  padding: 8px 16px;
  max-width: max-content;
  margin: 0 auto;
}

.message-text {
  margin: 0;
  line-height: 1.5;
  font-size: 0.95rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-time {
  font-size: 0.7rem;
  opacity: 0.7;
  align-self: flex-end;
}

.chat-inputbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 24px;
  border-top: 1px solid rgba(229, 231, 235, 0.8);
  background: rgba(255, 255, 255, 0.7);
}

.chat-input {
  flex: 1;
  resize: none;
  padding: 12px 18px;
  border-radius: 24px;
  border: 1px solid rgba(209, 213, 219, 0.8);
  background: #f9fafb;
  font-size: 0.95rem;
  line-height: 1.4;
  outline: none;
  min-height: 24px;
  max-height: 120px;
}

.chat-input:focus {
  border-color: #3b82f6;
  background: white;
}

.chat-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: #3b82f6;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease;
  flex-shrink: 0;
}

.send-btn:hover:not(:disabled) {
  background: #2563eb;
}

.send-btn:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}

/* ─── Divider ─── */
.copilot-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
}

/* ─── Right side ─── */
.copilot-side {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: #f5f5f7;
  overflow-y: auto;
}

.panel {
  background: #ffffff;
  border-radius: 12px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.panel-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.panel-label {
  font-size: 0.8rem;
  font-weight: 700;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.gate-btn {
  border: none;
  border-radius: 999px;
  padding: 8px 18px;
  font-size: 0.85rem;
  font-weight: 700;
  cursor: pointer;
  transition: background 0.15s ease;
}

.gate-btn--off {
  background: #fee2e2;
  color: #b91c1c;
}

.gate-btn--on {
  background: #dcfce7;
  color: #15803d;
}

.gate-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.gate-hint {
  margin: 0;
  font-size: 0.75rem;
  color: #9ca3af;
  line-height: 1.5;
}

.telemetry-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.telemetry-item {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
}

.telemetry-key {
  color: #6b7280;
}

.telemetry-val {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #1f2937;
}

.telemetry-val.is-stale {
  color: #dc2626;
}

.telemetry-val.is-low {
  color: #dc2626;
  font-weight: 700;
}

.panel--video {
  flex: 1;
  min-height: 200px;
}

.copilot-video {
  width: 100%;
  flex: 1;
  border-radius: 8px;
  background: #111827;
  object-fit: contain;
}
</style>

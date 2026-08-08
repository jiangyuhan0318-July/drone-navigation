<script setup>
import { ref, computed, h, nextTick, onMounted, onUnmounted } from 'vue';
import { useI18n } from 'vue-i18n';
import ViewComposer from '@shared/_ViewComposer.vue';
import ConfigurableIcon from '@shared/ConfigurableIcon.vue';
import DockMenuButton from '@shared/DockMenuButton.vue';
import { useDockRegistry } from '@shared-composables/useDockRegistry.js';
import { usePageRegistry } from '@shared-composables/usePageRegistry.js';
import { useAuth } from '@shared-composables/useAuth.js';
import { useMatrixClient } from '@shared-composables/useMatrixClient.js';
import { useRouter } from 'vue-router';

const { t } = useI18n();
const router = useRouter();
const { leftItems, rightItems, registerLeft, registerRight, clear } = useDockRegistry();
const { pages, registerPage, unregisterPage } = usePageRegistry();
const { isAuthenticated } = useAuth();
const {
  ready: chatReady, error: chatError,
  dms, teamRooms, activeRoom, activeRoomId, timeline, typingNames, directory,
  bootstrap, setActiveRoom, sendText, noteTyping,
  createDm, createTeamRoom, fetchDirectory,
} = useMatrixClient();

/* ─── Left-column width drag ─── */
const LEFT_MIN = 280;
const LEFT_MAX = 600;
const LEFT_DEFAULT = 40; // percentage
// The 72px AppDock strips overlay the page on both sides (see .community-page
// padding) — the draggable area is the content box between them.
const DOCK_W = 72;
const leftWidthPct = ref(LEFT_DEFAULT);
const isDragging = ref(false);

function onDividerPointerDown(e) {
  e.preventDefault();
  isDragging.value = true;
  document.addEventListener('pointermove', onDividerPointerMove);
  document.addEventListener('pointerup', onDividerPointerUp);
}

function onDividerPointerMove(e) {
  if (!isDragging.value) return;
  const panel = document.querySelector('.community-page');
  if (!panel) return;
  const rect = panel.getBoundingClientRect();
  const usable = rect.width - DOCK_W * 2;
  const x = e.clientX - rect.left - DOCK_W;
  const pct = (x / usable) * 100;
  const minPct = (LEFT_MIN / usable) * 100;
  const maxPct = (LEFT_MAX / usable) * 100;
  leftWidthPct.value = Math.min(maxPct, Math.max(minPct, pct));
}

function onDividerPointerUp() {
  isDragging.value = false;
  document.removeEventListener('pointermove', onDividerPointerMove);
  document.removeEventListener('pointerup', onDividerPointerUp);
}

/* ─── Sidebar navigation ─── */
const selectedNav = ref('chat');

/* ─── Composer ─── */
const input = ref('');
const sending = ref(false);
const messagesRef = ref(null);

async function sendMessage() {
  const text = input.value.trim();
  if (!text || sending.value || !activeRoomId.value) return;
  sending.value = true;
  try {
    await sendText(text);
    input.value = '';
    await nextTick();
    scrollToBottom();
  } finally {
    sending.value = false;
  }
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function onComposerInput() {
  noteTyping();
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight;
  }
}

async function selectRoom(roomId) {
  setActiveRoom(roomId);
  await nextTick();
  scrollToBottom();
}

/* ─── New chat / team room dialog ─── */
const dialogMode = ref(''); // '' | 'dm' | 'team'
const teamName = ref('');
const teamSelection = ref([]);

function openDialog(mode) {
  dialogMode.value = mode;
  teamName.value = '';
  teamSelection.value = [];
  fetchDirectory();
}

function isTeamSelected(entry) {
  return teamSelection.value.some((e) => e.mxid === entry.mxid);
}

function toggleTeamMember(entry) {
  if (isTeamSelected(entry)) {
    teamSelection.value = teamSelection.value.filter((e) => e.mxid !== entry.mxid);
  } else {
    teamSelection.value = [...teamSelection.value, entry];
  }
}

async function startDm(entry) {
  dialogMode.value = '';
  await createDm(entry);
  await nextTick();
  scrollToBottom();
}

async function createTeam() {
  if (!teamName.value.trim() || !teamSelection.value.length) return;
  const entries = [...teamSelection.value];
  dialogMode.value = '';
  await createTeamRoom(teamName.value, entries);
  await nextTick();
  scrollToBottom();
}

function initials(name) {
  return (name || '?').trim().charAt(0).toUpperCase() || '?';
}

/* ─── Formatting ─── */
function timeFmt(ts) {
  if (!ts) return '';
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function dayFmt(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? timeFmt(ts)
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

const typingText = computed(() => {
  const names = typingNames.value;
  if (!names.length) return '';
  if (names.length === 1) return t('chatview.typing_one', { name: names[0] });
  return t('chatview.typing_many', { names: names.join(', ') });
});

onMounted(() => {
  registerPage({ id: 'aerial', nameKey: 'aerialview.page_aerial', route: '/' });
  registerPage({ id: 'map', nameKey: 'aerialview.page_map', route: '/map' });
  registerPage({ id: 'realdrone', nameKey: 'aerialview.page_realdrone', route: '/real-drone' });
  registerPage({ id: 'extensions', nameKey: 'aerialview.page_extensions', route: '/extensions' });
  registerPage({ id: 'chat', nameKey: 'aerialview.page_chat', route: '/chat' });
  registerPage({ id: 'myspace', nameKey: 'aerialview.page_myspace', route: '/myspace' });

  // Register dock sidebar buttons
  registerLeft({
    id: 'pages',
    render: () => h(DockMenuButton, {
      icon: 'MENU_ROUTER',
      titleKey: 'chatview.nav_pages',
      pages,
    }),
  });
  registerLeft({
    id: 'chat',
    icon: 'MENU_CHAT',
    titleKey: 'chatview.nav_chat',
    active: computed(() => selectedNav.value === 'chat'),
    onClick: () => { selectedNav.value = 'chat'; },
  });
  registerLeft({
    id: 'contacts',
    icon: 'MENU_CONTACTS',
    titleKey: 'chatview.nav_contacts',
    active: computed(() => selectedNav.value === 'contacts'),
    onClick: () => { selectedNav.value = 'contacts'; },
  });
  registerLeft({
    id: 'gallery',
    icon: 'MENU_GALLARY',
    titleKey: 'chatview.nav_gallery',
    active: computed(() => selectedNav.value === 'gallery'),
    onClick: () => { selectedNav.value = 'gallery'; },
  });
  registerLeft({
    id: 'customer_service',
    icon: 'MENU_CUSTOMER_SERVICE',
    titleKey: 'chatview.nav_customer_service',
    active: computed(() => selectedNav.value === 'customer_service'),
    onClick: () => { router.push('/customer-service'); },
  });

  // Register right dock buttons
  registerRight({
    id: 'photo',
    icon: 'MENU_PHOTO',
    titleKey: 'chatview.tool_photo',
    onClick: () => {},
  });
  registerRight({
    id: 'file',
    icon: 'MENU_ARCHIVE',
    titleKey: 'chatview.tool_file',
    onClick: () => {},
  });
  registerRight({
    id: 'note',
    icon: 'MENU_NOTE',
    titleKey: 'chatview.tool_note',
    onClick: () => {},
  });
  registerRight({
    id: 'tool',
    icon: 'MENU_TOOL',
    titleKey: 'chatview.tool_tool',
    onClick: () => {},
  });

  // Community is the only Matrix entrance. The login/logout lockstep watch
  // lives at module scope in useMatrixClient (never unmounts); here we just
  // kick off the initial bootstrap + directory when already logged in.
  if (isAuthenticated.value) {
    bootstrap();
    fetchDirectory();
  }
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
    :right-items="rightItems"
    :show-flight="false"
    :show-camera="false"
    :show-hud="false"
    :flight="{ mode: '-', vx: 0, vy: 0, yaw: 0, vz: 0 }"
    :camera="{ mode: '-', yaw: 0, pitch: 0, roll: 0 }"
  >
    <template #background>
      <div class="community-page">
        <!-- Left panel -->
        <aside
          class="community-sidebar"
          :style="{ flexBasis: leftWidthPct + '%' }"
        >
          <!-- Chat: room list -->
          <template v-if="selectedNav === 'chat'">
            <div class="sidebar-actions">
              <button class="sidebar-action" :disabled="!chatReady" @click="openDialog('dm')">
                + {{ t('chatview.new_chat') }}
              </button>
              <button class="sidebar-action" :disabled="!chatReady" @click="openDialog('team')">
                + {{ t('chatview.new_team_room') }}
              </button>
            </div>

            <div v-if="dms.length" class="room-section">
              <h3 class="room-section-title">{{ t('chatview.direct_messages') }}</h3>
              <button
                v-for="room in dms"
                :key="room.roomId"
                class="room-item"
                :class="{ 'room-item--active': room.roomId === activeRoomId }"
                @click="selectRoom(room.roomId)"
              >
                <span class="room-avatar">{{ initials(room.name) }}</span>
                <span class="room-meta">
                  <span class="room-name">{{ room.name }}</span>
                  <span class="room-preview">{{ room.preview }}</span>
                </span>
                <span class="room-time">{{ dayFmt(room.lastTs) }}</span>
              </button>
            </div>

            <div v-if="teamRooms.length" class="room-section">
              <h3 class="room-section-title">{{ t('chatview.team_rooms') }}</h3>
              <button
                v-for="room in teamRooms"
                :key="room.roomId"
                class="room-item"
                :class="{ 'room-item--active': room.roomId === activeRoomId }"
                @click="selectRoom(room.roomId)"
              >
                <span class="room-avatar room-avatar--team">{{ initials(room.name) }}</span>
                <span class="room-meta">
                  <span class="room-name">{{ room.name }}</span>
                  <span class="room-preview">{{ room.preview || t('chatview.members_count', { count: room.members }) }}</span>
                </span>
                <span class="room-time">{{ dayFmt(room.lastTs) }}</span>
              </button>
            </div>

            <p v-if="chatReady && !dms.length && !teamRooms.length" class="sidebar-empty">
              {{ t('chatview.no_conversations') }}
            </p>
          </template>

          <!-- Contacts stub (untouched for now) -->
          <p v-else-if="selectedNav === 'contacts'" class="sidebar-empty">
            {{ t('chatview.contacts_stub') }}
          </p>

          <!-- Gallery stub (untouched for now) -->
          <p v-else-if="selectedNav === 'gallery'" class="sidebar-empty">
            {{ t('chatview.gallery_stub') }}
          </p>
        </aside>

        <!-- Divider (draggable) -->
        <div
          class="community-divider"
          @pointerdown="onDividerPointerDown"
        />

        <!-- Right content area -->
        <main class="community-content">
          <!-- Login gate: same green-banner pattern as the Save/capture gates -->
          <template v-if="!isAuthenticated">
            <div class="chat-notice chat-notice--green">
              {{ t('chatview.login_required') }}
            </div>
            <div class="chat-empty">
              <p>{{ t('chatview.select_room') }}</p>
            </div>
          </template>

          <!-- Backend/Synapse unavailable -->
          <template v-else-if="chatError === 'unavailable'">
            <div class="chat-notice chat-notice--red">
              {{ t('chatview.unavailable') }}
            </div>
            <div class="chat-empty">
              <button class="sidebar-action" @click="bootstrap">{{ t('chatview.retry') }}</button>
            </div>
          </template>

          <!-- Connecting -->
          <template v-else-if="!chatReady">
            <div class="chat-empty">
              <p>{{ t('chatview.connecting') }}</p>
            </div>
          </template>

          <!-- Ready -->
          <template v-else>
            <!-- Chat header -->
            <header class="chat-header">
              <h1 class="chat-header-title">
                {{ activeRoom ? activeRoom.name : t('chatview.conversations') }}
              </h1>
              <span class="chat-status">{{ t('chatview.online') }}</span>
            </header>

            <!-- No room selected -->
            <div v-if="!activeRoom" class="chat-empty">
              <p>{{ t('chatview.select_room') }}</p>
            </div>

            <!-- Messages -->
            <template v-else>
              <div ref="messagesRef" class="messages">
                <div
                  v-for="msg in timeline"
                  :key="msg.id"
                  class="message-wrapper"
                  :class="msg.mine ? 'message-wrapper--user' : 'message-wrapper--bot'"
                >
                  <div class="message-bubble" :class="msg.mine ? 'message-bubble--user' : 'message-bubble--bot'">
                    <span v-if="!msg.mine && !activeRoom.isDm" class="message-sender">{{ msg.senderName }}</span>
                    <p class="message-text">{{ msg.body }}</p>
                    <span class="message-time">{{ timeFmt(msg.ts) }}</span>
                  </div>
                </div>
              </div>

              <!-- Typing indicator -->
              <div v-if="typingText" class="typing-indicator">{{ typingText }}</div>

              <!-- Input bar -->
              <footer class="chat-inputbar">
                <button class="icon-btn" :title="t('chatview.attach_file')">
                  <ConfigurableIcon name="CHAT_ATTACHMENT" :size="22" />
                </button>
                <textarea
                  v-model="input"
                  class="chat-input"
                  :placeholder="t('chatview.type_a_message')"
                  rows="1"
                  @keydown="handleKeydown"
                  @input="onComposerInput"
                />
                <button class="send-btn" :title="t('chatview.send')" :disabled="sending" @click="sendMessage">
                  <ConfigurableIcon name="CHAT_SEND" :size="18" />
                </button>
              </footer>
            </template>
          </template>
        </main>

        <!-- New chat / team room dialog -->
        <div v-if="dialogMode" class="chat-modal-overlay" @click.self="dialogMode = ''">
          <div class="chat-modal">
            <h2 class="chat-modal-title">
              {{ dialogMode === 'dm' ? t('chatview.new_chat') : t('chatview.new_team_room') }}
            </h2>
            <input
              v-if="dialogMode === 'team'"
              v-model="teamName"
              class="chat-modal-input"
              :placeholder="t('chatview.team_name_placeholder')"
            />
            <p class="chat-modal-label">
              {{ dialogMode === 'dm' ? t('chatview.pick_member_dm') : t('chatview.pick_members_team') }}
            </p>
            <div class="chat-modal-list">
              <p v-if="!directory.length" class="chat-modal-empty">
                {{ t('chatview.no_members_hint') }}
              </p>
              <button
                v-for="entry in directory"
                :key="entry.mxid"
                class="chat-modal-member"
                :class="{ 'chat-modal-member--selected': dialogMode === 'team' && isTeamSelected(entry) }"
                @click="dialogMode === 'dm' ? startDm(entry) : toggleTeamMember(entry)"
              >
                <span class="room-avatar">{{ initials(entry.display_name) }}</span>
                <span class="member-name">{{ entry.display_name }}</span>
                <span v-if="dialogMode === 'team' && isTeamSelected(entry)" class="member-check">✓</span>
              </button>
            </div>
            <div class="chat-modal-actions">
              <button class="btn-cancel" @click="dialogMode = ''">{{ t('chatview.cancel') }}</button>
              <button
                v-if="dialogMode === 'team'"
                class="btn-create"
                :disabled="!teamName.trim() || !teamSelection.length"
                @click="createTeam"
              >
                {{ t('chatview.create') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </ViewComposer>
</template>

<style scoped>
.community-page {
  position: absolute;
  inset: 0;
  display: flex;
  pointer-events: auto;
  background: #ffffff;
  user-select: none;
  z-index: 6;
  /* Clear the 72px AppDock strips on both sides: the docks (z-index 10,
     pointer-events auto) overlay the page, so any interactive content in the
     outer 72px would have its clicks eaten by the dock container. */
  padding: 0 72px;
  box-sizing: border-box;
}

/* ─── Left sidebar ─── */
.community-sidebar {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #f5f5f7;
  overflow-y: auto;
}

.community-sidebar::-webkit-scrollbar {
  width: 8px;
}

.community-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.community-sidebar::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 4px;
}

.community-sidebar::-webkit-scrollbar-thumb:hover {
  background: rgba(0, 0, 0, 0.25);
}

.sidebar-actions {
  display: flex;
  gap: 8px;
  padding: 16px 16px 8px;
}

.sidebar-action {
  flex: 1;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(209, 213, 219, 0.9);
  background: #ffffff;
  color: #1d1d1f;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.sidebar-action:hover:not(:disabled) {
  background: #eef2f7;
}

.sidebar-action:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.room-section {
  padding: 8px 8px 0;
}

.room-section-title {
  margin: 8px 8px 6px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #6e6e73;
}

.room-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 9px 10px;
  border: none;
  border-radius: 10px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
}

.room-item:hover {
  background: rgba(0, 0, 0, 0.05);
}

.room-item--active {
  background: rgba(59, 130, 246, 0.12);
}

.room-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #3b82f6;
  color: #ffffff;
  font-size: 0.9rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.room-avatar--team {
  background: #8b5cf6;
}

.room-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.room-name {
  font-size: 0.88rem;
  font-weight: 600;
  color: #1d1d1f;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-preview {
  font-size: 0.75rem;
  color: #6e6e73;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-time {
  font-size: 0.7rem;
  color: #9ca3af;
  flex-shrink: 0;
}

.sidebar-empty {
  padding: 24px 20px;
  font-size: 0.85rem;
  color: #6e6e73;
  text-align: center;
  line-height: 1.5;
}

/* ─── Divider ─── */
.community-divider {
  width: 4px;
  flex-shrink: 0;
  background: #e5e5ea;
  cursor: col-resize;
  transition: background 0.15s ease;
}

.community-divider:hover,
.community-divider:active {
  background: #007aff;
}

/* ─── Right content area ─── */
.community-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  overflow: hidden;
}

/* ─── Notice banners (green matches the Save/capture gates) ─── */
.chat-notice {
  margin: 16px 24px 0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.4;
}

.chat-notice--green {
  background: #e8f7ee;
  border: 1px solid #b7e4c7;
  color: #1a7f37;
}

.chat-notice--red {
  background: #fdecec;
  border: 1px solid #f5c2c2;
  color: #b3261e;
}

.chat-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6e6e73;
  font-size: 0.9rem;
  gap: 12px;
}

/* ─── Chat header ─── */
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
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-status {
  font-size: 0.75rem;
  font-weight: 600;
  color: #16a34a;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.chat-status::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}

/* ─── Messages ─── */
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
}

.message-wrapper--user {
  justify-content: flex-end;
}

.message-wrapper--bot {
  justify-content: flex-start;
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

.message-sender {
  font-size: 0.72rem;
  font-weight: 700;
  color: #6d28d9;
}

.message-text {
  margin: 0;
  line-height: 1.5;
  font-size: 0.95rem;
  user-select: text;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-time {
  font-size: 0.7rem;
  opacity: 0.7;
  align-self: flex-end;
}

.typing-indicator {
  padding: 0 24px 6px;
  font-size: 0.75rem;
  font-style: italic;
  color: #6e6e73;
}

/* ─── Input bar ─── */
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

.icon-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid rgba(209, 213, 219, 0.8);
  background: white;
  color: #4b5563;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.15s ease;
  flex-shrink: 0;
}

.icon-btn:hover {
  background: #f3f4f6;
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
  opacity: 0.6;
  cursor: default;
}

/* ─── New chat / team room dialog ─── */
.chat-modal-overlay {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}

.chat-modal {
  width: 380px;
  max-height: 70vh;
  background: #ffffff;
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-modal-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  color: #1d1d1f;
}

.chat-modal-input {
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid rgba(209, 213, 219, 0.9);
  font-size: 0.9rem;
  outline: none;
}

.chat-modal-input:focus {
  border-color: #3b82f6;
}

.chat-modal-label {
  margin: 0;
  font-size: 0.78rem;
  font-weight: 600;
  color: #6e6e73;
}

.chat-modal-list {
  flex: 1;
  min-height: 80px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.chat-modal-empty {
  padding: 20px 8px;
  font-size: 0.82rem;
  color: #6e6e73;
  text-align: center;
}

.chat-modal-member {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s ease;
}

.chat-modal-member:hover {
  background: rgba(0, 0, 0, 0.05);
}

.chat-modal-member--selected {
  background: rgba(59, 130, 246, 0.12);
}

.member-name {
  flex: 1;
  font-size: 0.9rem;
  font-weight: 600;
  color: #1d1d1f;
}

.member-check {
  color: #3b82f6;
  font-weight: 700;
}

.chat-modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.btn-cancel,
.btn-create {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.btn-cancel {
  border: 1px solid rgba(209, 213, 219, 0.9);
  background: #ffffff;
  color: #1d1d1f;
}

.btn-cancel:hover {
  background: #f3f4f6;
}

.btn-create {
  border: none;
  background: #3b82f6;
  color: #ffffff;
}

.btn-create:hover:not(:disabled) {
  background: #2563eb;
}

.btn-create:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

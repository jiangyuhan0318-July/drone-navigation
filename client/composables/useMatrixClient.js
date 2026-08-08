/**
 * useMatrixClient.js – module-level Matrix singleton for Community -> Chat.
 *
 * The user never sees Matrix: credentials are brokered by FastAPI
 * (GET /api/matrix/token, JWT-guarded) and cached in sessionStorage; the
 * client reaches Synapse through the same-origin /_matrix proxy (Vite dev
 * proxy locally, Caddy in production).
 *
 * bootstrap() is driven from ChatView (Community is the only Matrix
 * entrance); a module-level auth watcher tears the client down on logout and
 * re-bootstraps on login, so chat follows the website account automatically.
 */
import { computed, ref, watch } from 'vue';
import * as sdk from 'matrix-js-sdk';
import { useAuth } from '@shared-composables/useAuth.js';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';
const CRED_KEY = 'drone.matrix.creds';

/* Reactive state shared by every component instance. */
const ready = ref(false);
const error = ref(''); // '' | 'unavailable'
const myUserId = ref('');
const rooms = ref([]); // joined-room summaries, sorted by recency
const activeRoomId = ref('');
const timeline = ref([]); // m.text events of the active room
const typingNames = ref([]); // who is typing in the active room
const directory = ref([]); // chat-addressable site users (display_name+mxid)

let client = null;
let bootPromise = null;

/* ─── Credentials ─── */
async function fetchCreds() {
  const { token } = useAuth();
  const cached = sessionStorage.getItem(CRED_KEY);
  if (cached) {
    try {
      const creds = JSON.parse(cached);
      // Creds are bound to the app session that brokered them: after logout
      // or an account switch the cached Matrix identity must be discarded
      // (otherwise the next user would inherit the previous user's rooms).
      if (creds._auth_token === token.value) return creds;
    } catch { /* fall through to re-broker */ }
    sessionStorage.removeItem(CRED_KEY);
  }
  const res = await fetch(`${API_BASE}/api/matrix/token`, {
    headers: { Authorization: `Bearer ${token.value}` },
  });
  if (!res.ok) throw new Error(`matrix token HTTP ${res.status}`);
  const creds = await res.json();
  sessionStorage.setItem(CRED_KEY, JSON.stringify({ ...creds, _auth_token: token.value }));
  return creds;
}

/* ─── Room/timeline mapping ─── */
function directRoomIds() {
  const content = client?.getAccountData('m.direct')?.getContent() || {};
  return new Set(Object.values(content).flat());
}

function hasExplicitName(room) {
  return !!room.currentState.getStateEvents('m.room.name', '');
}

function isDmRoom(room, dmIds) {
  // Rooms we created as DMs are tracked in m.direct; rooms the peer created
  // show up with no explicit name and exactly two members.
  return dmIds.has(room.roomId)
    || (!hasExplicitName(room) && room.getJoinedMemberCount() === 2);
}

function lastTextOf(room) {
  const events = room.getLiveTimeline().getEvents();
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    if (ev.getType() === 'm.room.message' && ev.getContent()?.msgtype === 'm.text') {
      return ev.getContent().body || '';
    }
  }
  return '';
}

function refreshRooms() {
  if (!client) { rooms.value = []; return; }
  const dmIds = directRoomIds();
  const list = [];
  for (const room of client.getRooms()) {
    if (room.getMyMembership() !== 'join') continue;
    list.push({
      roomId: room.roomId,
      name: room.name || '…',
      isDm: isDmRoom(room, dmIds),
      members: room.getJoinedMemberCount(),
      preview: lastTextOf(room),
      lastTs: room.getLastActiveTimestamp(),
    });
  }
  list.sort((a, b) => b.lastTs - a.lastTs);
  rooms.value = list;
  if (activeRoomId.value) refreshTimeline();
}

function updateTyping(room) {
  if (!room || !client) { typingNames.value = []; return; }
  const me = client.getUserId();
  // matrix-js-sdk v42: typing state is member-based (RoomMember.typing);
  // Room.getTypingMembers() no longer exists.
  typingNames.value = room.getMembers()
    .filter((m) => m.typing && m.userId !== me)
    .map((m) => m.name);
}

function refreshTimeline() {
  if (!client || !activeRoomId.value) { timeline.value = []; typingNames.value = []; return; }
  const room = client.getRoom(activeRoomId.value);
  if (!room) { timeline.value = []; return; }
  const me = client.getUserId();
  const msgs = [];
  for (const ev of room.getLiveTimeline().getEvents()) {
    if (ev.getType() !== 'm.room.message') continue;
    const content = ev.getContent() || {};
    if (content.msgtype !== 'm.text' || typeof content.body !== 'string') continue;
    const senderId = ev.getSender();
    msgs.push({
      id: ev.getId(),
      senderId,
      senderName: room.getMember(senderId)?.name || senderId,
      body: content.body,
      ts: ev.getTs(),
      mine: senderId === me,
    });
  }
  timeline.value = msgs;
  updateTyping(room);
}

/* ─── Event wiring ───
 * Every handler body runs through safe(): a UI-mapping exception must NEVER
 * propagate back into the SDK — a throw inside Room.timeline handlers breaks
 * sendTextMessage (pending-event path) and aborts /sync room processing.
 */
function safe(fn) {
  try { fn(); } catch (err) { console.error('[matrix] UI refresh failed:', err); }
}

function wireEvents(c) {
  c.on('Room', () => safe(refreshRooms));
  c.on('Room.name', () => safe(refreshRooms));
  c.on('Room.receipt', () => safe(refreshRooms));
  c.on('Room.accountData', () => safe(refreshRooms));
  c.on('accountData', (event) => { if (event.getType() === 'm.direct') safe(refreshRooms); });
  c.on('Room.timeline', (event, room) => safe(() => {
    refreshRooms();
    if (room?.roomId === activeRoomId.value) {
      refreshTimeline();
      if (event.getSender() && event.getSender() !== c.getUserId()) markRead();
    }
  }));
  c.on('RoomMember.typing', (event, member) => safe(() => {
    if (member.roomId === activeRoomId.value) updateTyping(c.getRoom(activeRoomId.value));
  }));
  c.on('Room.myMembership', (room, membership) => safe(() => {
    // In-site chat v1: auto-accept invites so DMs/team rooms just appear.
    if (membership === 'invite') c.joinRoom(room.roomId).catch(() => {});
    refreshRooms();
  }));
}

/* ─── Lifecycle ─── */
async function bootstrap() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated.value) return false;
  if (client) return true;
  if (bootPromise) return bootPromise;

  bootPromise = (async () => {
    try {
      error.value = '';
      const creds = await fetchCreds();
      const c = sdk.createClient({
        baseUrl: window.location.origin, // same-origin /_matrix proxy
        accessToken: creds.access_token,
        userId: creds.user_id,
        deviceId: creds.device_id || undefined,
      });
      wireEvents(c);
      const synced = new Promise((resolve) => {
        const onSync = (state, prev, data) => {
          if (state === 'PREPARED') { c.removeListener('sync', onSync); resolve(true); }
          // Stale cached creds (e.g. Synapse DB reset): force re-broker next time.
          if (state === 'ERROR' && data?.error?.errcode === 'M_UNKNOWN_TOKEN') {
            sessionStorage.removeItem(CRED_KEY);
          }
        };
        c.on('sync', onSync);
      });
      await c.startClient({ initialSyncLimit: 30 });
      client = c;
      myUserId.value = creds.user_id;
      await synced;
      ready.value = true;
      refreshRooms();
      return true;
    } catch (err) {
      console.error('[matrix] bootstrap failed:', err);
      error.value = 'unavailable';
      teardown();
      return false;
    } finally {
      bootPromise = null;
    }
  })();
  return bootPromise;
}

function teardown() {
  if (client) {
    try { client.stopClient(); } catch { /* noop */ }
    client = null;
  }
  sessionStorage.removeItem(CRED_KEY);
  ready.value = false;
  error.value = '';
  myUserId.value = '';
  rooms.value = [];
  activeRoomId.value = '';
  timeline.value = [];
  typingNames.value = [];
}

/** Kept for API compatibility; the lockstep watch is module-level (below). */
function armAuthWatcher() {}

/* Login/logout lockstep: registered at module scope so it is NEVER disposed
 * with a component (a watch created inside onMounted dies on unmount, which
 * previously let stale Matrix identities survive account switches). This is
 * also requirement #3: logging into the website logs into Synapse, always.
 */
const { isAuthenticated: _isAuthenticated } = useAuth();
watch(_isAuthenticated, (authed) => {
  if (authed) bootstrap();
  else teardown();
});

/* ─── Chat actions ─── */
function markRead() {
  if (!client || !activeRoomId.value) return;
  const events = client.getRoom(activeRoomId.value)?.getLiveTimeline().getEvents() || [];
  const last = events[events.length - 1];
  if (last) client.sendReadReceipt(last).catch(() => {});
}

function setActiveRoom(roomId) {
  activeRoomId.value = roomId || '';
  refreshTimeline();
  markRead();
}

async function sendText(body) {
  const text = (body || '').trim();
  if (!client || !activeRoomId.value || !text) return;
  await client.sendTextMessage(activeRoomId.value, text);
  refreshTimeline();
  refreshRooms();
}

let typingTimer = null;
function noteTyping() {
  if (!client || !activeRoomId.value) return;
  client.sendTyping(activeRoomId.value, true, 4000).catch(() => {});
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => {
    client?.sendTyping(activeRoomId.value, false, 0).catch(() => {});
  }, 4000);
}

async function createDm(entry) {
  if (!client || !entry?.mxid) return '';
  const existing = (client.getAccountData('m.direct')?.getContent()?.[entry.mxid] || [])
    .find((id) => client.getRoom(id)?.getMyMembership() === 'join');
  if (existing) { setActiveRoom(existing); return existing; }
  const res = await client.createRoom({
    is_direct: true,
    invite: [entry.mxid],
    preset: 'trusted_private_chat',
  });
  const content = { ...(client.getAccountData('m.direct')?.getContent() || {}) };
  content[entry.mxid] = [res.room_id, ...(content[entry.mxid] || [])];
  await client.setAccountData('m.direct', content);
  refreshRooms();
  setActiveRoom(res.room_id);
  return res.room_id;
}

async function createTeamRoom(name, entries) {
  if (!client || !(name || '').trim()) return '';
  const res = await client.createRoom({
    name: name.trim(),
    invite: (entries || []).map((e) => e.mxid).filter(Boolean),
    preset: 'private_chat',
  });
  refreshRooms();
  setActiveRoom(res.room_id);
  return res.room_id;
}

async function fetchDirectory() {
  const { token } = useAuth();
  if (!token.value) { directory.value = []; return; }
  try {
    const res = await fetch(`${API_BASE}/api/directory/users`, {
      headers: { Authorization: `Bearer ${token.value}` },
    });
    directory.value = res.ok ? await res.json() : [];
  } catch { directory.value = []; }
}

const dms = computed(() => rooms.value.filter((r) => r.isDm));
const teamRooms = computed(() => rooms.value.filter((r) => !r.isDm));
const activeRoom = computed(() => rooms.value.find((r) => r.roomId === activeRoomId.value) || null);

export function useMatrixClient() {
  return {
    ready, error, myUserId,
    rooms, dms, teamRooms,
    activeRoomId, activeRoom, timeline, typingNames,
    directory,
    bootstrap, teardown, armAuthWatcher,
    setActiveRoom, sendText, noteTyping, markRead,
    createDm, createTeamRoom, fetchDirectory,
  };
}

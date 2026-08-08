import { ref, computed, onUnmounted } from 'vue';
import config from '../config.json';

const DEFAULT_URL = 'ws://127.0.0.1:18789';
const DEFAULT_SESSION_KEY = 'agent:main:main';
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_DELAY_MS = 30000;

// config.json is bundled at build time (static JSON import), so its URL is
// only correct for the machine the build was made on. Resolve at runtime:
//   1. An explicitly configured non-loopback URL always wins (custom gateway).
//   2. Pages served over HTTPS must use wss:// (browsers block ws:// as mixed
//      content), and 127.0.0.1 in a visitor's browser means THEIR machine —
//      so go through Caddy's /ws reverse proxy on the same origin instead.
//   3. Otherwise (local dev) keep the loopback gateway on this machine.
function resolveGatewayUrl() {
  const configured = config.openclaw?.url || '';
  const isLoopback = /^wss?:\/\/(127\.0\.0\.1|localhost)([:/]|$)/.test(configured);
  if (configured && !isLoopback) return configured;
  if (typeof window !== 'undefined' && window.location.protocol === 'https:') {
    return `wss://${window.location.host}/ws`;
  }
  return configured || DEFAULT_URL;
}

function generateId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function formatTime(timestamp) {
  const date = timestamp ? new Date(timestamp) : new Date();
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function extractText(message) {
  if (!message || typeof message !== 'object') return '';
  if (typeof message.text === 'string' && message.text.length > 0) return message.text;
  if (typeof message.content === 'string' && message.content.length > 0) return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .filter((block) => block && (block.type === 'text' || typeof block.text === 'string'))
      .map((block) => block.text)
      .join('\n');
  }
  return '';
}

// The OpenClaw gateway periodically emits a keep-alive assistant message whose
// text is "HEARTBEAT_OK". It is protocol plumbing, not conversation, so it must
// never be rendered as a chat bubble (live events or loaded history).
const HEARTBEAT_TEXT = 'HEARTBEAT_OK';

function isHeartbeatMessage(text) {
  return typeof text === 'string' && text.trim().toUpperCase() === HEARTBEAT_TEXT;
}

// True when a (possibly still-streaming) chunk can only be the keep-alive token,
// e.g. "HEART", "HEARTBEAT", "HEARTBEAT_OK". Used to suppress the partial bubble
// before the full token has arrived.
function isHeartbeatPrefix(text) {
  if (typeof text !== 'string') return false;
  const t = text.trim().toUpperCase();
  return t.length > 0 && HEARTBEAT_TEXT.startsWith(t);
}

export function useOpenClaw() {
  const ws = ref(null);
  const status = ref('idle'); // idle | connecting | connected | error | closed
  const error = ref(null);
  const messages = ref([]);
  const sessionKey = ref(null);
  const pendingRequests = new Map();

  let reconnectTimer = null;
  let reconnectDelay = RECONNECT_DELAY_MS;
  let challengeResolved = false;
  let intentionallyClosed = false;
  let partialRunIds = new Map();
  let heartbeatRunIds = new Set();

  const isConnected = computed(() => status.value === 'connected');

  const gatewayUrl = resolveGatewayUrl();
  const gatewayToken = config.openclaw?.token || '';

  function appendMessage(message) {
    messages.value.push(message);
    if (messages.value.length > 200) {
      messages.value.shift();
    }
  }

  function sendRaw(obj) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error('WebSocket is not open'));
    }
    const id = generateId();
    const frame = { ...obj, id };
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        pendingRequests.delete(id);
        reject(new Error(`Request ${obj.method || obj.event} timed out`));
      }, 30000);
      pendingRequests.set(id, { resolve, reject, timeout });
      ws.value.send(JSON.stringify(frame));
    });
  }

  function sendRequest(method, params = {}) {
    return sendRaw({ type: 'req', method, params });
  }

  function handleFrame(data) {
    let frame;
    try {
      frame = JSON.parse(data);
    } catch (e) {
      console.warn('[OpenClaw] Invalid JSON frame:', data);
      return;
    }

    if (frame.type === 'event') {
      if (frame.event === 'connect.challenge') {
        performHandshake(frame.payload);
        return;
      }
      if (frame.event === 'chat') {
        handleChatEvent(frame.payload);
        return;
      }
      return;
    }

    if (frame.type === 'res') {
      const pending = pendingRequests.get(frame.id);
      if (!pending) return;
      clearTimeout(pending.timeout);
      pendingRequests.delete(frame.id);
      if (frame.ok) {
        pending.resolve(frame.payload);
      } else {
        pending.reject(new Error(frame.error?.message || 'OpenClaw request failed'));
      }
    }
  }

  async function performHandshake(challengePayload) {
    if (challengeResolved) return;
    challengeResolved = true;

    try {
      await sendRequest('connect', {
        minProtocol: 4,
        maxProtocol: 4,
        client: {
          id: 'openclaw-control-ui',
          version: '1.0.0',
          platform: 'web',
          mode: 'webchat',
        },
        role: 'operator',
        scopes: ['operator.read', 'operator.write'],
        caps: [],
        auth: { token: gatewayToken },
      });

      status.value = 'connected';
      error.value = null;
      reconnectDelay = RECONNECT_DELAY_MS;
      await initSession();
      await loadHistory();
    } catch (e) {
      error.value = e.message || 'Handshake failed';
      status.value = 'error';
      close();
    }
  }

  async function initSession() {
    try {
      const list = await sendRequest('sessions.list', { limit: 1 });
      if (list?.sessions && list.sessions.length > 0 && list.sessions[0]?.key) {
        sessionKey.value = list.sessions[0].key;
        return;
      }
    } catch (e) {
      console.warn('[OpenClaw] sessions.list failed:', e.message);
    }

    try {
      const created = await sendRequest('sessions.create', {
        key: DEFAULT_SESSION_KEY,
        agentId: 'main',
      });
      if (created?.key) {
        sessionKey.value = created.key;
        return;
      }
    } catch (e) {
      console.warn('[OpenClaw] sessions.create failed:', e.message);
    }

    sessionKey.value = DEFAULT_SESSION_KEY;
  }

  async function loadHistory() {
    if (!sessionKey.value) return;
    try {
      const history = await sendRequest('chat.history', {
        sessionKey: sessionKey.value,
        limit: 50,
      });
      if (history?.messages && Array.isArray(history.messages)) {
        messages.value = history.messages
          .filter((entry) => {
            const role = typeof entry.role === 'string' ? entry.role.toLowerCase() : '';
            if (role !== 'user' && role !== 'assistant') return false;
            // Drop gateway keep-alive messages from the rendered history.
            return !isHeartbeatMessage(extractText(entry));
          })
          .map((entry) => ({
            id: entry.messageId || entry.id || generateId(),
            sender: entry.role.toLowerCase() === 'user' ? 'user' : 'bot',
            text: extractText(entry),
            time: formatTime(entry.timestamp),
          }));
      }
    } catch (e) {
      console.warn('[OpenClaw] Failed to load history:', e.message);
    }
  }

  function handleChatEvent(payload) {
    if (!payload || typeof payload !== 'object') return;
    const state = payload.state;
    const message = payload.message;
    const runId = payload.runId;
    const role = message?.role ? String(message.role).toLowerCase() : '';
    const text = extractText(message);

    if (role !== 'assistant' || !text) return;

    if (state === 'partial' && runId) {
      // A run that only ever streams the keep-alive token must not produce a
      // bubble. Track it and suppress every subsequent chunk for this run.
      if (heartbeatRunIds.has(runId)) return;
      if (isHeartbeatPrefix(text)) {
        heartbeatRunIds.add(runId);
        return;
      }
      const existing = partialRunIds.get(runId);
      if (existing) {
        existing.text = text;
      } else {
        const msg = {
          id: generateId(),
          sender: 'bot',
          text,
          time: formatTime(),
          runId,
        };
        partialRunIds.set(runId, msg);
        appendMessage(msg);
      }
      return;
    }

    if (state === 'final') {
      if (runId && heartbeatRunIds.has(runId)) {
        heartbeatRunIds.delete(runId);
        return;
      }
      // Ignore the gateway keep-alive message; it is not part of the conversation.
      if (isHeartbeatMessage(text)) return;
      if (runId && partialRunIds.has(runId)) {
        partialRunIds.delete(runId);
        return;
      }
      appendMessage({
        id: generateId(),
        sender: 'bot',
        text,
        time: formatTime(),
      });
    }
  }

  async function sendMessage(text) {
    const trimmed = text.trim();
    if (!trimmed) return;
    if (!isConnected.value || !sessionKey.value) {
      error.value = 'Not connected to OpenClaw gateway';
      return;
    }

    appendMessage({
      id: generateId(),
      sender: 'user',
      text: trimmed,
      time: formatTime(),
    });

    try {
      await sendRequest('chat.send', {
        sessionKey: sessionKey.value,
        message: trimmed,
        idempotencyKey: generateId(),
      });
    } catch (e) {
      error.value = e.message || 'Failed to send message';
    }
  }

  function connect() {
    if (ws.value || intentionallyClosed) return;
    status.value = 'connecting';
    error.value = null;
    challengeResolved = false;

    try {
      ws.value = new WebSocket(gatewayUrl);
    } catch (e) {
      error.value = e.message;
      status.value = 'error';
      scheduleReconnect();
      return;
    }

    ws.value.addEventListener('message', (event) => {
      handleFrame(event.data);
    });

    ws.value.addEventListener('close', () => {
      status.value = 'closed';
      ws.value = null;
      if (!intentionallyClosed) {
        scheduleReconnect();
      }
    });

    ws.value.addEventListener('error', () => {
      error.value = 'WebSocket error';
      status.value = 'error';
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer || intentionallyClosed) return;
    status.value = 'closed';
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
  }

  function close() {
    intentionallyClosed = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws.value) {
      ws.value.close();
      ws.value = null;
    }
  }

  onUnmounted(() => {
    close();
    pendingRequests.forEach((pending) => clearTimeout(pending.timeout));
    pendingRequests.clear();
  });

  connect();

  return {
    status,
    error,
    messages,
    isConnected,
    sendMessage,
    connect,
    close,
  };
}

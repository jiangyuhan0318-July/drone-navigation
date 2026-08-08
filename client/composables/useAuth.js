/**
 * Authentication state + API client for the FastAPI-Users backend.
 *
 * - Bearer JWT stored in localStorage; sent as `Authorization: Bearer <token>`.
 * - API base: in dev (Vite on :5173) calls go to http://localhost:8000; in
 *   production the SPA and API are same-origin behind Caddy (`/api/*`).
 * - Errors are thrown as `Error` with a `.code` property carrying an i18n key
 *   suffix (e.g. 'error_invalid_credentials') — components render them via
 *   `t('authflow.' + err.code)`.
 */

import { computed, ref } from 'vue';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';
const TOKEN_KEY = 'drone.auth.token';

const token = ref(localStorage.getItem(TOKEN_KEY) || '');
const user = ref(null);
let mePromise = null;

function setToken(value) {
  token.value = value || '';
  if (value) localStorage.setItem(TOKEN_KEY, value);
  else localStorage.removeItem(TOKEN_KEY);
}

function authError(code, fallback = 'error_generic') {
  const err = new Error(code || fallback);
  err.code = code || fallback;
  return err;
}

export function useAuth() {
  const isAuthenticated = computed(() => !!token.value);

  async function fetchMe() {
    if (!token.value) { user.value = null; return null; }
    if (!mePromise) {
      mePromise = (async () => {
        const res = await fetch(`${API_BASE}/api/users/me`, {
          headers: { Authorization: `Bearer ${token.value}` },
        });
        if (res.status === 401) { setToken(''); user.value = null; return null; }
        if (!res.ok) throw authError('error_generic');
        user.value = await res.json();
        return user.value;
      })().finally(() => { mePromise = null; });
    }
    return mePromise;
  }

  async function login(email, password) {
    const res = await fetch(`${API_BASE}/api/auth/jwt/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: email, password }),
    });
    if (!res.ok) {
      throw authError(
        res.status === 400 ? 'error_invalid_credentials' : 'error_generic',
      );
    }
    const data = await res.json();
    setToken(data.access_token);
    await fetchMe();
    return user.value;
  }

  async function register(email, password, displayName) {
    const res = await fetch(`${API_BASE}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: displayName || null }),
    });
    if (!res.ok) throw authError('error_register_failed');
    return res.json(); // fastapi-users does NOT log in on register
  }

  async function logout() {
    try {
      await fetch(`${API_BASE}/api/auth/jwt/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token.value}` },
      });
    } catch { /* local logout proceeds regardless */ }
    setToken('');
    user.value = null;
  }

  async function requestPasswordReset(email) {
    // Always 202 by design (does not reveal whether the email exists).
    await fetch(`${API_BASE}/api/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
  }

  async function resetPassword(resetToken, password) {
    const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: resetToken, password }),
    });
    if (!res.ok) throw authError('reset_error');
  }

  async function verifyEmail(verifyToken) {
    const res = await fetch(`${API_BASE}/api/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: verifyToken }),
    });
    if (!res.ok) throw authError('verify_error');
    return res.json();
  }

  async function googleLogin() {
    const res = await fetch(`${API_BASE}/api/auth/google/authorize`);
    if (!res.ok) throw authError('google_unavailable');
    const data = await res.json();
    if (!data.authorization_url) throw authError('google_unavailable');
    window.location.assign(data.authorization_url);
  }

  // SPA Google callback: forwards `code`/`state` to the API callback, which
  // returns the JWT as JSON (BearerTransport login response).
  async function handleOAuthCallback(search) {
    const res = await fetch(`${API_BASE}/api/auth/google/callback${search}`);
    if (!res.ok) throw authError('callback_error');
    const data = await res.json();
    if (!data.access_token) throw authError('callback_error');
    setToken(data.access_token);
    await fetchMe();
    return user.value;
  }

  return {
    token,
    user,
    isAuthenticated,
    fetchMe,
    login,
    register,
    logout,
    requestPasswordReset,
    resetPassword,
    verifyEmail,
    googleLogin,
    handleOAuthCallback,
  };
}

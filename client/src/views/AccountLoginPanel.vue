<script setup>
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useAuth } from '@shared-composables/useAuth.js';
import ConfigurableIcon from '@shared/ConfigurableIcon.vue';

const { t } = useI18n();
const {
  user,
  isAuthenticated,
  fetchMe,
  login,
  register,
  logout,
  requestPasswordReset,
  googleLogin,
} = useAuth();

/* 'login' | 'register' | 'forgot' */
const mode = ref('login');
const email = ref('');
const password = ref('');
const confirmPassword = ref('');
const displayName = ref('');
const showPassword = ref(false);
const showConfirmPassword = ref(false);
const busy = ref(false);
const errorKey = ref('');
const noticeKey = ref('');

const avatarInitial = computed(() => {
  const src = user.value?.display_name || user.value?.email || '';
  return src ? src.trim().charAt(0).toUpperCase() : '?';
});

onMounted(() => {
  if (isAuthenticated.value && !user.value) fetchMe().catch(() => {});
});

function resetFeedback() {
  errorKey.value = '';
  noticeKey.value = '';
}

function switchMode(next) {
  mode.value = next;
  resetFeedback();
}

function showError(err) {
  errorKey.value = `authflow.${err?.code || 'error_generic'}`;
}

async function submitLogin() {
  if (busy.value) return;
  busy.value = true;
  resetFeedback();
  try {
    await login(email.value.trim(), password.value);
  } catch (err) {
    showError(err);
  } finally {
    busy.value = false;
  }
}

async function submitRegister() {
  if (busy.value) return;
  if (password.value !== confirmPassword.value) {
    resetFeedback();
    errorKey.value = 'authflow.error_password_mismatch';
    return;
  }
  busy.value = true;
  resetFeedback();
  try {
    await register(email.value.trim(), password.value, displayName.value.trim());
    noticeKey.value = 'authflow.register_success';
    mode.value = 'login';
    password.value = '';
    confirmPassword.value = '';
  } catch (err) {
    showError(err);
  } finally {
    busy.value = false;
  }
}

async function submitForgot() {
  if (busy.value) return;
  busy.value = true;
  resetFeedback();
  try {
    await requestPasswordReset(email.value.trim());
    noticeKey.value = 'authflow.forgot_sent';
  } catch (err) {
    showError(err);
  } finally {
    busy.value = false;
  }
}

async function submitGoogle() {
  if (busy.value) return;
  busy.value = true;
  resetFeedback();
  try {
    await googleLogin(); // redirects away on success
  } catch (err) {
    showError(err);
    busy.value = false;
  }
}

async function submitLogout() {
  if (busy.value) return;
  busy.value = true;
  try {
    await logout();
  } finally {
    busy.value = false;
    resetFeedback();
    switchMode('login');
  }
}
</script>

<template>
  <div class="auth-panel">
    <!-- ─── Authenticated: profile card ─── -->
    <div v-if="isAuthenticated && user" class="auth-card">
      <div class="auth-avatar">{{ avatarInitial }}</div>
      <h2 class="auth-title">{{ user.display_name || user.email }}</h2>
      <p class="auth-subtitle">{{ user.email }}</p>
      <span
        class="auth-chip"
        :class="user.is_verified ? 'auth-chip--ok' : 'auth-chip--warn'"
      >
        {{ user.is_verified ? t('authflow.status_verified') : t('authflow.status_unverified') }}
      </span>
      <button class="auth-button auth-button--secondary" :disabled="busy" @click="submitLogout">
        {{ t('authflow.logout') }}
      </button>
    </div>

    <!-- ─── Anonymous: login / register / forgot ─── -->
    <div v-else class="auth-card">
      <!-- Tabs -->
      <div v-if="mode !== 'forgot'" class="auth-tabs">
        <button
          class="auth-tab"
          :class="{ 'auth-tab--active': mode === 'login' }"
          @click="switchMode('login')"
        >
          {{ t('authflow.tab_login') }}
        </button>
        <button
          class="auth-tab"
          :class="{ 'auth-tab--active': mode === 'register' }"
          @click="switchMode('register')"
        >
          {{ t('authflow.tab_register') }}
        </button>
      </div>

      <h2 v-if="mode === 'forgot'" class="auth-title">{{ t('authflow.forgot_title') }}</h2>
      <p v-if="mode === 'forgot'" class="auth-hint">{{ t('authflow.forgot_hint') }}</p>

      <!-- Feedback banners -->
      <p v-if="errorKey" class="auth-banner auth-banner--error">{{ t(errorKey) }}</p>
      <p v-if="noticeKey" class="auth-banner auth-banner--notice">{{ t(noticeKey) }}</p>

      <!-- Login form -->
      <form v-if="mode === 'login'" class="auth-form" @submit.prevent="submitLogin">
        <label class="auth-label">{{ t('authflow.email') }}</label>
        <input v-model="email" type="email" required class="auth-input" :placeholder="t('authflow.email_placeholder')" />
        <label class="auth-label">{{ t('authflow.password') }}</label>
        <div class="auth-password">
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            required
            class="auth-input auth-input--password"
            :placeholder="t('authflow.password_placeholder')"
          />
          <button
            type="button"
            class="auth-password__toggle"
            :title="t(showPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            :aria-label="t(showPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            @click="showPassword = !showPassword"
          >
            <ConfigurableIcon :name="showPassword ? 'PASSWORD_SHOW' : 'PASSWORD_HIDE'" :size="20" />
          </button>
        </div>
        <button type="submit" class="auth-button" :disabled="busy">
          {{ busy ? t('authflow.busy') : t('authflow.submit_login') }}
        </button>
        <button type="button" class="auth-link" @click="switchMode('forgot')">
          {{ t('authflow.forgot_link') }}
        </button>
      </form>

      <!-- Register form -->
      <form v-else-if="mode === 'register'" class="auth-form" @submit.prevent="submitRegister">
        <label class="auth-label">{{ t('authflow.display_name') }}</label>
        <input v-model="displayName" type="text" class="auth-input" :placeholder="t('authflow.display_name_placeholder')" />
        <label class="auth-label">{{ t('authflow.email') }}</label>
        <input v-model="email" type="email" required class="auth-input" :placeholder="t('authflow.email_placeholder')" />
        <label class="auth-label">{{ t('authflow.password') }}</label>
        <div class="auth-password">
          <input
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            required
            class="auth-input auth-input--password"
            :placeholder="t('authflow.password_placeholder')"
          />
          <button
            type="button"
            class="auth-password__toggle"
            :title="t(showPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            :aria-label="t(showPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            @click="showPassword = !showPassword"
          >
            <ConfigurableIcon :name="showPassword ? 'PASSWORD_SHOW' : 'PASSWORD_HIDE'" :size="20" />
          </button>
        </div>
        <label class="auth-label">{{ t('authflow.confirm_password') }}</label>
        <div class="auth-password">
          <input
            v-model="confirmPassword"
            :type="showConfirmPassword ? 'text' : 'password'"
            required
            class="auth-input auth-input--password"
            :placeholder="t('authflow.confirm_password_placeholder')"
          />
          <button
            type="button"
            class="auth-password__toggle"
            :title="t(showConfirmPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            :aria-label="t(showConfirmPassword ? 'authflow.password_hide' : 'authflow.password_show')"
            @click="showConfirmPassword = !showConfirmPassword"
          >
            <ConfigurableIcon :name="showConfirmPassword ? 'PASSWORD_SHOW' : 'PASSWORD_HIDE'" :size="20" />
          </button>
        </div>
        <button type="submit" class="auth-button" :disabled="busy">
          {{ busy ? t('authflow.busy') : t('authflow.submit_register') }}
        </button>
      </form>

      <!-- Forgot-password form -->
      <form v-else class="auth-form" @submit.prevent="submitForgot">
        <label class="auth-label">{{ t('authflow.email') }}</label>
        <input v-model="email" type="email" required class="auth-input" :placeholder="t('authflow.email_placeholder')" />
        <button type="submit" class="auth-button" :disabled="busy">
          {{ busy ? t('authflow.busy') : t('authflow.forgot_submit') }}
        </button>
        <button type="button" class="auth-link" @click="switchMode('login')">
          {{ t('authflow.back_to_login') }}
        </button>
      </form>

      <!-- Google OAuth -->
      <template v-if="mode !== 'forgot'">
        <div class="auth-divider">
          <span class="auth-divider__line" />
          <span class="auth-divider__text">{{ t('authflow.or_divider') }}</span>
          <span class="auth-divider__line" />
        </div>
        <button class="auth-button auth-button--google" :disabled="busy" @click="submitGoogle">
          {{ t('authflow.google_button') }}
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.auth-panel {
  display: flex;
  justify-content: center;
  padding-top: 24px;
}

.auth-card {
  width: 100%;
  max-width: 400px;
  background: #ffffff;
  border: 1px solid #e5e5ea;
  border-radius: 14px;
  padding: 28px 28px 24px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

/* Tabs */
.auth-tabs {
  display: flex;
  background: #f5f5f7;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 20px;
}

.auth-tab {
  flex: 1;
  padding: 8px 0;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
  color: #6e6e73;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.auth-tab--active {
  background: #ffffff;
  color: #1d1d1f;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.auth-title {
  margin: 0 0 6px;
  font-size: 1.15rem;
  font-weight: 600;
  color: #1d1d1f;
  text-align: center;
}

.auth-subtitle {
  margin: 0 0 10px;
  font-size: 0.9rem;
  color: #6e6e73;
  text-align: center;
}

.auth-hint {
  margin: 0 0 14px;
  font-size: 0.85rem;
  color: #6e6e73;
  text-align: center;
}

/* Banners */
.auth-banner {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 0.85rem;
  line-height: 1.4;
}

.auth-banner--error {
  background: #fff0f0;
  color: #c41e1e;
  border: 1px solid #ffd2d2;
}

.auth-banner--notice {
  background: #eef7ee;
  color: #1e7a1e;
  border: 1px solid #cbe8cb;
}

/* Form */
.auth-form {
  display: flex;
  flex-direction: column;
}

.auth-label {
  font-size: 0.8rem;
  font-weight: 500;
  color: #6e6e73;
  margin: 10px 0 4px;
}

.auth-input {
  padding: 10px 12px;
  border: 1px solid #d8d8dc;
  border-radius: 8px;
  font-size: 0.9rem;
  color: #1d1d1f;
  outline: none;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.auth-input:focus {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

/* Password visibility toggle */
.auth-password {
  position: relative;
  display: flex;
}

.auth-input--password {
  width: 100%;
  padding-right: 40px;
}

.auth-password__toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: none;
  color: #6e6e73;
  cursor: pointer;
  transition: color 0.15s ease, background 0.15s ease;
}

.auth-password__toggle:hover {
  color: #1d1d1f;
  background: rgba(0, 0, 0, 0.05);
}

.auth-button {
  margin-top: 18px;
  padding: 11px 0;
  border: none;
  border-radius: 8px;
  background: #007aff;
  color: #ffffff;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.auth-button:hover:not(:disabled) {
  background: #0066d6;
}

.auth-button:disabled {
  opacity: 0.6;
  cursor: default;
}

.auth-button--secondary {
  background: #f5f5f7;
  color: #1d1d1f;
}

.auth-button--secondary:hover:not(:disabled) {
  background: #e5e5ea;
}

.auth-button--google {
  margin-top: 0;
  background: #ffffff;
  color: #1d1d1f;
  border: 1px solid #d8d8dc;
}

.auth-button--google:hover:not(:disabled) {
  background: #f5f5f7;
}

.auth-link {
  margin-top: 12px;
  border: none;
  background: none;
  color: #007aff;
  font-size: 0.85rem;
  cursor: pointer;
  align-self: center;
}

.auth-link:hover {
  text-decoration: underline;
}

/* Divider */
.auth-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 20px 0;
}

.auth-divider__line {
  flex: 1;
  height: 1px;
  background: #e5e5ea;
}

.auth-divider__text {
  font-size: 0.8rem;
  color: #6e6e73;
}

/* Profile */
.auth-avatar {
  width: 64px;
  height: 64px;
  margin: 0 auto 12px;
  border-radius: 50%;
  background: #007aff;
  color: #ffffff;
  font-size: 1.6rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.auth-chip {
  align-self: center;
  margin: 4px 0 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 600;
}

.auth-chip--ok {
  background: #eef7ee;
  color: #1e7a1e;
}

.auth-chip--warn {
  background: #fff7e6;
  color: #a06a00;
}
</style>

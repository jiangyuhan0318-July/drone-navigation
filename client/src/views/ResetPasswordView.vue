<script setup>
import { ref } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useAuth } from '@shared-composables/useAuth.js';

const { t } = useI18n();
const route = useRoute();
const { resetPassword } = useAuth();

/* 'form' | 'success' | 'error' */
const state = ref('form');
const password = ref('');
const confirmPassword = ref('');
const busy = ref(false);
const mismatch = ref(false);

async function submit() {
  if (busy.value) return;
  mismatch.value = password.value !== confirmPassword.value;
  if (mismatch.value) return;
  busy.value = true;
  try {
    await resetPassword(String(route.query.token || ''), password.value);
    state.value = 'success';
  } catch {
    state.value = 'error';
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-page__card">
      <template v-if="state === 'form'">
        <h2 class="auth-page__title">{{ t('authflow.reset_title') }}</h2>
        <p v-if="mismatch" class="auth-page__text auth-page__text--error">
          {{ t('authflow.error_password_mismatch') }}
        </p>
        <form class="auth-page__form" @submit.prevent="submit">
          <input
            v-model="password"
            type="password"
            required
            class="auth-page__input"
            :placeholder="t('authflow.new_password_placeholder')"
          />
          <input
            v-model="confirmPassword"
            type="password"
            required
            class="auth-page__input"
            :placeholder="t('authflow.confirm_password_placeholder')"
          />
          <button type="submit" class="auth-page__button" :disabled="busy">
            {{ busy ? t('authflow.busy') : t('authflow.reset_submit') }}
          </button>
        </form>
      </template>
      <template v-else-if="state === 'success'">
        <p class="auth-page__text auth-page__text--ok">{{ t('authflow.reset_success') }}</p>
        <router-link to="/myspace" class="auth-page__link">{{ t('authflow.go_myspace') }}</router-link>
      </template>
      <template v-else>
        <p class="auth-page__text auth-page__text--error">{{ t('authflow.reset_error') }}</p>
        <router-link to="/myspace" class="auth-page__link">{{ t('authflow.go_myspace') }}</router-link>
      </template>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #ffffff;
  z-index: 6;
}

.auth-page__card {
  width: 100%;
  max-width: 400px;
  padding: 32px;
  border: 1px solid #e5e5ea;
  border-radius: 14px;
  text-align: center;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.auth-page__title {
  margin: 0 0 16px;
  font-size: 1.1rem;
  font-weight: 600;
  color: #1d1d1f;
}

.auth-page__form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.auth-page__input {
  padding: 10px 12px;
  border: 1px solid #d8d8dc;
  border-radius: 8px;
  font-size: 0.9rem;
  outline: none;
}

.auth-page__input:focus {
  border-color: #007aff;
  box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.15);
}

.auth-page__button {
  margin-top: 6px;
  padding: 11px 0;
  border: none;
  border-radius: 8px;
  background: #007aff;
  color: #ffffff;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
}

.auth-page__button:hover:not(:disabled) { background: #0066d6; }
.auth-page__button:disabled { opacity: 0.6; cursor: default; }

.auth-page__text {
  margin: 0 0 16px;
  font-size: 0.95rem;
  color: #1d1d1f;
}

.auth-page__text--ok { color: #1e7a1e; }
.auth-page__text--error { color: #c41e1e; }

.auth-page__link {
  color: #007aff;
  font-size: 0.9rem;
  text-decoration: none;
}

.auth-page__link:hover { text-decoration: underline; }
</style>

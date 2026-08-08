<script setup>
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useAuth } from '@shared-composables/useAuth.js';

// Landing page for the Google OAuth flow: Google redirects here with
// ?code=...&state=..., we forward them to the API callback which returns
// the JWT as JSON, then drop the user into My Space.
const { t } = useI18n();
const router = useRouter();
const { handleOAuthCallback } = useAuth();

/* 'pending' | 'error' (success navigates away) */
const state = ref('pending');

onMounted(async () => {
  try {
    await handleOAuthCallback(window.location.search);
    router.replace('/myspace');
  } catch {
    state.value = 'error';
  }
});
</script>

<template>
  <div class="auth-page">
    <div class="auth-page__card">
      <p v-if="state === 'pending'" class="auth-page__text">{{ t('authflow.callback_pending') }}</p>
      <template v-else>
        <p class="auth-page__text auth-page__text--error">{{ t('authflow.callback_error') }}</p>
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
  max-width: 400px;
  padding: 32px;
  border: 1px solid #e5e5ea;
  border-radius: 14px;
  text-align: center;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.auth-page__text {
  margin: 0 0 16px;
  font-size: 0.95rem;
  color: #1d1d1f;
}

.auth-page__text--error { color: #c41e1e; }

.auth-page__link {
  color: #007aff;
  font-size: 0.9rem;
  text-decoration: none;
}

.auth-page__link:hover { text-decoration: underline; }
</style>

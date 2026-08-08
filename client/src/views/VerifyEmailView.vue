<script setup>
import { onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from 'vue-i18n';
import { useAuth } from '@shared-composables/useAuth.js';

const { t } = useI18n();
const route = useRoute();
const { verifyEmail } = useAuth();

/* 'pending' | 'success' | 'error' */
const state = ref('pending');

onMounted(async () => {
  try {
    await verifyEmail(String(route.query.token || ''));
    state.value = 'success';
  } catch {
    state.value = 'error';
  }
});
</script>

<template>
  <div class="auth-page">
    <div class="auth-page__card">
      <p v-if="state === 'pending'" class="auth-page__text">{{ t('authflow.verify_pending') }}</p>
      <template v-else-if="state === 'success'">
        <p class="auth-page__text auth-page__text--ok">{{ t('authflow.verify_success') }}</p>
        <router-link to="/myspace" class="auth-page__link">{{ t('authflow.go_myspace') }}</router-link>
      </template>
      <template v-else>
        <p class="auth-page__text auth-page__text--error">{{ t('authflow.verify_error') }}</p>
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

.auth-page__text--ok { color: #1e7a1e; }
.auth-page__text--error { color: #c41e1e; }

.auth-page__link {
  color: #007aff;
  font-size: 0.9rem;
  text-decoration: none;
}

.auth-page__link:hover { text-decoration: underline; }
</style>

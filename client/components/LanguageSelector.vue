<script setup>
import { watch } from 'vue';
import { useI18n } from 'vue-i18n';

const { locale } = useI18n();

watch(locale, (newLocale) => {
  localStorage.setItem('user-lang', newLocale);
});
</script>

<template>
  <select v-model="locale" class="language-selector">
    <option value="en">EN</option>
    <option value="zh">中文</option>
  </select>
</template>

<style scoped>
.language-selector {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid rgba(156, 163, 175, 0.4);
  background: rgba(255, 255, 255, 0.95);
  color: #374151;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s ease;
}

.language-selector:hover {
  border-color: #3b82f6;
}

.language-selector:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
}
</style>

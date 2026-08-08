<script setup>
import { ref, watchEffect } from 'vue';
import { useI18n } from 'vue-i18n';

const props = defineProps({
  docPath: {
    type: String,
    required: true,
  },
});

const { locale } = useI18n();
const htmlContent = ref('');
const loadError = ref(null);

watchEffect(async () => {
  const currentLocale = locale.value;
  try {
    // Attempt to load the locale-specific HTML file.
    const mod = await import(`../../assets/docs/${props.docPath}.${currentLocale}.html?raw`);
    htmlContent.value = mod.default;
    loadError.value = null;
  } catch (e) {
    // Fallback to English if the locale-specific file is missing.
    try {
      const mod = await import(`../../assets/docs/${props.docPath}.en.html?raw`);
      htmlContent.value = mod.default;
      loadError.value = null;
    } catch (fallbackError) {
      htmlContent.value = '';
      loadError.value = fallbackError.message;
    }
  }
});
</script>

<template>
  <div class="localized-page">
    <div v-if="loadError" class="localized-page__error">
      <p>{{ loadError }}</p>
    </div>
    <div v-else v-html="htmlContent" class="localized-page__content" />
  </div>
</template>

<style scoped>
.localized-page {
  width: 100%;
  height: 100%;
  overflow-y: auto;
}

.localized-page__content {
  padding: 24px;
  font-family: 'Segoe UI', Calibri, sans-serif;
  line-height: 1.6;
  color: #f8fafc;
}

.localized-page__error {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #f87171;
  font-size: 0.9rem;
}
</style>

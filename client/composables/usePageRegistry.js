import { reactive } from 'vue';

const pages = reactive([]);

export function usePageRegistry() {
  function registerPage(page) {
    // Avoid duplicate registrations
    const idx = pages.findIndex((p) => p.id === page.id);
    if (idx >= 0) {
      pages.splice(idx, 1, page);
    } else {
      pages.push(page);
    }
  }

  function unregisterPage(id) {
    const idx = pages.findIndex((p) => p.id === id);
    if (idx >= 0) pages.splice(idx, 1);
  }

  function clearPages() {
    pages.length = 0;
  }

  return {
    pages,
    registerPage,
    unregisterPage,
    clearPages,
  };
}

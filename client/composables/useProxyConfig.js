/**
 * useProxyConfig.js – singleton reactive store for proxy configuration.
 * Shared between ExtensionsView (editable) and SettingsView (read-only display).
 */
import { reactive, computed } from 'vue';

const state = reactive({
  os: 'MacOS for MacBook',
  login: 'droner',
  password: 'welcome',
  httpHost: '8.221.124.43',
  httpPort: 3128,
  httpsHost: '8.221.124.43',
  httpsPort: 3128,
  socksHost: '8.221.124.43',
  socksPort: 3128,
  ignoreHosts: 'localhost,127.0.0.1,192.168.*,*.local,*.internal',
});

const OS_OPTIONS = ['Android', 'iOS for iPhone', 'Windows', 'MacOS for MacBook', 'Linux'];

export function useProxyConfig() {
  function buildUrl(host, port) {
    const creds = state.login && state.password
      ? `${state.login}:${state.password}@`
      : state.login
        ? `${state.login}@`
        : '';
    return `http://${creds}${host}:${port}`;
  }

  const httpProxy = computed(() => buildUrl(state.httpHost, state.httpPort));
  const httpsProxy = computed(() => buildUrl(state.httpsHost, state.httpsPort));
  const noProxy = computed(() => state.ignoreHosts);

  return {
    proxyConfig: state,
    OS_OPTIONS,
    httpProxy,
    httpsProxy,
    noProxy,
  };
}

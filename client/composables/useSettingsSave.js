/**
 * useSettingsSave.js – Save-button flow shared by MySpaceView & SettingsView.
 *
 * Case 1 (authenticated): PUT the whole settings envelope to the backend,
 *   then flash a green "saved" notice at the top of the right panel.
 * Case 2 (anonymous / expired token): redirect to My Space > Account and
 *   flash a green "please log in" notice at the top of that panel instead.
 *
 * The notice state is module-level so it survives the Settings -> My Space
 * navigation (SettingsView unmounts while MySpaceView mounts).
 */
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';
import { useAppSettings } from '@shared-composables/useAppSettings.js';
import { useAuth } from '@shared-composables/useAuth.js';

const API_BASE = import.meta.env.DEV ? 'http://localhost:8000' : '';

/* '' | 'saved' | 'login_required' | 'save_failed' */
const saveNotice = ref('');
let noticeTimer = null;

function flash(key, ms = 6000) {
  saveNotice.value = key;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { saveNotice.value = ''; }, ms);
}

export function useSettingsSave() {
  const router = useRouter();
  const route = useRoute();
  const { locale } = useI18n();
  const { token, isAuthenticated } = useAuth();
  const { settings } = useAppSettings();

  /** Shape must mirror server/app/schemas.py::SettingsDocument. */
  function buildDocument() {
    return {
      version: 1,
      locale: locale.value,
      font: { fontFamily: settings.fontFamily, fontSize: settings.fontSize },
      media: { audioVolume: settings.audioVolume },
      network: { enterpriseProxy: settings.enterpriseProxy },
      flight: {
        takeoffAltitude: settings.takeoffAltitude,
        safetyBuffer: settings.safetyBuffer,
        defaultLat: settings.defaultLat,
        defaultLon: settings.defaultLon,
        defaultAlt: settings.defaultAlt,
        defaultYaw: settings.defaultYaw,
        defaultPitch: settings.defaultPitch,
        defaultRoll: settings.defaultRoll,
      },
    };
  }

  function goLogin() {
    flash('login_required');
    if (route.path !== '/myspace' || route.query.sub !== 'account') {
      router.push('/myspace?sub=account');
    }
    return false;
  }

  async function saveSettings() {
    if (!isAuthenticated.value || !token.value) return goLogin();
    let resp;
    try {
      resp = await fetch(`${API_BASE}/api/users/me/settings`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token.value}`,
        },
        body: JSON.stringify(buildDocument()),
      });
    } catch {
      flash('save_failed'); // network down / API unreachable
      return false;
    }
    if (resp.status === 401) return goLogin(); // token expired mid-session
    if (!resp.ok) {
      flash('save_failed');
      return false;
    }
    flash('saved');
    return true;
  }

  return { saveNotice, saveSettings };
}

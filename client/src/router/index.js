import { createRouter, createWebHistory } from 'vue-router';
import AerialView from '@/views/AerialView.vue';
import RealDroneView from '@/views/RealDroneView.vue';
import MeshView from '@/views/MeshView.vue';
import Map2DView from '@/views/Map2DView.vue';
import Satellite2DView from '@/views/Satellite2DView.vue';
import ChatView from '@/views/ChatView.vue';
import SettingsView from '@/views/SettingsView.vue';
import MySpaceView from '@/views/MySpaceView.vue';
import ExtensionsView from '@/views/ExtensionsView.vue';

const routes = [
  {
    path: '/',
    name: 'Aerial',
    component: AerialView,
  },
  {
    path: '/real-drone',
    name: 'RealDrone',
    component: RealDroneView,
  },
  {
    path: '/mesh',
    name: 'Mesh3D',
    component: MeshView,
  },
  {
    path: '/map',
    name: 'Map2D',
    component: Map2DView,
  },
  {
    path: '/satellite',
    name: 'Satellite2D',
    component: Satellite2DView,
  },
  {
    path: '/chat',
    name: 'Chat',
    component: ChatView,
  },
  {
    path: '/customer-service',
    name: 'CustomerService',
    component: () => import('@/views/CustomerServiceView.vue'),
  },
  {
    path: '/copilot',
    name: 'Copilot',
    component: () => import('@/views/CopilotView.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
  },
  {
    path: '/myspace',
    name: 'MySpace',
    component: MySpaceView,
  },
  {
    // Auth flow action pages (email links + Google OAuth landing)
    path: '/verify-email',
    name: 'VerifyEmail',
    component: () => import('@/views/VerifyEmailView.vue'),
  },
  {
    path: '/reset-password',
    name: 'ResetPassword',
    component: () => import('@/views/ResetPasswordView.vue'),
  },
  {
    path: '/auth/callback',
    name: 'AuthCallback',
    component: () => import('@/views/AuthCallbackView.vue'),
  },
  {
    path: '/extensions',
    name: 'Extensions',
    component: ExtensionsView,
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;

<template>
  <transition name="flash">
    <div v-if="visible" class="collision-warning">
      <span class="collision-warning__icon">⚠</span>
      <span class="collision-warning__text">{{ $t('collisionwarning.warning') }}</span>
      <span class="collision-warning__icon">⚠</span>
    </div>
  </transition>
</template>

<script setup>
defineProps({
  visible: {
    type: Boolean,
    default: false,
  },
});
</script>

<style scoped>
.collision-warning {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 12px 28px;
  border-radius: 8px;
  background: rgba(220, 20, 60, 0.88);
  color: #ffffff;
  font-family: Calibri, 'Segoe UI', sans-serif;
  font-size: 0.77rem;
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
  pointer-events: none;
  z-index: 100;
  box-shadow: 0 0 18px rgba(220, 20, 60, 0.9);
  animation: warningPulse 1s ease-in-out infinite;
}

.collision-warning__icon {
  font-size: 1.2rem;
  line-height: 1;
}

.collision-warning__text {
  letter-spacing: 0.02em;
}

@keyframes warningPulse {
  0%,
  100% {
    opacity: 1;
    box-shadow: 0 0 18px rgba(220, 20, 60, 0.9);
  }
  50% {
    opacity: 0.72;
    box-shadow: 0 0 42px rgba(220, 20, 60, 1);
  }
}

.flash-enter-active,
.flash-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.flash-enter-from,
.flash-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-12px);
}
</style>

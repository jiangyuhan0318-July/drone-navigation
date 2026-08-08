import { useDrone } from './useDrone.js';
import { useCameraCommands } from './useCameraCommands.js';

const ROTATION_SPEED = 60.0; // degrees per second at full deflection

export function useCameraPhysics() {
  const { gimbal } = useDrone();
  const { cameraCmd, activeCameraMode, camera } = useCameraCommands();

  function step(dt, { applyMovement = true } = {}) {
    if (!applyMovement) return;

    // Z -> yaw, Y -> pitch, X -> roll.
    if (activeCameraMode.value === 'Z') {
      gimbal.yaw += cameraCmd.yaw * ROTATION_SPEED * dt;
      camera.yaw = cameraCmd.yaw;
      camera.pitch = 0;
      camera.roll = 0;
    } else if (activeCameraMode.value === 'Y') {
      gimbal.pitch += cameraCmd.pitch * ROTATION_SPEED * dt;
      camera.yaw = 0;
      camera.pitch = cameraCmd.pitch;
      camera.roll = 0;
    } else if (activeCameraMode.value === 'X') {
      gimbal.roll += cameraCmd.roll * ROTATION_SPEED * dt;
      camera.yaw = 0;
      camera.pitch = 0;
      camera.roll = cameraCmd.roll;
    }
  }

  return { step };
}

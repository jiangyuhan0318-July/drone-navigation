#!/bin/bash
# Gesture Launcher — starts the gesture pipeline in one go:
#   1. gesture_recognizer.py — MediaPipe 手势识别服务, HTTP :8700
#      (吃视频流: 默认本地摄像头; 无人机接上后切 RTSP)
#   2. gesture_control.py    — 手势→飞行动作执行器 (默认 DRY-RUN 只打日志)
#
# Usage:
#   ./start_gesture.sh              # 识别 + dry-run 执行器
#   ./start_gesture.sh --live       # 识别 + 真发命令 (需 gate 打开 + 无人机在线)
#   ./start_gesture.sh --source rtsp://127.0.0.1:8554/crazyflie-drone
#   ./start_gesture.sh --stop       # 停止全部手势进程
#
# Environment:
#   GESTURE_SOURCE   — 视频源 (默认 0 = 本地摄像头; 或 rtsp://127.0.0.1:8554/crazyflie-drone)
#   GESTURE_PORT     — 手势服务端口 (默认 8700)
#   GESTURE_TOKEN    — server 若配了 telemetry_token 则须带上
#
# Example (无人机已接, 走共享视频流, 真发命令):
#   GESTURE_SOURCE="rtsp://127.0.0.1:8554/crazyflie-drone" ./start_gesture.sh --live

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_PY="${CONDA_PY:-$HOME/miniconda3/envs/drone-navigation/bin/python}"
GESTURE_SOURCE="${GESTURE_SOURCE:-0}"
GESTURE_PORT="${GESTURE_PORT:-8700}"

if ! command -v "$CONDA_PY" >/dev/null 2>&1; then
  echo "conda python not found at $CONDA_PY — set CONDA_PY" >&2
  exit 1
fi

stop_all() {
  pkill -f "gesture_recognizer.py" 2>/dev/null
  pkill -f "gesture_control.py" 2>/dev/null
  echo "[Gesture] all gesture processes stopped"
}

case "${1:-}" in
  --stop) stop_all; exit 0 ;;
esac

if pgrep -f "gesture_recognizer.py" >/dev/null 2>&1; then
  echo "[Gesture] recognizer already running on :$GESTURE_PORT — skipping"
else
  echo "[Gesture] recognizer: source=$GESTURE_SOURCE port=$GESTURE_PORT"
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" gesture_recognizer.py \
     --input "$GESTURE_SOURCE" --port "$GESTURE_PORT" \
     > "$SCRIPT_DIR/../logs/gesture.log" 2>&1) &
fi

LIVE_FLAG=""
[[ "${1:-}" == "--live" ]] && LIVE_FLAG="--live"
echo "[Gesture] executor: ${LIVE_FLAG:-DRY-RUN}"
(cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" gesture_control.py $LIVE_FLAG \
   --token "${GESTURE_TOKEN:-}" \
   > "$SCRIPT_DIR/../logs/gesture_control.log" 2>&1) &

echo "[Gesture] logs: logs/gesture.log, logs/gesture_control.log"
echo "[Gesture] API:  curl http://127.0.0.1:${GESTURE_PORT}/gesture"
echo "[Gesture] Ctrl+C 或 ./start_gesture.sh --stop 停止"
trap stop_all INT
wait

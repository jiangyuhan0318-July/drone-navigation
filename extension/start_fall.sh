#!/bin/bash
# Fall Launcher — starts the fall-detection pipeline in one go:
#   1. fall_recognizer.py — MediaPipe Pose 跌倒检测服务, HTTP :8704
#      (视频源默认本地摄像头; 无人机接上后可切 RTSP)
#   2. fall_control.py    — 摔倒 → 起飞执行器 (默认 DRY-RUN 只打日志)
#
# Usage:
#   ./start_fall.sh              # 识别 + dry-run 执行器
#   ./start_fall.sh --live       # 识别 + 真发命令 (需 gate 打开 + 无人机在线)
#   ./start_fall.sh --source rtsp://127.0.0.1:8554/crazyflie-drone
#   ./start_fall.sh --stop       # 停止全部跌倒进程
#
# Environment:
#   FALL_SOURCE   — 视频源 (默认 0 = 本地摄像头; 或 rtsp://127.0.0.1:8554/crazyflie-drone)
#   FALL_PORT     — 跌倒服务端口 (默认 8704)
#   FALL_TOKEN    — server 若配了 telemetry_token 则须带上
#   FALL_SHOW=1   — 开 /video 流: http://127.0.0.1:$FALL_PORT/video 可看实时画面
#
# Example (无人机已接, 走共享视频流, 真发命令):
#   FALL_SOURCE="rtsp://127.0.0.1:8554/crazyflie-drone" ./start_fall.sh --live

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_PY="${CONDA_PY:-$HOME/miniconda3/envs/drone-navigation/bin/python}"
FALL_SOURCE="${FALL_SOURCE:-0}"
FALL_PORT="${FALL_PORT:-8704}"

if ! command -v "$CONDA_PY" >/dev/null 2>&1; then
  echo "conda python not found at $CONDA_PY — set CONDA_PY" >&2
  exit 1
fi

stop_all() {
  pkill -f "fall_recognizer.py" 2>/dev/null
  pkill -f "fall_control.py" 2>/dev/null
  echo "[Fall] all fall processes stopped"
}

case "${1:-}" in
  --stop) stop_all; exit 0 ;;
esac

if pgrep -f "fall_recognizer.py" >/dev/null 2>&1; then
  echo "[Fall] recognizer already running on :$FALL_PORT — skipping"
else
  SHOW_FLAG=""
  [[ "${FALL_SHOW:-0}" == "1" ]] && SHOW_FLAG="--show"
  echo "[Fall] recognizer: source=$FALL_SOURCE port=$FALL_PORT ${SHOW_FLAG}"
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" fall_recognizer.py \
     --source "$FALL_SOURCE" --port "$FALL_PORT" $SHOW_FLAG \
     > "$SCRIPT_DIR/../logs/fall.log" 2>&1) &
fi

LIVE_FLAG=""
[[ "${1:-}" == "--live" ]] && LIVE_FLAG="--live"
echo "[Fall] executor: ${LIVE_FLAG:-DRY-RUN}"
(cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" fall_control.py $LIVE_FLAG \
   --token "${FALL_TOKEN:-}" \
   > "$SCRIPT_DIR/../logs/fall_control.log" 2>&1) &

echo "[Fall] logs: logs/fall.log, logs/fall_control.log"
echo "[Fall] API:  curl http://127.0.0.1:${FALL_PORT}/fall"
echo "[Fall] Ctrl+C 或 ./start_fall.sh --stop 停止"
trap stop_all INT
wait

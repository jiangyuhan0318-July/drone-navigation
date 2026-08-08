#!/bin/bash
# Posture Guardian Launcher — 姿态守护两件套一键启动 (手势控制同款模式):
#   1. posture_guardian.py — 姿态检测服务, HTTP :8703 (默认本机摄像头)
#   2. posture_control.py  — 姿态 → 告警/动作执行器 (默认 DRY-RUN)
#
# Usage:
#   ./start_posture.sh                       # 识别 + dry-run 执行器 (本机摄像头)
#   ./start_posture.sh --source 0            # 指定摄像头索引
#   ./start_posture.sh --source rtsp://127.0.0.1:8554/crazyflie-drone
#   ./start_posture.sh --live                # 真发命令 (ACTION_MAP 配了才有)
#   ./start_posture.sh --stop                # 停止全部姿态进程
#
# Environment:
#   POSTURE_SOURCE  — 视频源 (默认 0 = 本机摄像头)
#   POSTURE_PORT    — 姿态服务端口 (默认 8703)
#   POSTURE_TOKEN   — server 若配了 telemetry_token 则须带上

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_PY="${CONDA_PY:-$HOME/miniconda3/envs/drone-navigation/bin/python}"
POSTURE_SOURCE="${POSTURE_SOURCE:-0}"
POSTURE_PORT="${POSTURE_PORT:-8703}"
LOG_DIR="$SCRIPT_DIR/../logs"

stop_all() {
  pkill -f "posture_guardian.py" 2>/dev/null
  pkill -f "posture_control.py" 2>/dev/null
  echo "[Posture] all posture processes stopped"
}

case "${1:-}" in
  --stop) stop_all; exit 0 ;;
esac

mkdir -p "$LOG_DIR"
LIVE_FLAG=""
[[ "$*" == *--live* ]] && LIVE_FLAG="--live"

if pgrep -f "posture_guardian.py" >/dev/null 2>&1; then
  echo "[Posture] recognizer already running on :$POSTURE_PORT — skipping"
else
  echo "[Posture] recognizer: source=$POSTURE_SOURCE port=$POSTURE_PORT"
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" posture_guardian.py \
     --source "$POSTURE_SOURCE" --port "$POSTURE_PORT" \
     > "$LOG_DIR/posture_guardian.log" 2>&1) &
fi

echo "[Posture] executor: ${LIVE_FLAG:-DRY-RUN}"
(cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" posture_control.py $LIVE_FLAG \
   --token "${POSTURE_TOKEN:-}" > "$LOG_DIR/posture_control.log" 2>&1) &

echo "[Posture] logs: logs/posture_guardian.log, logs/posture_control.log"
echo "[Posture] API:  curl http://127.0.0.1:${POSTURE_PORT}/posture"
echo "[Posture] Ctrl+C 或 ./start_posture.sh --stop 停止"
trap stop_all INT
wait

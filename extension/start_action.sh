#!/bin/bash
# Action Launcher — starts the body-action pipeline in one go:
#   1. action_recognizer.py — MediaPipe Pose 身体动作识别 (双手举起/双臂交叉/T字展开), HTTP :8706
#   2. action_control.py    — 姿态事件 → 服务端姿态状态机 (默认 DRY-RUN 只打日志)
#
# 姿态语义 (服务端 drone_commands.py):
#   hands_up 双手举起 → 进入准备确认 / arms_crossed 双臂交叉 → 取消待确认
#   t_pose T字展开 → 切换姿态控制模式
#
# Usage:
#   ./start_action.sh              # 识别 + dry-run 执行器
#   ./start_action.sh --live       # 识别 + 真发事件 (仅状态位, 飞行仍走门控)
#   ./start_action.sh --source rtsp://127.0.0.1:8554/crazyflie-drone
#   ./start_action.sh --stop       # 停止全部动作进程
#
# Environment:
#   ACTION_SOURCE   — 视频源 (默认 0 = 本地摄像头; 或 rtsp://...)
#   ACTION_PORT     — 识别服务端口 (默认 8706)
#   ACTION_TOKEN    — server 若配了 telemetry_token 则须带上
#   ACTION_SHOW=1   — 开 /video 流: http://127.0.0.1:$ACTION_PORT/video 可看实时画面
#
# 注意: 摄像头同一时刻只能被一个进程占用 — 手势/坐姿/跌倒/守护中心
# 运行时先停掉 (./start_*.sh --stop)。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_PY="${CONDA_PY:-$HOME/miniconda3/envs/drone-navigation/bin/python}"
ACTION_SOURCE="${ACTION_SOURCE:-0}"
ACTION_PORT="${ACTION_PORT:-8706}"

if ! command -v "$CONDA_PY" >/dev/null 2>&1; then
  echo "conda python not found at $CONDA_PY — set CONDA_PY" >&2
  exit 1
fi

stop_all() {
  pkill -f "action_recognizer.py" 2>/dev/null
  pkill -f "action_control.py" 2>/dev/null
  echo "[Action] all action processes stopped"
}

case "${1:-}" in
  --stop) stop_all; exit 0 ;;
esac

if pgrep -f "action_recognizer.py" >/dev/null 2>&1; then
  echo "[Action] recognizer already running on :$ACTION_PORT — skipping"
else
  SHOW_FLAG=""
  [[ "${ACTION_SHOW:-0}" == "1" ]] && SHOW_FLAG="--show"
  echo "[Action] recognizer: source=$ACTION_SOURCE port=$ACTION_PORT ${SHOW_FLAG}"
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" action_recognizer.py \
     --source "$ACTION_SOURCE" --port "$ACTION_PORT" $SHOW_FLAG \
     > "$SCRIPT_DIR/../logs/action.log" 2>&1) &
fi

LIVE_FLAG=""
[[ "${1:-}" == "--live" ]] && LIVE_FLAG="--live"
echo "[Action] executor: ${LIVE_FLAG:-DRY-RUN}"
(cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" action_control.py $LIVE_FLAG \
   ${ACTION_TOKEN:+--token "$ACTION_TOKEN"} \
   > "$SCRIPT_DIR/../logs/action_control.log" 2>&1) &

echo "[Action] logs: logs/action.log, logs/action_control.log"
echo "[Action] API:  curl http://127.0.0.1:${ACTION_PORT}/action"
echo "[Action] Ctrl+C 或 ./start_action.sh --stop 停止"
trap stop_all INT
wait

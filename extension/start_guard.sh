#!/bin/bash
# Guard Center Launcher — 统一守护中心 (单进程单端口, 检测模式四选一)
#   1. guard_center.py   — 一路摄像头, 一次只跑一个检测 (模式制), HTTP :8705
#   2. guard_control.py  — 统一执行器: 读 /status 当前模式自动跟随, 视频不断
#
# 仪表盘: 浏览器打开 http://127.0.0.1:8705/  (实时视频 + 状态面板 + 模式切换按钮)
# 切模式 = 检测+控制一起换 (统一执行器自动跟随), 视频流始终不断:
#   仪表盘点按钮 或 curl -X PUT :8705/mode -d '{"mode":"fall"}'
#
# 模式 → 无人机动作:
#   gesture 👍起飞 ✌️降落 🖐急停 ✊悬停 ☝️前 👎后 🤟左 👌右
#   posture 坐姿不端正 → 起飞 0.5m     fall 摔倒 → 起飞 0.5m
#   action 🙌急停 🙅降落 ⭐姿态状态机
#
# Usage:
#   ./start_guard.sh                     # 初始模式=手势 (GUARD_MODE 可覆盖)
#   ./start_guard.sh --mode=fall         # 初始模式=跌倒
#   ./start_guard.sh --mode=action --live   # 初始模式=动作 + 真发命令
#   ./start_guard.sh --stop              # 停止全部守护进程
#
# Environment:
#   GUARD_MODE    — 初始检测模式 gesture|posture|fall|action (默认 gesture, 可 --mode 覆盖)
#   GUARD_SOURCE  — 视频源 (默认 0 = 本地摄像头; 或 rtsp://...)
#   GUARD_PORT    — 端口 (默认 8705)
#   GUARD_TOKEN   — server 若配了 telemetry_token 则须带上
#
# 注意: 摄像头同一时刻只能被一个进程占用 — 起守护中心前, 独立的
# gesture/posture/fall/action 服务必须已停止 (./start_*.sh --stop)。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_PY="${CONDA_PY:-$HOME/miniconda3/envs/drone-navigation/bin/python}"
GUARD_SOURCE="${GUARD_SOURCE:-0}"
GUARD_PORT="${GUARD_PORT:-8705}"
MODE="${GUARD_MODE:-gesture}"
LIVE_FLAG=""

for a in "$@"; do
  case "$a" in
    --live)       LIVE_FLAG="--live" ;;
    --stop)       pkill -f "guard_center.py" 2>/dev/null
                  pkill -f "guard_control.py" 2>/dev/null
                  echo "[Guard] all guard processes stopped"
                  exit 0 ;;
    --mode=*)     MODE="${a#--mode=}" ;;
  esac
done

case "$MODE" in
  gesture|posture|fall|action) ;;
  *) echo "[Guard] 非法模式: $MODE (gesture|posture|fall|action)" >&2; exit 1 ;;
esac

if ! command -v "$CONDA_PY" >/dev/null 2>&1; then
  echo "conda python not found at $CONDA_PY — set CONDA_PY" >&2
  exit 1
fi

if pgrep -f "guard_center.py" >/dev/null 2>&1; then
  echo "[Guard] guard_center already running — 同步模式: PUT /mode $MODE"
  curl -s -X PUT "http://127.0.0.1:${GUARD_PORT}/mode" \
    -H "Content-Type: application/json" \
    -d "{\"mode\":\"$MODE\"}" >/dev/null 2>&1 \
    && echo "[Guard] 模式已切到 $MODE" \
    || echo "[Guard] 注意: PUT /mode 失败 (中心是否起在 :$GUARD_PORT ?)"
else
  echo "[Guard] guard_center: source=$GUARD_SOURCE port=$GUARD_PORT mode=$MODE"
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" guard_center.py \
     --source "$GUARD_SOURCE" --port "$GUARD_PORT" --mode "$MODE" \
     > "$SCRIPT_DIR/../logs/guard_center.log" 2>&1) &
fi

TOKEN_FLAG=""
[[ -n "${GUARD_TOKEN:-}" ]] && TOKEN_FLAG="--token $GUARD_TOKEN"

# 统一执行器 (guard_control.py): 读 /status 当前模式, 自动跟随切换 —
# 网页/HTTP 切模式后控制立即跟着走, 不需要重启执行器。
echo "[Guard] 模式: $MODE 执行器: ${LIVE_FLAG:-DRY-RUN}"
if pgrep -f "guard_control.py" >/dev/null 2>&1; then
  echo "[Guard] guard_control.py already running — 跳过 (避免重复执行器)"
else
  (cd "$SCRIPT_DIR" && PYTHONUNBUFFERED=1 "$CONDA_PY" guard_control.py $LIVE_FLAG \
     $TOKEN_FLAG \
     > "$SCRIPT_DIR/../logs/guard_control.log" 2>&1) &
fi

echo "[Guard] logs: logs/guard_center.log, logs/guard_control.log"
echo "[Guard] dashboard: http://127.0.0.1:${GUARD_PORT}/  (切模式: 面板按钮或"
echo "         curl -X PUT :${GUARD_PORT}/mode -d '{\"mode\":\"$MODE\"}')"
echo "[Guard] Ctrl+C 或 ./start_guard.sh --stop 停止"
trap 'pkill -f "guard_center.py" 2>/dev/null; pkill -f "guard_control.py" 2>/dev/null' INT
wait

#!/usr/bin/env python3
"""action_control.py — 身体动作事件 → 无人机动作执行器

消费识别服务 (:8706 独立版 或 :8705 守护中心) 的确认姿态事件, 上升沿执行一次:

    recognizer (Webcam, MediaPipe)  →  /action (state, last_event)
    action_control (本脚本)         →  POST /api/drone/action (飞行动令)

动作语义 (用户定义, 2026-08-07):
  - hands_up     双手举起   → 急停 (estop, 安全通道, 不受门控)
  - arms_crossed 双臂交叉   → 降落 (land)
  - t_pose       T 字展开   → 姿态状态机事件 (切换姿态控制模式, 不直接飞)

安全护栏 (与手势/跌倒执行器同构):
  - 默认 DRY-RUN 只打日志, --live 才真发命令
  - estop/land 永远可恢复 (服务端不设门控); 起飞类才受飞行门控
  - STALE_S=3: 识别服务/链路断后不误发
  - EVENT_COOLDOWN_S=3: 同一姿态重复确认不刷屏

Usage:
  python action_control.py                      # dry-run
  python action_control.py --live               # 真发命令
Env: COPILOT_BASE (默认 http://127.0.0.1:8000), ACTION_URL (默认 :8706/action)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("COPILOT_BASE", "http://127.0.0.1:8000").rstrip("/")
ACTION_URL = os.environ.get("ACTION_URL", "http://127.0.0.1:8706/action").rstrip("/")

POLL_S = 0.5            # 轮询识别服务
STALE_S = 3.0           # 超过此时长没刷新 → 链路断
EVENT_COOLDOWN_S = 3.0  # 事件冷却: 同一姿态重复确认不刷屏 (识别器已有 2.5s)

TOKEN = os.environ.get("COPILOT_TOKEN", "")

POSE_LABELS = {"hands_up": "双手举起", "arms_crossed": "双臂交叉",
               "t_pose": "T字展开"}

# ── 动作映射: 姿态 → (action, params) ──────────────────────────────────────
# estop/land 永远可恢复 (服务端不设门控); 若以后要起飞类需受飞行门控。
# t_pose 不进映射 — 保持姿态状态机事件 (切换姿态控制模式, 不直接飞)。
ACTION_MAP = {
    "hands_up":     ("estop", {}),      # 🙌 双手举起 → 急停 (安全通道)
    "arms_crossed": ("land", {}),       # 🙅 双臂交叉 → 降落
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    url = f"{BASE}{path}"
    if TOKEN:
        url += ("&" if "?" in path else "?") + f"token={TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def get_action_state(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def send_command(action: str, params: dict) -> dict:
    """POST /api/drone/action — 与手势/跌倒执行器同一条命令通道。"""
    return _api("/api/drone/action", method="POST", body={
        "action": action, **params, "source": "extension_action",
    })


def send_pose_event(pose: str, confidence: float, held_ms: int) -> dict:
    """t_pose 专用: 姿态状态机事件 (切换姿态控制模式, 不直接飞)。"""
    return _api("/api/pose/event", method="POST", body={
        "pose": pose,
        "confidence": confidence,
        "held_ms": held_ms,
        "source": "extension_action",
        "timestamp_ms": int(time.time() * 1000),
    })


def main() -> int:
    ap = argparse.ArgumentParser(prog="action_control.py", description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="真发姿态事件 (默认 dry-run 只打日志)")
    ap.add_argument("--token", default="", help="server telemetry_token (如有)")
    ap.add_argument("--action-url", default=ACTION_URL,
                    help="身体动作服务 URL (默认 :8706/action; 守护中心为 "
                         ":8705/action)")
    args = ap.parse_args()

    if args.token:
        os.environ["COPILOT_TOKEN"] = args.token

    log(f"action_control 启动 mode={'LIVE' if args.live else 'DRY-RUN'} "
        f"recognizer={args.action_url} base={BASE}")
    log(f"护栏: STALE_S={STALE_S}, 事件冷却 {EVENT_COOLDOWN_S}s")

    last_event_ts = None   # 已消费的 last_event.ts (上升沿记忆)
    last_fired_at = 0.0    # 上次 POST 时间 (冷却记忆)
    stale_logged = False

    while True:
        st = get_action_state(args.action_url)
        now = time.time()

        if "error" in st:
            if not stale_logged:
                log(f"识别服务不可达: {st['error']} — 等待中 (不发送任何事件)")
                stale_logged = True
            time.sleep(POLL_S)
            continue
        stale_logged = False

        ev = st.get("last_event")
        if not ev:
            time.sleep(POLL_S)
            continue

        ev_ts = ev.get("ts", 0)
        fresh = now - ev_ts <= STALE_S
        if not fresh:
            time.sleep(POLL_S)
            continue

        if ev_ts == last_event_ts:
            time.sleep(POLL_S)
            continue  # 同一事件, 已处理过
        last_event_ts = ev_ts

        if now - last_fired_at < EVENT_COOLDOWN_S:
            continue  # 事件刚发过, 冷却内

        pose = ev.get("pose", "none")
        label = POSE_LABELS.get(pose, pose)
        log(f"!! 姿态确认: {label} (conf={ev.get('confidence')} "
            f"held={ev.get('held_ms')}ms)")

        if not args.live:
            # dry-run: 说明这个姿态本应执行的动作
            mapped = ACTION_MAP.get(pose)
            if mapped:
                action, params = mapped
                log(f"  [DRY-RUN] 本应 POST /api/drone/action: {label} → "
                    f"{action} {params or ''}")
            else:
                log(f"  [DRY-RUN] t_pose 本应 POST /api/pose/event: "
                    f"切换姿态控制模式")
            last_fired_at = now
            continue

        mapped = ACTION_MAP.get(pose)
        if mapped:
            action, params = mapped
            r = send_command(action, params)
            if "error" in r:
                log(f"  ✋ {action} 命令失败: {r['error']}")
                continue
            log(f"  → {action} 已下发: {r.get('status') or r.get('result') or r}")
            last_fired_at = now
            continue

        # t_pose: 姿态状态机事件 (切换姿态控制模式, 不直接飞)
        r = send_pose_event(pose, ev.get("confidence", 0.0), ev.get("held_ms", 0))
        last_fired_at = now
        if "error" in r:
            log(f"  ✋ POST 失败: {r['error']}")
            continue
        effect = r.get("effect", "?")
        detail = r.get("detail") or ""
        pending = (r.get("pending_action") or {})
        log(f"  → effect={effect}{(' (' + detail + ')') if detail else ''} "
            f"pending={'有' if pending.get('active') else '无'} "
            f"ready={(r.get('pose_state') or {}).get('ready_for_confirmation')}")


if __name__ == "__main__":
    sys.exit(main())

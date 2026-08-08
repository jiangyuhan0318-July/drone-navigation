#!/usr/bin/env python3
"""guard_control.py — 守护中心统一执行器 (四模式合一)

替代四个独立执行器: 读 /status 里的当前模式, 只消费该模式的事件,
网页/HTTP 切模式 (PUT /mode) 后控制自动跟随 — 视频流始终不断。

    guard_center (:8705)  →  /status {mode, gesture, posture, fall, action}
    guard_control (本脚本) →  POST /api/drone/action (飞行动令, 按模式映射)
                             POST /api/pose/event (仅 action 的 t_pose)

模式 → 动作映射 (用户定义, 2026-08-07):
  gesture  👍起飞 / ✌️降落 / 🖐急停 / ✊悬停 / ☝️前 / 👎后 / 🤟左 / 👌右
  posture  坐姿不端正 (head_down/too_close) → 起飞 0.5m
  fall     摔倒确认 → 起飞 0.5m
  action   🙌双手举起→急停, 🙅双臂交叉→降落, ⭐T字展开→姿态状态机 (不直接飞)

安全护栏 (与各独立执行器一致):
  - 默认 DRY-RUN 只打日志, --live 才真发
  - estop/land/stop 永远可恢复 (服务端不设门控); takeoff 类受飞行门控
    + 电量护栏 (起飞前查电量, <BATTERY_FLOOR_V 拒绝)
  - STALE_S=3: 识别服务/链路断后不误发
  - 事件冷却 2-3s: 同一事件不刷屏

Usage:
  python guard_control.py                # dry-run
  python guard_control.py --live         # 真发命令
  python guard_control.py --live --height 1.0   # 起飞高度 1.0m
Env: COPILOT_BASE (默认 http://127.0.0.1:8000), GUARD_BASE (默认 :8705)
"""
import argparse
import json
import os
import sys
import time
import urllib.request

GUARD_BASE = os.environ.get("GUARD_BASE", "http://127.0.0.1:8705").rstrip("/")
BASE = os.environ.get("COPILOT_BASE", "http://127.0.0.1:8000").rstrip("/")

POLL_S = 0.5            # 轮询守护中心
STALE_S = 3.0           # 事件/状态超过此时长 → 视为断链不误发
COOLDOWN_S = 3.0        # 同一事件触发后冷却
BATTERY_FLOOR_V = 3.5   # 起飞前电量下限

TOKEN = os.environ.get("COPILOT_TOKEN", "")

# ── 模式 → 动作映射 (各独立执行器 ACTION_MAP 汇总) ─────────────────────────
# estop/land/stop 永远可恢复; takeoff/forward/back/left/right 受门控。
ACTION_MAP = {
    "gesture": {
        "Thumb_Up":    ("takeoff", {"height": 0.5}),   # 👍 起飞
        "Victory":     ("land", {}),                   # ✌️ 降落
        "Open_Palm":   ("estop", {}),                  # 🖐 急停
        "Closed_Fist": ("stop", {}),                   # ✊ 悬停
        "Pointing_Up": ("forward", {"distance": 0.3}), # ☝️ 向前
        "Thumb_Down":  ("back", {"distance": 0.3}),    # 👎 向后
        "ILoveYou":    ("left", {"distance": 0.3}),    # 🤟 向左
        "OK":          ("right", {"distance": 0.3}),   # 👌 向右
    },
    "posture": {
        "head_down": ("takeoff", {"height": 0.5}),     # 坐姿不端正 → 起飞
        "too_close": ("takeoff", {"height": 0.5}),
    },
    "fall": {
        "alert": ("takeoff", {"height": 0.5}),         # 摔倒确认 → 起飞
    },
    "action": {
        "hands_up":     ("estop", {}),                 # 🙌 双手举起 → 急停
        "arms_crossed": ("land", {}),                  # 🙅 双臂交叉 → 降落
    },
}

GESTURE_EMOJI = {"Closed_Fist": "✊", "Open_Palm": "🖐", "Pointing_Up": "☝️",
                 "Thumb_Down": "👎", "Thumb_Up": "👍", "Victory": "✌️",
                 "ILoveYou": "🤟", "OK": "👌"}
POSTURE_LABEL = {"head_down": "坐姿不端正(低头)", "too_close": "坐姿不端正(过近)",
                 "normal": "正常", "unknown": "未知"}
ACTION_LABEL = {"hands_up": "🙌双手举起", "arms_crossed": "🙅双臂交叉",
                "t_pose": "⭐T字展开"}
TAKEOFF_POSE = {"takeoff"}


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


def get_center_status() -> dict:
    try:
        with urllib.request.urlopen(f"{GUARD_BASE}/status", timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def battery_ok() -> tuple[bool, str]:
    """起飞前电量护栏 (estop/land/stop 不查)。"""
    status = _api("/api/copilot/status")
    if "error" in status:
        return True, f"status 不可达 ({status['error']}) — 由 server 兜底"
    v = ((status.get("telemetry") or {}).get("battery") or {}).get("voltage")
    if v is None:
        return True, "无电量数据 — 由 server 兜底"
    if v < BATTERY_FLOOR_V:
        return False, f"电量过低 ({v:.2f}V < {BATTERY_FLOOR_V}V) — 拒绝起飞"
    return True, f"电量 {v:.2f}V OK"


def send_command(action: str, params: dict) -> dict:
    return _api("/api/drone/action", method="POST", body={
        "action": action, **params, "source": "guard_control",
    })


def send_pose_event(pose: str, confidence: float, held_ms: int) -> dict:
    """t_pose 专用: 姿态状态机事件 (切换姿态控制模式, 不直接飞)。"""
    return _api("/api/pose/event", method="POST", body={
        "pose": pose, "confidence": confidence, "held_ms": held_ms,
        "source": "guard_control", "timestamp_ms": int(time.time() * 1000),
    })


def fire(mode: str, name: str, conf: float, live: bool, height: float):
    """事件 → (映射) → dry-run 日志 或 真发命令。返回 True 表示已消费 (吃冷却)。"""
    mapped = ACTION_MAP.get(mode, {}).get(name)
    label = ({"gesture": lambda: f"{GESTURE_EMOJI.get(name, '')} {name}",
              "posture": lambda: POSTURE_LABEL.get(name, name),
              "fall": lambda: f"摔倒确认",
              "action": lambda: ACTION_LABEL.get(name, name)}[mode])()
    if mapped:
        action, params = mapped
        # 起飞高度统一为 --height 参数值
        if action == "takeoff":
            params = {**params, "height": height}
        log(f"!! [{mode}] {label} (conf={conf:.2f}) → {action} {params or ''}")
        if not live:
            log(f"  [DRY-RUN] 本应 POST /api/drone/action: {action} {params or ''}")
            return True
        if action in TAKEOFF_POSE:
            ok, reason = battery_ok()
            if not ok:
                log(f"  ✋ {reason} — 不下发, 事件已消费")
                return True
        r = send_command(action, params)
        log(f"  → delivered={r.get('delivered')} reason={r.get('reason')} "
            f"result={r.get('result') or r.get('status') or ''}")
        return True
    # t_pose 等未映射动作: 发姿态状态机事件 (不直接飞)
    if mode == "action" and name == "t_pose":
        log(f"!! [action] {label} (conf={conf:.2f}) → 姿态状态机")
        if not live:
            log(f"  [DRY-RUN] 本应 POST /api/pose/event: 切换姿态控制模式")
            return True
        r = send_pose_event(name, conf, 0)
        log(f"  → effect={r.get('effect', '?')} detail={r.get('detail') or ''}")
        return True
    log(f"!! [{mode}] {label} (conf={conf:.2f}) — 未绑定动作, 忽略")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(prog="guard_control.py", description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="真发命令 (默认 dry-run 只打日志)")
    ap.add_argument("--token", default="", help="server telemetry_token (如有)")
    ap.add_argument("--height", type=float, default=0.5,
                    help="坐姿/摔倒响应起飞高度 (0.1-1.5m, 默认 0.5)")
    args = ap.parse_args()
    if args.token:
        os.environ["COPILOT_TOKEN"] = args.token

    log(f"guard_control 启动 mode={'LIVE' if args.live else 'DRY-RUN'} "
        f"center={GUARD_BASE} base={BASE} 起飞高度={args.height}m")
    log(f"护栏: 电量 <{BATTERY_FLOOR_V}V 拒绝起飞, 事件冷却 {COOLDOWN_S}s, "
        f"STALE_S={STALE_S}")

    last_ev = {"gesture": None, "posture": 0.0, "fall": 0.0, "action": 0.0}
    last_fired_at = 0.0
    stale_logged = False
    last_mode = None

    while True:
        st = get_center_status()
        now = time.time()

        if "error" in st:
            if not stale_logged:
                log(f"守护中心不可达: {st['error']} — 等待中 (不发送任何命令)")
                stale_logged = True
            time.sleep(POLL_S)
            continue
        stale_logged = False

        mode = st.get("mode", "gesture")
        if mode != last_mode:
            last_mode = mode
            log(f"模式 → {mode} (控制跟随切换)")
            # 模式变化: 清空各模式事件记忆, 避免旧模式残留事件跨模式触发
            last_ev = {"gesture": None, "posture": 0.0, "fall": 0.0, "action": 0.0}
            last_fired_at = 0.0

        # ── 手势: rising-edge on 手势值 + 新鲜度 (gesture_control 原模型) ──
        if mode == "gesture":
            g = st.get("gesture")
            fresh_s = st.get("gesture_fresh_s")
            if g is None or fresh_s is None or fresh_s > STALE_S:
                last_ev["gesture"] = None
            elif g != last_ev["gesture"]:
                last_ev["gesture"] = g
                if now - last_fired_at < COOLDOWN_S:
                    log(f"手势 {GESTURE_EMOJI.get(g, '')} {g} 冷却中 "
                        f"({COOLDOWN_S}s) — 忽略抖动重触发")
                else:
                    fire(mode, g, st.get("gesture_conf") or 0.0,
                         args.live, args.height)
                    last_fired_at = now
            time.sleep(POLL_S)
            continue

        # ── 其余: last_event.ts 上升沿模型 ──
        ev_key = {"posture": "posture_event", "fall": "fall_event",
                  "action": "action_event"}[mode]
        ev = st.get(ev_key)
        if not ev:
            time.sleep(POLL_S)
            continue
        ev_ts = ev.get("ts", 0)
        if now - ev_ts > STALE_S:
            time.sleep(POLL_S)
            continue
        if ev_ts == last_ev[mode]:
            time.sleep(POLL_S)
            continue
        last_ev[mode] = ev_ts

        if now - last_fired_at < COOLDOWN_S:
            log(f"[{mode}] 事件冷却中 ({COOLDOWN_S}s) — 忽略")
            continue

        # fall 事件无 state 字段 (事件本身即摔倒确认); 其余模式取 state/pose
        if mode == "fall":
            name = "alert"
        else:
            name = ev.get("state") or ev.get("pose")
        if name is None:
            time.sleep(POLL_S)
            continue
        fire(mode, name, ev.get("confidence") or 0.0, args.live, args.height)
        last_fired_at = now
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())

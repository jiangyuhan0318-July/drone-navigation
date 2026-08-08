#!/usr/bin/env python3
"""
gesture_control.py — 手势 → 飞行动作执行器

轮询手势服务 (:8700/gesture), 按映射表把"手势变化"翻译成飞行动令,
经 /api/copilot/command 下发 —— 与网页 HUD / OpenClaw 同一条验证过的
门控链路, 不是直连 CRTP。

安全设计:
  - 上升沿触发: 手势"变化"才执行一次, 持续比同一个手势不会重复发令
  - 过期保护: 手势数据 > 1s 未更新 (fresh_s) 视为失效, 不动作
  - 默认 --dry-run: 只打印将要下发的命令, 不发真命令; 加 --live 才真发
  - estop/land/stop 不受飞行门控限制 (永远可恢复); takeoff 受门控,
    gate 未开时 server 返回 flight_gate_off (本脚本原样打印)

Usage:
  python gesture_control.py                     # dry-run: 只打日志
  python gesture_control.py --live              # 真发命令
  python gesture_control.py --gesture-url http://127.0.0.1:8700
  python gesture_control.py --token <token>     # 若 server 配了 telemetry_token
"""
import argparse
import json
import time
import urllib.request

GESTURE_URL = "http://127.0.0.1:8700/gesture"
COMMAND_URL = "http://127.0.0.1:8000/api/copilot/command"

# ── 映射表: 手势 → (action, params) ────────────────────────────────────────
# estop/land/stop 永远可恢复; takeoff/forward/back/left/right 受飞行门控 (gate) 限制。
MAP = {
    "Thumb_Up":     ("takeoff", {"height": 0.5}),     # 👍 起飞
    "Victory":      ("land", {}),                     # ✌️ 降落
    "Open_Palm":    ("estop", {}),                    # 🖐 急停 (安全通道)
    "Closed_Fist":  ("stop", {}),                     # ✊ 悬停
    "Pointing_Up":  ("forward", {"distance": 0.3}),   # ☝️ 向前
    "Thumb_Down":   ("back", {"distance": 0.3}),      # 👎 向后
    "ILoveYou":     ("left", {"distance": 0.3}),      # 🤟 向左
    "OK":           ("right", {"distance": 0.3}),     # 👌 向右 (自定义手势)
}

STALE_S = 1.0    # 手势数据超过该秒数视为过期, 不触发
POLL_S = 0.5     # 轮询间隔
COOLDOWN_S = 2.0 # 同一手势触发后冷却: 识别抖动 (手势→None→同手势) 时
                 # 短时间内的重复检测不重复发令, 防止命令连发把飞机推乱


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_gesture():
    try:
        with urllib.request.urlopen(GESTURE_URL, timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "gesture": None, "fresh_s": None}


def send_command(action, params, token):
    body = json.dumps({"action": action, **params}).encode()
    url = COMMAND_URL + (f"?token={token}" if token else "")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"delivered": False, "reason": f"HTTP {e.code}"}
    except Exception as e:
        return {"delivered": False, "reason": str(e)}


def main():
    ap = argparse.ArgumentParser(description="Gesture -> flight command executor")
    ap.add_argument("--live", action="store_true", help="actually send commands (default: dry-run)")
    ap.add_argument("--gesture-url", default=GESTURE_URL)
    ap.add_argument("--token", default="", help="server telemetry_token if configured")
    args = ap.parse_args()

    mode = "LIVE" if args.live else "DRY-RUN"
    log(f"gesture_control started in {mode} mode — mapping: {json.dumps(MAP, ensure_ascii=False)}")

    last = None          # last triggered gesture (rising-edge memory)
    last_fired = None    # last gesture actually sent (cooldown memory)
    last_fired_at = 0.0  # when the last command was sent
    since = 0.0          # last time we announced a held gesture
    while True:
        g = get_gesture()
        gesture = g.get("gesture")
        fresh = g.get("fresh_s")
        now = time.time()

        if gesture is None or fresh is None or fresh > STALE_S:
            last = None  # hand gone / stale: reset edge so the next gesture fires
        elif gesture != last:
            action, params = MAP.get(gesture, (None, None))
            if action:
                if gesture == last_fired and now - last_fired_at < COOLDOWN_S:
                    log(f"手势 {gesture} 冷却中 ({COOLDOWN_S}s) — 忽略抖动重触发")
                    last = gesture
                else:
                    log(f"手势 {gesture} → {action} {params or ''}")
                    if args.live:
                        r = send_command(action, params, args.token)
                        log(f"   → delivered={r.get('delivered')} reason={r.get('reason')}")
                    last_fired = gesture
                    last_fired_at = now
            else:
                log(f"手势 {gesture} — 未绑定动作")
            last = gesture
            since = now
        elif now - since > 3:
            log(f"手势 {gesture} 保持中 (不重复触发)")
            since = now

        time.sleep(POLL_S)


if __name__ == "__main__":
    main()

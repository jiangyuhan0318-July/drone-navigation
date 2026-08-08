#!/usr/bin/env python3
"""
posture_control.py — 姿态守护 → 告警/动作执行器

轮询姿态守护服务 (:8703/posture), 上升沿触发: 姿态状态变化时上报,
异常 (head_down 头部前倾 / too_close 距离过近) 持续时按节奏提醒。

安全设计 (与 gesture_control.py / fall_control.py 一致):
  - 默认只告警 (日志 + 控制台), 不动作
  - ACTION_MAP 留空: 想绑定飞行动令加一行即可 (如 head_down → ...)
  - 默认 --dry-run; --live 才真发命令
  - 异常持续每 10 s 复报一次

Usage:
  python posture_control.py             # dry-run: 只告警
  python posture_control.py --live      # 真发命令 (ACTION_MAP 配了才有)
"""
import argparse
import json
import time
import urllib.request

POSTURE_URL = "http://127.0.0.1:8703/posture"
COMMAND_URL = "http://127.0.0.1:8000/api/copilot/command"

# ── 姿态异常 → 飞行动令映射 ────────────────────────────────────────────────
# 用户需求: 检测到坐姿不端正 (头部前倾/距离过近) → 飞机起飞。
# takeoff 受飞行门控约束 (gate 未开会被 server 拒绝)。
ACTION_MAP = {
    "head_down": ("takeoff", {"height": 0.5}),
    "too_close": ("takeoff", {"height": 0.5}),
}

ABNORMAL_STATES = ("head_down", "too_close")

STALE_S = 1.0
POLL_S = 0.5
REALERT_S = 10.0   # 异常持续时复报间隔


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_posture():
    try:
        with urllib.request.urlopen(POSTURE_URL, timeout=2) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "state": None, "fresh_s": None}


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
    ap = argparse.ArgumentParser(description="Posture guardian -> alert/action executor")
    ap.add_argument("--live", action="store_true", help="actually send commands (default: dry-run)")
    ap.add_argument("--posture-url", default=POSTURE_URL)
    ap.add_argument("--token", default="", help="server telemetry_token if configured")
    args = ap.parse_args()

    mode = "LIVE" if args.live else "DRY-RUN"
    log(f"posture_control started in {mode} mode — action map: {json.dumps(ACTION_MAP, ensure_ascii=False)}")

    last = None
    last_alert = 0.0
    while True:
        p = get_posture()
        state = p.get("state")
        fresh = p.get("fresh_s")
        now = time.time()

        if state is None or fresh is None or fresh > STALE_S:
            last = None
        elif state != last:
            if state in ABNORMAL_STATES:
                log(f"⚠️ 姿态异常: {state} (持续 {p.get('duration_ms', 0)} ms, "
                    f"置信度 {p.get('confidence', 0):.2f})")
            elif state == "normal":
                log(f"✅ 坐姿恢复: normal")
            else:
                log(f"状态: {state}")
            action, params = ACTION_MAP.get(state, (None, None))
            if action:
                log(f"姿态映射 → {action} {params or ''}")
                if args.live:
                    r = send_command(action, params, args.token)
                    log(f"   → delivered={r.get('delivered')} reason={r.get('reason')}")
            last = state
            last_alert = now
        elif state in ABNORMAL_STATES and now - last_alert > REALERT_S:
            log(f"⚠️ 姿态异常持续: {state} — 复报 (请调整坐姿)")
            last_alert = now

        time.sleep(POLL_S)


if __name__ == "__main__":
    main()

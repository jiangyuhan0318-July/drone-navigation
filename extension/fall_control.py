#!/usr/bin/env python3
"""fall_control.py — 跌倒事件 → 飞行动令执行器

消费 fall_recognizer.py (:8704) 的确认摔倒事件, 上升沿触发一次起飞:

    fall_recognizer (Webcam, MediaPipe)  →  /fall (state=alert, last_event)
    fall_control (本脚本)                →  POST /api/copilot/command takeoff

与手势执行器同构的安全护栏:
  - 默认 DRY-RUN 只打日志, --live 才真发命令
  - 命令永远走 /api/copilot/command 门控链路 (server 端 gate 关闭即拒绝)
  - 起飞前查电量, < 3.5V 拒绝 (与 copilot_ctl 同规则)
  - 摔倒事件 30s 冷却: 倒地的人持续被检测到不会重复发起飞
  - STALE_S=3: 识别服务/链路断后不误发

Usage:
  python fall_control.py                      # dry-run
  python fall_control.py --live               # 真发命令 (需 gate 开 + 无人机在线)
  python fall_control.py --token TOKEN        # server 配了 telemetry_token 时
Env: COPILOT_BASE (默认 http://127.0.0.1:8000), FALL_URL (默认 :8704/fall)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("COPILOT_BASE", "http://127.0.0.1:8000").rstrip("/")
FALL_URL = os.environ.get("FALL_URL", "http://127.0.0.1:8704/fall").rstrip("/")

POLL_S = 0.5            # 轮询识别服务
STALE_S = 3.0           # 超过此时长没刷新 → 链路断
FALL_COOLDOWN_S = 30.0  # 一次确认摔倒后, 冷却期内不再发第二次起飞
BATTERY_FLOOR_V = 3.5   # 起飞最低电量 (与 copilot_ctl 一致)

TOKEN = os.environ.get("COPILOT_TOKEN", "")


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


def get_fall_state(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


def send_takeoff(height: float) -> dict:
    return _api("/api/copilot/command", method="POST",
                body={"action": "takeoff", "height": height})


def battery_ok() -> tuple[bool, str]:
    """None/未知电量 → 放行 (server 会报 no drone link); < 3.5V 拒绝。"""
    status = _api("/api/copilot/status")
    if "error" in status:
        return True, f"status 不可达 ({status['error']}) — 由 server 兜底"
    voltage = (status.get("telemetry") or {}).get("battery") or {}
    v = voltage.get("voltage")
    if v is None:
        return True, "无电量数据 — 由 server 兜底"
    if v < BATTERY_FLOOR_V:
        return False, f"电量过低 ({v:.2f}V < {BATTERY_FLOOR_V}V) — 拒绝起飞"
    return True, f"电量 {v:.2f}V OK"


def main() -> int:
    ap = argparse.ArgumentParser(prog="fall_control.py", description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="真发命令 (默认 dry-run 只打日志)")
    ap.add_argument("--token", default="", help="server telemetry_token (如有)")
    ap.add_argument("--height", type=float, default=0.5,
                    help="摔倒响应起飞高度 (0.1-1.5m, 默认 0.5)")
    ap.add_argument("--fall-url", default=FALL_URL,
                    help="跌倒服务 URL (默认 :8704/fall; 守护中心为 :8705/fall)")
    args = ap.parse_args()

    if args.token:
        os.environ["COPILOT_TOKEN"] = args.token

    log(f"fall_control 启动 mode={'LIVE' if args.live else 'DRY-RUN'} "
        f"recognizer={args.fall_url} base={BASE}")
    log(f"护栏: 电量 <{BATTERY_FLOOR_V}V 拒绝, 事件冷却 {FALL_COOLDOWN_S}s, "
        f"STALE_S={STALE_S}")

    last_event_ts = None   # 已消费的 last_event.ts (上升沿记忆)
    last_fired_at = 0.0    # 上次真发命令时间 (冷却记忆)
    stale_logged = False

    while True:
        st = get_fall_state(args.fall_url)
        now = time.time()

        if "error" in st:
            if not stale_logged:
                log(f"识别服务不可达: {st['error']} — 等待中 (不发送任何命令)")
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

        if now - last_fired_at < FALL_COOLDOWN_S:
            log(f"摔倒事件 (axis={ev.get('axis_angle_deg')}° "
                f"conf={ev.get('confidence')}) — 冷却期内忽略 (还剩 "
                f"{FALL_COOLDOWN_S - (now - last_fired_at):.0f}s)")
            continue

        log(f"!! 摔倒确认 → 触发起飞 {args.height:.1f}m "
            f"({ev.get('axis_angle_deg')}° / ratio={ev.get('bbox_ratio')})")

        ok, reason = battery_ok()
        if not ok:
            log(f"  ✋ {reason} — 不起飞, 只上报 (webhook 仍会发)")
            continue  # 冷却不更新: 电量回升后下一次摔倒仍可触发

        if not args.live:
            log(f"  [DRY-RUN] 本应发送: takeoff height={args.height:.1f} "
                f"({reason})")
            last_fired_at = now  # dry-run 也吃冷却, 防止刷屏
            continue

        r = send_takeoff(args.height)
        last_fired_at = now
        log(f"  → delivered={r.get('delivered')} "
            f"reason={r.get('reason')} "
            f"telemetry_z={((r.get('telemetry') or {}).get('position') or {}).get('z')}")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""action_recognizer.py — 身体动作识别服务 (双手举起 / 双臂交叉 / T字展开)

识别器(桌面版客服项目 usePoseControl.js 的 Python 移植, 阈值原样):
  - hands_up     双手举起   — 进入"准备确认"状态
  - arms_crossed 双臂交叉   — 取消待确认动作
  - t_pose       T 字展开   — 切换姿态控制模式

事件规则与浏览器版一致:
  - 姿态持握 ≥1000ms 且置信度 ≥0.65 才触发一次事件
  - 触发后 2500ms 冷却, 防同一姿态重复刷事件
  - 人不在画面 / 姿态丢失 → 计时归零, 不残留

HTTP (默认 :8706, ACTION_PORT):
  GET /action   — 当前姿态 + last_event (执行器轮询这个)
  GET /health   — 存活检查
  GET /video    — --show 时提供 MJPEG 流 (浏览器 <img src=.../video>)

与手势/坐姿/跌倒服务互斥: 摄像头同一时刻只能被一个进程占用。
执行器配对: action_control.py (POST /api/pose/event → 服务端姿态状态机)。

Usage:
  python action_recognizer.py                  # 本机摄像头
  python action_recognizer.py --show           # 开 /video 实时画面
  python action_recognizer.py --source rtsp://127.0.0.1:8554/crazyflie-drone
Env: ACTION_SOURCE (默认 0), ACTION_PORT (默认 8706)
"""
import argparse
import json
import math
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

DEFAULT_INPUT = os.environ.get("ACTION_SOURCE", "0")
DEFAULT_PORT = int(os.environ.get("ACTION_PORT", "8706"))

POSE_MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"

HOLD_THRESHOLD_MS = 1000      # 姿态持握多久触发 (浏览器版同款)
MIN_CONFIDENCE = 0.65         # 最低置信度
TRIGGER_COOLDOWN_MS = 2500    # 触发后冷却, 防刷屏

POSE_LABELS = {"hands_up": "双手举起", "arms_crossed": "双臂交叉",
               "t_pose": "T字展开"}
STATE_COLORS = {"hands_up": (245, 158, 11), "arms_crossed": (11, 158, 245),
                "t_pose": (156, 39, 176), "none": (94, 197, 34)}
POSE_CONNECTIONS = [  # MediaPipe 33 点骨架 (姿势面板同款)
    [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21],
    [12, 14], [14, 16], [16, 18], [16, 20], [16, 22],
    [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [27, 29],
    [24, 26], [26, 28], [28, 30],
]

QUEUE_MAXSIZE = 2
DISPLAY_Q = queue.Queue(maxsize=QUEUE_MAXSIZE)


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.pose = "none"        # hands_up / arms_crossed / t_pose / none
        self.person = False
        self.confidence = 0.0
        self.held_ms = 0
        self.last_event = None
        self.ts = 0.0
        self.frames = 0
        self.fps = 0.0


STATE = State()


def classify_pose(lmks):
    """usePoseControl.js classifyPose 的 Python 移植 (阈值原样)。

    Returns (pose, confidence): pose ∈ hands_up|arms_crossed|t_pose|none
    """
    if lmks is None or len(lmks) < 25:
        return "none", 0.0

    def dist(a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    ls, rs = lmks[11], lmks[12]   # 肩
    le, re = lmks[13], lmks[14]   # 肘
    lw, rw = lmks[15], lmks[16]   # 腕
    lh, rh = lmks[23], lmks[24]   # 髋
    required = [ls, rs, le, re, lw, rw, lh, rh]
    if any(p is None for p in required):
        return "none", 0.0

    visibility = sum(float(p.visibility or 0) for p in required) / len(required)
    shoulder_mid_x = (ls.x + rs.x) / 2
    shoulder_width = max(dist(ls, rs), 0.1)
    wrist_gap = dist(lw, rw)

    # 双手举起: 腕在肩上, 肘在髋上
    if (lw.y < ls.y and rw.y < rs.y and le.y < lh.y and re.y < rh.y):
        return "hands_up", min(0.99, visibility)

    # 双臂交叉: 双腕贴近中线(±0.35肩宽), 在肩下, 腕距 < 0.5肩宽
    if (abs(lw.x - shoulder_mid_x) < shoulder_width * 0.35
            and abs(rw.x - shoulder_mid_x) < shoulder_width * 0.35
            and lw.y > ls.y - 0.05 and rw.y > rs.y - 0.05
            and wrist_gap < shoulder_width * 0.5):
        return "arms_crossed", min(0.95, visibility)

    # T 字展开: 双腕与肩同高(±0.12), 向外张开(±0.45肩宽)
    if (abs(lw.y - ls.y) < 0.12 and abs(rw.y - rs.y) < 0.12
            and lw.x < ls.x - shoulder_width * 0.45
            and rw.x > rs.x + shoulder_width * 0.45):
        return "t_pose", min(0.95, visibility)

    return "none", visibility


def read_frames_loop(source, frame_q, stop):
    # 摄像头索引必须是 int — 字符串 "0" 在 macOS AVFoundation 后端打不开
    # (会按文件路径解析)。RTSP/文件路径则保持字符串。
    cap_source = int(source) if str(source).isdigit() else source
    # macOS 摄像头 HAL 刚释放时立即 open 偶发失败 — 启动重试 10 次,
    # 运行中断流也自动重开, 不再需要手动重启。
    cap = cv2.VideoCapture()
    for attempt in range(1, 11):
        if stop.is_set():
            return
        cap.open(cap_source)
        if cap.isOpened():
            break
        log("INIT", f"无法打开视频源: {source} (尝试 {attempt}/10, 1s 后重试)")
        time.sleep(1.0)
    if not cap.isOpened():
        log("INIT", "放弃: 视频源始终无法打开, 检查是否有其他进程占用摄像头")
        return
    log("INIT", f"视频源已打开: {source}")
    failed_reads = 0
    while not stop.is_set():
        ok, img = cap.read()
        if not ok:
            failed_reads += 1
            if failed_reads >= 5:
                log("INIT", "视频流中断, 尝试重新打开视频源")
                cap.release()
                for attempt in range(1, 6):
                    if stop.is_set():
                        return
                    cap.open(cap_source)
                    if cap.isOpened():
                        failed_reads = 0
                        log("INIT", "视频源重开成功")
                        break
                    time.sleep(1.0)
            time.sleep(0.1)
            continue
        failed_reads = 0
        if frame_q.full():
            try:
                frame_q.get_nowait()
            except queue.Empty:
                pass
        frame_q.put_nowait(img)
    cap.release()


def draw_frame(img, lmks, pose, conf, person):
    h, w = img.shape[:2]
    color = STATE_COLORS.get(pose, (94, 197, 34))
    if lmks is not None:
        pts = [(int(p.x * w), int(p.y * h)) for p in lmks]
        for a, b in POSE_CONNECTIONS:
            cv2.line(img, pts[a], pts[b], color, 2)
        for p in pts:
            cv2.circle(img, p, 3, color, -1)
    label = f"动作: {POSE_LABELS.get(pose, pose)} conf={conf:.2f}"
    if not person:
        label = "无人"
    cv2.putText(img, label, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 0, 0), 4)
    cv2.putText(img, label, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                color, 2)
    return img


def detect_loop(frame_q, stop, show):
    base = python.BaseOptions(model_asset_path=str(POSE_MODEL))
    pose_opts = vision.PoseLandmarkerOptions(
        base_options=base, running_mode=vision.RunningMode.VIDEO,
        num_poses=1, min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
    pose_lm = vision.PoseLandmarker.create_from_options(pose_opts)

    ms = 0
    stable_pose = None      # 当前持握的姿态 (浏览器版逻辑原样)
    stable_since = 0
    held_ms = 0
    last_trigger_at = 0
    last_log = 0
    last_frames = 0

    while not stop.is_set():
        try:
            img = frame_q.get(timeout=1)
        except queue.Empty:
            continue
        ms += 33
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            res = pose_lm.detect_for_video(mp_image, ms)
        except Exception as e:
            log("AI", f"Detection error: {e}")
            continue

        lmks = res.pose_landmarks[0] if res.pose_landmarks else None
        person = lmks is not None
        pose, conf = classify_pose(lmks)

        # 持握计时 (与浏览器版一致: 姿态丢失即清零)
        if not pose or conf < MIN_CONFIDENCE:
            stable_pose = None
            stable_since = 0
            held_ms = 0
        elif pose == stable_pose:
            held_ms = ms - stable_since
        else:
            stable_pose = pose
            stable_since = ms
            held_ms = 0

        event = None
        if (pose and pose != "none" and conf >= MIN_CONFIDENCE and stable_pose == pose
                and held_ms >= HOLD_THRESHOLD_MS
                and ms - last_trigger_at >= TRIGGER_COOLDOWN_MS):
            last_trigger_at = ms
            event = {
                "pose": pose,
                "confidence": round(conf, 3),
                "held_ms": held_ms,
                "ts": time.time(),
            }

        if show:
            img = draw_frame(img, lmks, pose, conf, person)
            if DISPLAY_Q.full():
                try:
                    DISPLAY_Q.get_nowait()
                except queue.Empty:
                    pass
            DISPLAY_Q.put_nowait(img)

        now = time.time()
        with STATE.lock:
            STATE.frames += 1
            STATE.person = person
            STATE.pose = pose if conf >= MIN_CONFIDENCE else "none"
            STATE.confidence = round(conf, 3)
            STATE.held_ms = held_ms
            STATE.ts = now
            if event:
                STATE.last_event = event
                log("EVENT", f"!! {POSE_LABELS.get(pose, pose)} 确认: "
                             f"conf={event['confidence']:.2f} "
                             f"held={event['held_ms']}ms")

            now_m = time.monotonic()
            if now_m - last_log >= 5:
                STATE.fps = (STATE.frames - last_frames) / (now_m - last_log)
                last_frames = STATE.frames
                last_log = now_m
                log("AI", f"{STATE.frames} frames, {STATE.fps:.1f} fps, "
                          f"pose={STATE.pose} person={person}")

    pose_lm.close()


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        with STATE.lock:
            snap = {
                "state": STATE.pose,
                "person": STATE.person,
                "confidence": STATE.confidence,
                "held_ms": STATE.held_ms,
                "last_event": STATE.last_event,
                "ts": STATE.ts,
                "frames": STATE.frames,
                "fps": round(STATE.fps, 2),
            }
        path = self.path.rstrip("/")
        if path == "/action":
            self._json(200, snap)
        elif path == "/health":
            self._json(200, {"ok": True})
        elif path == "/video":
            self._stream_video()
        else:
            self._json(404, {"error": "not found"})

    def _stream_video(self):
        """--show 模式: MJPEG 流 (浏览器 <img src=.../video> 或直接打开看)。"""
        self.send_response(200)
        self.send_header("Content-Type",
                         "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        while True:
            try:
                img = DISPLAY_Q.get(timeout=1)
            except queue.Empty:
                continue
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                                 + buf.tobytes() + b"\r\n")
                self.wfile.flush()
            except Exception:
                return  # 浏览器断开

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(prog="action_recognizer.py", description=__doc__)
    ap.add_argument("--source", default=DEFAULT_INPUT,
                    help="视频源: 0=本机摄像头 / rtsp://... / 文件")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"HTTP 端口 (默认 {DEFAULT_PORT})")
    ap.add_argument("--show", action="store_true",
                    help="开 /video MJPEG 实时画面")
    args = ap.parse_args()

    if not POSE_MODEL.exists():
        log("INIT", f"模型缺失: {POSE_MODEL} — 检查 extension/models/")
        return 1

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
    threading.Thread(target=read_frames_loop, args=(args.source, frame_q, stop),
                     daemon=True).start()
    threading.Thread(target=detect_loop, args=(frame_q, stop, args.show),
                     daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log("HTTP", f"action recognizer on http://127.0.0.1:{args.port}/ "
                f"(/action /health" + (" /video" if args.show else "") + ")")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()

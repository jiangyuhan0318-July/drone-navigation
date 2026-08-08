#!/usr/bin/env python3
"""
fall_recognizer.py — 跌倒检测服务 (本机摄像头, MediaPipe Pose, 毫秒级)

检测逻辑完整移植自队友浏览器实现 (FallDetectionOverlay.vue, 阈值原样不改):
  - axisAngleDeg: 肩中点 vs 髋中点与竖直夹角 (倒地判定核心)
  - bboxRatio:    全身包围盒宽高比 (横躺 → 比值 > 0.95)
  - bodyDrop:     髋部相对基准线的下坠量 (跌倒瞬间骤降)
  - 状态机: standing -> falling -> lying -> alert (倒地确认 900ms 触发事件)
  - 确认一次只发一个 fall 事件; 恢复站立 (upright 600ms) 后才允许下一次

与手势/姿态服务同构: 帧线程 + 检测线程 + HTTP, 供执行器 / OpenClaw skill 消费。

Usage:
  python fall_recognizer.py                      # 默认本机摄像头
  python fall_recognizer.py --source rtsp://127.0.0.1:8554/crazyflie-drone
  python fall_recognizer.py --port 8704
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
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ── Configuration ──────────────────────────────────────────────────────────
DEFAULT_INPUT = os.environ.get("VIDEO_FALL_INPUT", "0")
DEFAULT_PORT = int(os.environ.get("FALL_PORT", "8704"))

POSE_MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
QUEUE_MAXSIZE = 2

# 队友阈值 (FallDetectionOverlay.vue 原值, 不改)
MIN_PERSON_HEIGHT = 0.12        # 人太小不判 (画面里太远/只有半个身子)
LYING_CONFIRM_MS = 900          # 倒地状态持续多久才确认报警
RECOVERY_MS = 600               # 恢复站立多久回到 standing
MAX_SAMPLES = 120               # 髋部历史样本 (算垂直速度用)

# 骨架连线 (POSE_CONNECTIONS, 浏览器版同款)
POSE_CONNECTIONS = [
    [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
    [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
    [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [27, 29], [29, 31],
    [24, 26], [26, 28], [28, 30], [30, 32],
]

# 状态 → BGR 颜色 (浏览器版: 红=倒地/报警, 橙=跌倒中, 绿=正常)
STATE_COLORS = {"alert": (68, 68, 239), "lying": (68, 68, 239),
                "falling": (11, 158, 245), "standing": (94, 197, 34)}


def draw_frame(img, landmarks, state, confidence, person):
    """--show 模式: 画面 + 骨架 + 状态角标 (BGR 就地绘制, 返回供 /video 推送)。"""
    h, w = img.shape[:2]
    color = STATE_COLORS.get(state, (94, 197, 34))
    if landmarks is not None:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in landmarks]
        for a, b in POSE_CONNECTIONS:
            cv2.line(img, pts[a], pts[b], color, 2)
        for p in pts:
            cv2.circle(img, p, 3, color, -1)
    cv2.putText(img, f"FallGuard: {state} conf={confidence:.2f} person={person}",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return img


# --show 模式下检测线程画好的帧, 供 /video MJPEG 流消费 (丢帧不阻塞检测)
DISPLAY_Q = queue.Queue(maxsize=3)


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "standing"     # standing / falling / lying / alert
        self.confidence = 0.0
        self.features = {}
        self.person = False
        self.ts = 0.0
        self.frames = 0
        self.fps = 0.0
        self.last_event = None      # 最近一次确认摔倒 {ts, confidence, features}


STATE = State()


def read_frames_loop(source_url, frame_q, stop):
    if isinstance(source_url, str) and source_url.isdigit():
        source_url = int(source_url)
    while not stop.is_set():
        cap = cv2.VideoCapture(source_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            log("IN", f"Cannot open {source_url} — retrying in 3 s...")
            cap.release()
            stop.wait(3)
            continue
        log("IN", f"Connected to {source_url}")
        while not stop.is_set():
            ret, img = cap.read()
            if not ret:
                log("IN", "Source stream ended — reconnecting...")
                break
            if frame_q.full():
                try:
                    frame_q.get_nowait()
                except queue.Empty:
                    pass
            frame_q.put_nowait(img)
        cap.release()
        stop.wait(3)


def _avg(a, b):
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def compute_features(pose_landmarks):
    """移植队友 computeFeatures: 33 点 → 轴角/包围盒/身高/可见度。"""
    p = lambda i: pose_landmarks[i]
    shoulder = _avg(p(11), p(12))
    hip = _avg(p(23), p(24))
    ankle = _avg(p(27), p(28))

    xs = [pt.x for pt in pose_landmarks]
    ys = [pt.y for pt in pose_landmarks]
    bboxW = max(max(xs) - min(xs), 0.001)
    bboxH = max(max(ys) - min(ys), 0.001)
    vis = min((pt.visibility if pt.visibility is not None else 1.0)
              for pt in pose_landmarks)

    axisDx = shoulder[0] - hip[0]
    axisDy = shoulder[1] - hip[1]
    return {
        "hip": hip,
        "bboxW": bboxW,
        "bboxH": bboxH,
        "bboxRatio": bboxW / bboxH,
        "axisAngleDeg": math.degrees(math.atan2(abs(axisDx), abs(axisDy))),
        "visibility": vis,
        "personHeight": max(bboxH,
                            _dist(*shoulder, *hip) + _dist(*hip, *ankle)),
    }


class FallStateMachine:
    """浏览器状态机逐行移植: standing/falling/lying/alert + 恢复 + 防重报。"""

    def __init__(self):
        self.state = "standing"
        self.samples = []           # (t_ms, hip_y)
        self.baseline_hip_y = None
        self.fall_since = 0
        self.lying_since = 0
        self.upright_since = 0
        self.alert_sent = False
        self.event = None           # 本次摔倒的事件 (发出后置 None)

    def reset(self):
        self.state = "standing"
        self.samples = []
        self.baseline_hip_y = None
        self.fall_since = 0
        self.lying_since = 0
        self.upright_since = 0
        self.alert_sent = False
        self.event = None

    def step(self, feats, now_ms):
        """feats = compute_features() 输出; 返回本帧新事件 dict 或 None。"""
        if self.baseline_hip_y is None:
            self.baseline_hip_y = feats["hip"][1]

        self.samples.append((now_ms, feats["hip"][1]))
        if len(self.samples) > MAX_SAMPLES:
            self.samples.pop(0)

        bodyDrop = feats["hip"][1] - self.baseline_hip_y
        bodyDropNorm = bodyDrop / max(feats["personHeight"], 0.04)

        recent = [s for s in self.samples if now_ms - s[0] <= 450]
        vel = 0.0
        if len(recent) >= 2:
            dt = (recent[-1][0] - recent[0][0]) / 1000
            if dt > 0.01:
                vel = ((recent[-1][1] - recent[0][1])
                       / max(feats["personHeight"], 0.04) / dt)

        upright = (feats["axisAngleDeg"] < 32 and feats["bboxRatio"] < 0.92)

        # 基准线慢速跟随 (站立时的微小漂移), 与队友完全一致
        if self.state != "alert":
            drift = abs(feats["hip"][1] - self.baseline_hip_y)
            if drift < 0.06 * feats["personHeight"]:
                self.baseline_hip_y += (feats["hip"][1] - self.baseline_hip_y) * 0.08
            elif drift < 0.2 * feats["personHeight"]:
                self.baseline_hip_y += (feats["hip"][1] - self.baseline_hip_y) * 0.015

        lyingScore = (
            (1 if feats["bboxRatio"] > 0.95 else 0) +
            (1 if feats["axisAngleDeg"] > 45 else 0) +
            (1 if bodyDropNorm > 0.25 else 0))

        if self.state == "alert":
            # 恢复站立 → 重置, 允许下一次摔倒再次报警。
            # (浏览器原版在 alert 分支从不更新 upright_since, 报警后永久卡死
            # 在 alert — 对"摔倒→起飞"等于一辈子只能触发一次, 这里修正。)
            if upright:
                self.upright_since = self.upright_since or now_ms
                if now_ms - self.upright_since > RECOVERY_MS:
                    self.reset()
            else:
                self.upright_since = 0
        else:
            if upright:
                self.upright_since = self.upright_since or now_ms
                if (self.state in ("falling", "lying")
                        and now_ms - self.upright_since > RECOVERY_MS):
                    self.reset()
            else:
                self.upright_since = 0

            suddenFall = bodyDropNorm > 0.35 or vel > 1.2
            directLying = (feats["bboxRatio"] > 1.15
                           and feats["axisAngleDeg"] > 55
                           and feats["personHeight"] >= MIN_PERSON_HEIGHT)

            if self.state == "standing" and suddenFall:
                self.state = "falling"
                self.fall_since = now_ms
            elif self.state == "standing" and directLying:
                self.state = "lying"
                self.fall_since = now_ms
                self.lying_since = now_ms
            elif self.state == "falling":
                if lyingScore >= 2 and now_ms - self.fall_since >= 350:
                    self.state = "lying"
                    self.lying_since = now_ms
                elif now_ms - self.fall_since > 1800 and bodyDropNorm < 0.08:
                    self.reset()  # 假摔: 倒地但很快恢复正常
            elif self.state == "lying":
                if (lyingScore >= 2
                        and now_ms - self.lying_since >= LYING_CONFIRM_MS):
                    self.state = "alert"
                    if not self.alert_sent:
                        self.alert_sent = True
                        self.event = {
                            "type": "fall",
                            "confidence": round(feats["visibility"], 3),
                            "axis_angle_deg": round(feats["axisAngleDeg"], 1),
                            "bbox_ratio": round(feats["bboxRatio"], 3),
                            "ts": time.time(),
                        }
                elif lyingScore < 1 and now_ms - self.lying_since > 600:
                    self.reset()

        return self.event


def detect_loop(frame_q, stop, show=False):
    base = python.BaseOptions(model_asset_path=str(POSE_MODEL))
    pose_opts = vision.PoseLandmarkerOptions(
        base_options=base, running_mode=vision.RunningMode.VIDEO,
        num_poses=1, min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
    pose_lm = vision.PoseLandmarker.create_from_options(pose_opts)

    fsm = FallStateMachine()
    last_log = 0
    last_frames = 0
    ms = 0
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

        person = bool(res.pose_landmarks)
        feats = None
        event = None
        conf = 0.0
        if person:
            feats = compute_features(res.pose_landmarks[0])
            event = fsm.step(feats, ms)
            conf = feats["visibility"]
        if show:
            lmks = res.pose_landmarks[0] if res.pose_landmarks else None
            img = draw_frame(img, lmks, fsm.state, conf, person)
            if DISPLAY_Q.full():
                try:
                    DISPLAY_Q.get_nowait()
                except queue.Empty:
                    pass
            DISPLAY_Q.put_nowait(img)
        else:
            fsm.samples = []
            fsm.upright_since = 0  # 人不在画面 → 不清事件, 只停计时

        now = time.time()
        with STATE.lock:
            STATE.frames += 1
            STATE.person = person
            STATE.state = fsm.state
            STATE.confidence = round(conf, 3)
            STATE.features = (None if feats is None else {
                "axis_angle_deg": round(feats["axisAngleDeg"], 1),
                "bbox_ratio": round(feats["bboxRatio"], 3),
                "person_height": round(feats["personHeight"], 3),
                "visibility": round(feats["visibility"], 3),
            })
            STATE.ts = now
            if event:
                STATE.last_event = event
                fsm.event = None
                log("EVENT", f"!! 摔倒确认: axis={event['axis_angle_deg']}° "
                             f"ratio={event['bbox_ratio']} "
                             f"conf={event['confidence']:.2f}")

            now_m = time.monotonic()
            if now_m - last_log >= 5:
                STATE.fps = (STATE.frames - last_frames) / (now_m - last_log)
                last_frames = STATE.frames
                last_log = now_m
                log("AI", f"{STATE.frames} frames, {STATE.fps:.1f} fps, "
                          f"state={fsm.state} person={person}")

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
                "state": STATE.state,
                "person": STATE.person,
                "confidence": STATE.confidence,
                "features": STATE.features,
                "last_event": STATE.last_event,
                "ts": STATE.ts,
                "frames": STATE.frames,
                "fps": round(STATE.fps, 2),
            }
        if self.path.rstrip("/") == "/fall":
            self._json(200, snap)
        elif self.path.rstrip("/") == "/health":
            self._json(200, {"ok": True})
        elif self.path.rstrip("/") == "/video":
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
            ok, buf = cv2.imencode(".jpg", img,
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                continue
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                                 + buf.tobytes() + b"\r\n")
                self.wfile.flush()
            except Exception:
                return  # 浏览器断开

    def log_message(self, *a):
        pass  # 不刷屏


def main():
    ap = argparse.ArgumentParser(prog="fall_recognizer.py", description=__doc__)
    ap.add_argument("--source", default=DEFAULT_INPUT,
                    help="视频源: 0=本机摄像头 / rtsp://... / 文件")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"HTTP 端口 (默认 {DEFAULT_PORT})")
    ap.add_argument("--show", action="store_true",
                    help="开启 /video MJPEG 流: 浏览器打开 "
                         "http://127.0.0.1:<port>/video 看实时画面+骨架+状态")
    args = ap.parse_args()

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
    threading.Thread(target=read_frames_loop, args=(args.source, frame_q, stop),
                     daemon=True).start()
    threading.Thread(target=detect_loop, args=(frame_q, stop, args.show),
                     daemon=True).start()

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    log("HTTP", f"fall service on http://127.0.0.1:{args.port}/fall")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
posture_guardian.py — 姿态守护服务 (学习姿势提醒, 本地免费毫秒级)

检测逻辑完整移植自队友浏览器实现 (PostureGuardianView.vue):
  - head_lean_deg: 双耳中点 vs 双肩中点连线与竖直夹角 (≥11° = 头部前倾)
  - face_area: FaceLandmarker 468 点包围盒面积 (≥0.075 = 距离屏幕过近)
  - 优先级: 无人 → head_down → too_close → normal
  - 异常持续 ≥ 700ms 触发事件 (10s 冷却), 与队友节奏一致

视频源默认本机摄像头 (电脑摄像头, 学习场景), 与手势服务同构:
帧线程 + 检测线程 + HTTP, 供执行器 / OpenClaw skill 消费。

Usage:
  python posture_guardian.py                      # 默认本机摄像头
  python posture_guardian.py --source rtsp://127.0.0.1:8554/crazyflie-drone
  python posture_guardian.py --port 8703
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
# 队友演示/学习场景: 默认电脑摄像头; --source 可换飞机摄像头 RTSP。
DEFAULT_INPUT = os.environ.get("VIDEO_POSTURE_INPUT", "0")
DEFAULT_PORT = int(os.environ.get("POSTURE_PORT", "8703"))

# 模型: 与队友包同款 (pose_landmarker_lite + face_landmarker)
POSE_MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"
FACE_MODEL = Path(__file__).parent / "models" / "face_landmarker.task"

QUEUE_MAXSIZE = 2

# 队友阈值 (PostureGuardianView.vue 原值, 灵敏度已调低: 2026-08-07)
# 原值 11°/700ms 太灵敏 (正常打字/侧头就报), 放宽到 16°/2s。
# env 可覆盖: POSTURE_LEAN_DEG (默认 16.0), POSTURE_HOLD_MS (默认 2000)
HEAD_LEAN_THRESHOLD_DEG = float(os.environ.get("POSTURE_LEAN_DEG", "16.0"))
TOO_CLOSE_FACE_AREA = 0.075        # 距离过近阈值
REMINDER_AFTER_MS = int(os.environ.get("POSTURE_HOLD_MS", "2000"))
REMINDER_COOLDOWN_MS = 10000       # 两次事件最小间隔


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = None           # normal / head_down / too_close / unknown
        self.confidence = 0.0
        self.features = {}
        self.duration_ms = 0        # 当前状态持续时长
        self.ts = 0.0
        self.frames = 0
        self.fps = 0.0
        self.last_event = None      # 最近一次异常事件 {state, ts} or None


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


def _mid(a, b):
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def head_lean_deg(pose_landmarks):
    """移植队友 headLeanDeg: 耳中点 vs 肩中点, atan2(|dx|, dy)。"""
    ear = _mid(pose_landmarks[7], pose_landmarks[8])
    shoulder = _mid(pose_landmarks[11], pose_landmarks[12])
    dx = ear[0] - shoulder[0]
    dy = max(shoulder[1] - ear[1], 0.001)
    return abs(math.degrees(math.atan2(dx, dy)))


def face_area(face_landmarks):
    """移植队友 faceArea: 468 点包围盒面积。"""
    xs = [p.x for p in face_landmarks]
    ys = [p.y for p in face_landmarks]
    return max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))


def classify(pose_landmarks, face_landmarks):
    """移植队友 classify, 返回 (state, confidence, features)。"""
    features = {}
    if pose_landmarks is not None and len(pose_landmarks) >= 13:
        features["head_lean_deg"] = round(head_lean_deg(pose_landmarks), 2)
        features["shoulder_width"] = round(
            math.hypot(pose_landmarks[11].x - pose_landmarks[12].x,
                       pose_landmarks[11].y - pose_landmarks[12].y), 4)
    if face_landmarks is not None:
        features["face_area"] = round(face_area(face_landmarks), 5)

    if pose_landmarks is None and face_landmarks is None:
        return "unknown", 0.0, features
    lean = features.get("head_lean_deg", 0.0)
    if lean >= HEAD_LEAN_THRESHOLD_DEG:
        return "head_down", min(1.0, 0.65 + lean / 100.0), features
    area = features.get("face_area", 0.0)
    if area >= TOO_CLOSE_FACE_AREA:
        return "too_close", min(1.0, 0.65 + area), features
    return "normal", 0.8, features


def detect_loop(frame_q, stop):
    base = python.BaseOptions(model_asset_path=str(POSE_MODEL))
    pose_opts = vision.PoseLandmarkerOptions(
        base_options=base, running_mode=vision.RunningMode.VIDEO,
        num_poses=1, min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
    face_base = python.BaseOptions(model_asset_path=str(FACE_MODEL))
    face_opts = vision.FaceLandmarkerOptions(
        base_options=face_base, running_mode=vision.RunningMode.VIDEO,
        num_faces=1, min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5, min_tracking_confidence=0.5)
    pose_lm = vision.PoseLandmarker.create_from_options(pose_opts)
    face_lm = vision.FaceLandmarker.create_from_options(face_opts)

    last_log = 0
    last_frames = 0
    ms = 0
    prev_state = None
    abnormal_since = 0
    last_event_at = 0
    while not stop.is_set():
        try:
            img = frame_q.get(timeout=1)
        except queue.Empty:
            continue
        ms += 33
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        try:
            pose_res = pose_lm.detect_for_video(mp_image, ms)
            face_res = face_lm.detect_for_video(mp_image, ms)
        except Exception as e:
            log("AI", f"Detection error: {e}")
            continue

        pose_lmks = pose_res.pose_landmarks[0] if pose_res.pose_landmarks else None
        face_lmks = face_res.face_landmarks[0] if face_res.face_landmarks else None
        state, conf, feats = classify(pose_lmks, face_lmks)

        now_ms = ms
        if state != prev_state:
            prev_state = state
            abnormal_since = 0 if state in ("normal", "unknown") else now_ms
        duration = (now_ms - abnormal_since) if abnormal_since else 0
        remind = bool(
            abnormal_since
            and duration >= REMINDER_AFTER_MS
            and now_ms - last_event_at >= REMINDER_COOLDOWN_MS)

        with STATE.lock:
            STATE.frames += 1
            STATE.state = state
            STATE.confidence = conf
            STATE.features = feats
            STATE.duration_ms = duration
            STATE.ts = time.time()
            if remind:
                STATE.last_event = {"state": state, "ts": time.time()}
                last_event_at = now_ms
                log("EVENT", f"!! 姿态异常: {state} (持续 {duration} ms)")

            now = time.monotonic()
            if now - last_log >= 5:
                STATE.fps = (STATE.frames - last_frames) / (now - last_log)
                last_frames = STATE.frames
                last_log = now
                log("AI", f"{STATE.frames} frames, {STATE.fps:.1f} fps, "
                          f"state={state} ({conf:.2f}) dur={duration}ms "
                          f"feats={feats}")

    pose_lm.close()
    face_lm.close()


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
            st = STATE.state
            conf = STATE.confidence
            feats = STATE.features
            dur = STATE.duration_ms
            ts = STATE.ts
            frames = STATE.frames
            ev = STATE.last_event
        if self.path.rstrip("/") == "/posture":
            self._json(200, {
                "state": st,
                "confidence": round(conf, 3),
                "features": feats,
                "duration_ms": dur,
                "event": ev,
                "ts": round(ts, 3),
                "fresh_s": round(time.time() - ts, 2) if ts else None,
                "frames": frames,
            })
        elif self.path.rstrip("/") == "/health":
            self._json(200, {"status": "ok", "state": st, "frames": frames})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Posture guardian service (MediaPipe -> HTTP)")
    ap.add_argument("--source", "--input", dest="input", default=DEFAULT_INPUT,
                    help=f"Source URL (default: {DEFAULT_INPUT})")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"HTTP port (default: {DEFAULT_PORT})")
    args = ap.parse_args()

    log("INIT", f"Source: {args.input} | HTTP :{args.port}")

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
    threading.Thread(target=read_frames_loop, args=(args.input, frame_q, stop), daemon=True).start()
    threading.Thread(target=detect_loop, args=(frame_q, stop), daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log("HTTP", f"Posture API on http://127.0.0.1:{args.port}/posture")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("INIT", "Interrupted.")
    finally:
        stop.set()


if __name__ == "__main__":
    main()

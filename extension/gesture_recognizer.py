#!/usr/bin/env python3
"""
gesture_recognizer.py — 手势识别服务 (本地, 免费, 毫秒级)

拉取无人机/摄像头视频流，用 MediaPipe GestureRecognizer 做实时手势识别，
暴露一个轻量 HTTP 接口，供两条链路消费：

  1. 专项快速调用（chatbot / 直接映射）：curl http://127.0.0.1:8700/gesture
     —— 毫秒级返回当前手势，不经 LLM，适合手势指挥/紧急手势。
  2. OpenClaw agent 查询（模糊任务）：通过 skill 里的脚本同样调这个接口，
     agent 拿到的就是同一个确定性手势。

输入（与 video_ai_processor.py 同源）：
  --input rtsp://127.0.0.1:8554/crazyflie-drone   # MediaMTX RTSP（低延迟）
  --input http://192.168.0.106/stream             # AI-Deck MJPEG

输出：
  HTTP GET /gesture  → {"gesture": "thumb_up", "confidence": 0.93,
                         "ts": <epoch>, "fps": N}
  HTTP GET /health   → {"status": "ok", "frames": N, "gesture": ...}

标准手势（MediaPipe 内置）：Closed_Fist, Open_Palm, Pointing_Up,
Thumb_Down, Thumb_Up, Victory, ILoveYou。
附加自定义手势：OK（拇指+食指指尖相触）——演示"确认/批准"用。

Usage:
  python gesture_recognizer.py
  python gesture_recognizer.py --input http://192.168.0.106/stream
  python gesture_recognizer.py --port 8700
"""
import argparse
import json
import os
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlretrieve

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

# ── Configuration ──────────────────────────────────────────────────────────
# Default source: the local webcam (0) — gesture recognition watches the
# person in front of the camera, not the drone's AI-Deck view. Pass --input
# to point at a remote camera / RTSP stream instead.
DEFAULT_INPUT = os.environ.get("VIDEO_GESTURE_INPUT", "0")
DEFAULT_PORT = int(os.environ.get("GESTURE_PORT", "8700"))

# Model: first run downloads it (float16, ~5 MB) to ./models/
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
             "gesture_recognizer/float16/1/gesture_recognizer.task")
MODEL_PATH = Path(__file__).parent / "models" / "gesture_recognizer.task"

QUEUE_MAXSIZE = 2       # drop frames rather than build latency
VOTE_WINDOW = 5         # majority-vote over last N results (stabilize jitter)
OK_TIP_DIST = 0.06      # normalized thumb-index tip distance for OK gesture


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


# ── State (shared between recognizer thread and HTTP handler) ──────────────
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.gesture = None       # current (voted) gesture label or None
        self.confidence = 0.0
        self.ts = 0.0             # epoch of last recognized frame
        self.frames = 0
        self.fps = 0.0
        self.hands = 0
        self.votes = []           # recent raw labels, majority-vote over
        self.last_raw = None      # last single-frame result (unvoted)


STATE = State()


# ── Frame ingestion (same pattern as video_ai_processor.py) ────────────────
def read_frames_loop(source_url, frame_q, stop):
    """Background thread: pull frames from a cv2-readable source into a
    bounded queue. Exits on stop or unrecoverable error."""
    # A bare integer string ("0", "1") means a local camera index.
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


# ── Recognition ────────────────────────────────────────────────────────────
def ensure_model():
    """Download the MediaPipe gesture model on first run."""
    if MODEL_PATH.exists():
        return
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    log("MODEL", f"Downloading gesture model -> {MODEL_PATH} ...")
    urlretrieve(MODEL_URL, MODEL_PATH)
    log("MODEL", "Model ready.")


def _ok_gesture(landmarks) -> bool:
    """Custom OK check: thumb tip (4) and index tip (8) touch, other fingers
    extended. landmarks are normalized (x, y). Returns True if it looks like
    an OK sign — used as an extra gesture beyond MediaPipe's built-ins."""
    if landmarks is None or len(landmarks) < 21:
        return False
    tip4 = landmarks[4]
    tip8 = landmarks[8]
    d48 = float(np.hypot(tip4.x - tip8.x, tip4.y - tip8.y))
    if d48 > OK_TIP_DIST:
        return False
    # Middle (12), ring (16), pinky (20) tips should be past their PIPs.
    for tip, pip in ((12, 10), (16, 14), (20, 18)):
        if landmarks[tip].y >= landmarks[pip].y:
            return False
    return True


def recognize_loop(frame_q, stop):
    """Background thread: consume frames, run MediaPipe gesture recognition,
    vote-stabilize, and publish to STATE."""
    ensure_model()
    base = python.BaseOptions(model_asset_path=str(MODEL_PATH))
    options = vision.GestureRecognizerOptions(
        base_options=base,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    recognizer = vision.GestureRecognizer.create_from_options(options)

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
            result = recognizer.recognize_for_video(mp_image, ms)
        except Exception as e:
            log("AI", f"Recognition error: {e}")
            continue

        raw = None
        conf = 0.0
        hands = 0
        if result.gestures:
            g = result.gestures[0][0]
            hands = len(result.gestures)
            # 单手操控原则: 画面里出现多只手 → 歧义, 不输出任何手势。
            # 实测: 比 ✌️ 降落时另一只手入画, 首只手被判成 OK(1.00),
            # 把降落命令劫持成右移。多手时宁可不出命令, 也不误发。
            if hands == 1:
                # MediaPipe emits a fake "None" category when no hand is present.
                if g.category_name in ("None", "", "Unknown"):
                    raw = None
                else:
                    raw = g.category_name
                    conf = float(g.score)
                if _ok_gesture(result.hand_landmarks[0] if result.hand_landmarks else None):
                    raw = "OK"
                    conf = 1.0

        with STATE.lock:
            STATE.frames += 1
            STATE.hands = hands
            STATE.last_raw = raw
            if raw:
                STATE.votes.append(raw)
                if len(STATE.votes) > VOTE_WINDOW:
                    STATE.votes.pop(0)
                # Majority vote over the window (ties → newest wins).
                STATE.gesture = max(set(STATE.votes), key=STATE.votes.count)
                STATE.confidence = conf
                STATE.ts = time.time()
            else:
                # No hand in frame — forget old votes so a stale gesture
                # never survives the hand leaving the frame.
                STATE.votes.clear()
                STATE.gesture = None
                STATE.confidence = 0.0
            now = time.monotonic()
            if now - last_log >= 5:
                STATE.fps = (STATE.frames - last_frames) / (now - last_log)
                last_frames = STATE.frames
                last_log = now
                log("AI", f"{STATE.frames} frames, {STATE.fps:.1f} fps, "
                          f"hands={STATE.hands}, gesture={STATE.gesture} "
                          f"({STATE.confidence:.2f}) | raw={raw or '—'}")

    recognizer.close()


# ── HTTP API (the "specialized fast path") ─────────────────────────────────
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
            g = STATE.gesture
            conf = STATE.confidence
            ts = STATE.ts
            frames = STATE.frames
            hands = STATE.hands
            last_raw = STATE.last_raw
        if self.path.rstrip("/") == "/gesture":
            self._json(200, {
                "gesture": g,
                "confidence": round(conf, 3),
                "hands": hands,
                "ts": round(ts, 3),
                "fresh_s": round(time.time() - ts, 2) if ts else None,
                "frames": frames,
                "last_raw": last_raw,
            })
        elif self.path.rstrip("/") == "/health":
            self._json(200, {"status": "ok", "gesture": g, "frames": frames})
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, *args):  # silence request logging
        pass


def main():
    ap = argparse.ArgumentParser(description="Gesture recognition service (MediaPipe -> HTTP)")
    ap.add_argument("--input", default=os.environ.get("VIDEO_GESTURE_INPUT", DEFAULT_INPUT),
                    help=f"Source URL (default: {DEFAULT_INPUT})")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HTTP port (default: {DEFAULT_PORT})")
    args = ap.parse_args()

    log("INIT", f"Source: {args.input} | HTTP :{args.port}")

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)

    threading.Thread(target=read_frames_loop, args=(args.input, frame_q, stop), daemon=True).start()
    threading.Thread(target=recognize_loop, args=(frame_q, stop), daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log("HTTP", f"Gesture API on http://127.0.0.1:{args.port}/gesture")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("INIT", "Interrupted.")
    finally:
        stop.set()


if __name__ == "__main__":
    main()

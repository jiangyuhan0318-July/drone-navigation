#!/usr/bin/env python3
"""guard_center.py — 统一守护中心 (手势 + 坐姿 + 跌倒, 单进程单端口)

一个进程、一次摄像头采集, 三路 MediaPipe 检测跑在同一帧上:
  1. 手势   GestureRecognizer (gesture_recognizer.task) — 8 标准手势 + 自定义 OK
  2. 坐姿   Pose + Face (pose_landmarker_lite + face_landmarker) — 头倾/过近
  3. 跌倒   Pose (与坐姿共用同一实例) — 站立/跌倒/倒地/报警 状态机

一个 HTTP 端口 (默认 8705) 同时提供:
  GET /            HTML 仪表盘: 实时视频 + 三路状态面板
  GET /status      三路状态合并 JSON (给仪表盘/OpenClaw 一次拿全)
  GET /gesture     与 :8700 响应形状一致 — 执行器/技能可原样指过来
  GET /posture     与 :8703 响应形状一致
  GET /fall        与 :8704 响应形状一致
  GET /video       MJPEG 合成视频流 (骨架 + 手部 + 人脸框 + 三路状态角标)
  GET /health

检测逻辑分别移植自 gesture_recognizer.py / posture_guardian.py /
fall_recognizer.py (阈值与多手/冷却/防重规则全部原样), 摄像头同一时刻只能
被一个进程占用 — 开守护中心时, 单独的 gesture/posture/fall 服务必须停掉。

Usage:
  python guard_center.py                    # 默认本机摄像头, :8705
  python guard_center.py --source rtsp://127.0.0.1:8554/crazyflie-drone
  python guard_center.py --port 8705
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
DEFAULT_INPUT = os.environ.get("VIDEO_GUARD_INPUT", "0")
DEFAULT_PORT = int(os.environ.get("GUARD_PORT", "8705"))
DEFAULT_MODE = os.environ.get("GUARD_MODE", "gesture")  # gesture|posture|fall|action
MODES = ("gesture", "posture", "fall", "action")
QUEUE_MAXSIZE = 2

MODELS = Path(__file__).parent / "models"
GESTURE_MODEL = MODELS / "gesture_recognizer.task"
POSE_MODEL = MODELS / "pose_landmarker_lite.task"
FACE_MODEL = MODELS / "face_landmarker.task"

# ── 手势 (gesture_recognizer.py 原值) ─────────────────────────────────────
VOTE_WINDOW = 5         # 手势结果多数投票窗口 (稳抖)
OK_TIP_DIST = 0.06      # 拇指尖(4)-食指尖(8) 归一化距离阈值

# ── 坐姿 (posture_guardian.py 原值, 灵敏度已调低: 2026-08-07) ─────────────
# 原值 11°/700ms 太灵敏 (正常打字/侧头就报"坐姿不端正"), 放宽到 16°/2s:
# 要更明显的头前倾并持续 2 秒才算异常。可用 env 覆盖:
#   POSTURE_LEAN_DEG (默认 16.0), POSTURE_HOLD_MS (默认 2000)
HEAD_LEAN_THRESHOLD_DEG = float(os.environ.get("POSTURE_LEAN_DEG", "16.0"))
TOO_CLOSE_FACE_AREA = 0.075        # 距离过近阈值
REMINDER_AFTER_MS = int(os.environ.get("POSTURE_HOLD_MS", "2000"))
REMINDER_COOLDOWN_MS = 10000       # 两次事件最小间隔

# ── 跌倒 (FallDetectionOverlay.vue 原值, 含已修复的 alert 恢复) ────────────
MIN_PERSON_HEIGHT = 0.12
LYING_CONFIRM_MS = 900
RECOVERY_MS = 600
MAX_SAMPLES = 120

# ── 身体动作 (action_recognizer.py / usePoseControl.js 原值) ───────────────
HOLD_THRESHOLD_MS = 1000      # 姿态持握多久触发
MIN_ACTION_CONFIDENCE = 0.65  # 最低置信度
TRIGGER_COOLDOWN_MS = 2500    # 触发后冷却, 防刷屏

# 骨架/手部连线
POSE_CONNECTIONS = [
    [11, 12], [11, 13], [13, 15], [15, 17], [15, 19], [15, 21], [17, 19],
    [12, 14], [14, 16], [16, 18], [16, 20], [16, 22], [18, 20],
    [11, 23], [12, 24], [23, 24],
    [23, 25], [25, 27], [27, 29], [29, 31],
    [24, 26], [26, 28], [28, 30], [30, 32],
]
HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15],
    [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17],
]

GESTURE_EMOJI = {"Closed_Fist": "✊", "Open_Palm": "🖐", "Pointing_Up": "☝️",
                 "Thumb_Down": "👎", "Thumb_Up": "👍", "Victory": "✌️",
                 "ILoveYou": "🤟", "OK": "👌"}
FALL_COLORS = {"alert": (68, 68, 239), "lying": (68, 68, 239),
               "falling": (11, 158, 245), "standing": (94, 197, 34)}
POSTURE_COLORS = {"normal": (94, 197, 34), "head_down": (11, 158, 245),
                  "too_close": (68, 68, 239), "unknown": (128, 128, 128)}
ACTION_COLORS = {"hands_up": (245, 158, 11), "arms_crossed": (11, 158, 245),
                 "t_pose": (156, 39, 176), "none": (94, 197, 34)}
ACTION_LABELS = {"hands_up": "双手举起", "arms_crossed": "双臂交叉",
                 "t_pose": "T字展开"}


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class State:
    """四路检测的共享状态 (一把锁保护)。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.mode = DEFAULT_MODE  # 四选一: gesture / posture / fall / action
        self.frames = 0
        self.fps = 0.0
        self.ts = 0.0
        # 手势
        self.gesture = None
        self.gesture_conf = 0.0
        self.hands = 0
        self.last_raw = None
        self.gesture_ts = 0.0
        self.votes = []
        # 坐姿
        self.posture = "unknown"
        self.posture_conf = 0.0
        self.posture_features = {}
        self.posture_duration_ms = 0
        self.posture_event = None
        self.posture_ts = 0.0
        # 跌倒
        self.fall_state = "standing"
        self.person = False
        self.fall_conf = 0.0
        self.fall_features = None
        self.fall_event = None
        self.fall_ts = 0.0
        # 身体动作
        self.action = "none"      # hands_up / arms_crossed / t_pose / none
        self.action_conf = 0.0
        self.action_held_ms = 0
        self.action_event = None
        self.action_ts = 0.0


STATE = State()

# 检测线程画好的帧 (供 /video 消费, 丢帧不阻塞检测)
DISPLAY_Q = queue.Queue(maxsize=3)


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


# ── 坐姿分类 (posture_guardian.py 原样) ───────────────────────────────────
def _mid(a, b):
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def head_lean_deg(pose_landmarks):
    ear = _mid(pose_landmarks[7], pose_landmarks[8])
    shoulder = _mid(pose_landmarks[11], pose_landmarks[12])
    dx = ear[0] - shoulder[0]
    dy = max(shoulder[1] - ear[1], 0.001)
    return abs(math.degrees(math.atan2(dx, dy)))


def face_area(face_landmarks):
    xs = [p.x for p in face_landmarks]
    ys = [p.y for p in face_landmarks]
    return max(0.0, (max(xs) - min(xs)) * (max(ys) - min(ys)))


def classify_posture(pose_landmarks, face_landmarks):
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


# ── 身体动作 (action_recognizer.py / usePoseControl.js classifyPose 原样) ───
def classify_pose(lmks):
    """Returns (pose, confidence): pose ∈ hands_up|arms_crossed|t_pose|none"""
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


# ── 跌倒状态机 (fall_recognizer.py 原样, 含 alert 恢复修复) ────────────────
def _avg(a, b):
    return ((a.x + b.x) / 2, (a.y + b.y) / 2)


def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)


def fall_features(pose_landmarks):
    shoulder = _avg(pose_landmarks[11], pose_landmarks[12])
    hip = _avg(pose_landmarks[23], pose_landmarks[24])
    ankle = _avg(pose_landmarks[27], pose_landmarks[28])
    xs = [pt.x for pt in pose_landmarks]
    ys = [pt.y for pt in pose_landmarks]
    bboxW = max(max(xs) - min(xs), 0.001)
    bboxH = max(max(ys) - min(ys), 0.001)
    vis = min((pt.visibility if pt.visibility is not None else 1.0)
              for pt in pose_landmarks)
    return {
        "hip": hip,
        "bboxW": bboxW,
        "bboxH": bboxH,
        "bboxRatio": bboxW / bboxH,
        "axisAngleDeg": math.degrees(math.atan2(abs(shoulder[0] - hip[0]),
                                                abs(shoulder[1] - hip[1]))),
        "visibility": vis,
        "personHeight": max(bboxH, _dist(*shoulder, *hip) + _dist(*hip, *ankle)),
    }


class FallStateMachine:
    def __init__(self):
        self.state = "standing"
        self.samples = []
        self.baseline_hip_y = None
        self.fall_since = 0
        self.lying_since = 0
        self.upright_since = 0
        self.alert_sent = False
        self.event = None

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
            # 恢复站立 → 重置 (浏览器原版在 alert 分支从不更新 upright_since,
            # 报警后永久卡死 — 这里修正)
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
                    self.reset()
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


# ── 手势 OK 检测 (gesture_recognizer.py 原样) ─────────────────────────────
def _ok_gesture(landmarks) -> bool:
    if landmarks is None or len(landmarks) < 21:
        return False
    tip4 = landmarks[4]
    tip8 = landmarks[8]
    d48 = float(np.hypot(tip4.x - tip8.x, tip4.y - tip8.y))
    if d48 > OK_TIP_DIST:
        return False
    for tip, pip in ((12, 10), (16, 14), (20, 18)):
        if landmarks[tip].y >= landmarks[pip].y:
            return False
    return True


# ── 检测主循环: 一帧喂三路 ────────────────────────────────────────────────
def detect_loop(frame_q, stop):
    base_g = python.BaseOptions(model_asset_path=str(GESTURE_MODEL))
    gesture_lm = vision.GestureRecognizer.create_from_options(
        vision.GestureRecognizerOptions(
            base_options=base_g, running_mode=vision.RunningMode.VIDEO,
            num_hands=2, min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5, min_tracking_confidence=0.5))

    base_p = python.BaseOptions(model_asset_path=str(POSE_MODEL))
    pose_lm = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=base_p, running_mode=vision.RunningMode.VIDEO,
            num_poses=1, min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5, min_tracking_confidence=0.5))

    base_f = python.BaseOptions(model_asset_path=str(FACE_MODEL))
    face_lm = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=base_f, running_mode=vision.RunningMode.VIDEO,
            num_faces=1, min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5, min_tracking_confidence=0.5))

    fsm = FallStateMachine()
    last_log = 0
    last_frames = 0
    ms = 0
    last_mode = None
    prev_posture = None
    abnormal_since = 0
    posture_event_at = 0
    last_action = None      # 身体动作状态机 (与浏览器版一致)
    action_since = 0
    action_last_trigger = 0

    while not stop.is_set():
        try:
            img = frame_q.get(timeout=1)
        except queue.Empty:
            continue
        ms += 33
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # ── 模式三选一: 切模式即重置三路状态, 只跑选中的检测 ──
        with STATE.lock:
            mode = STATE.mode
        if mode != last_mode:
            last_mode = mode
            fsm.reset()
            with STATE.lock:
                STATE.votes.clear()
                STATE.gesture = None
                STATE.gesture_conf = 0.0
                STATE.gesture_ts = 0.0
                STATE.posture = "unknown"
                STATE.posture_conf = 0.0
                STATE.posture_features = {}
                STATE.posture_duration_ms = 0
                STATE.posture_event = None
                STATE.posture_ts = 0.0
                STATE.fall_state = "standing"
                STATE.fall_conf = 0.0
                STATE.fall_features = None
                STATE.fall_event = None
                STATE.fall_ts = 0.0
                STATE.action = "none"
                STATE.action_conf = 0.0
                STATE.action_held_ms = 0
                STATE.action_event = None
                STATE.action_ts = 0.0
                STATE.person = False
                STATE.ts = time.time()
            prev_posture = None
            abnormal_since = 0
            log("MODE", f"检测模式: {mode}")

        # ── 手势 (仅 mode=gesture) ──
        gesture = None
        conf = 0.0
        hands = 0
        gres = None
        if mode == "gesture":
            try:
                gres = gesture_lm.recognize_for_video(mp_image, ms)
                if gres.gestures:
                    g = gres.gestures[0][0]
                    hands = len(gres.gestures)
                    if hands == 1:  # 单手操控原则 (多手歧义不出命令)
                        if g.category_name in ("None", "", "Unknown"):
                            gesture = None
                        else:
                            gesture = g.category_name
                            conf = float(g.score)
                        if _ok_gesture(gres.hand_landmarks[0]
                                       if gres.hand_landmarks else None):
                            gesture = "OK"
                            conf = 1.0
            except Exception as e:
                log("AI", f"Gesture error: {e}")

        # ── 姿态骨架 (posture / fall / action 三种模式共用一次 pose 推理) ──
        pose_lmks = None
        if mode in ("posture", "fall", "action"):
            try:
                pres = pose_lm.detect_for_video(mp_image, ms)
                pose_lmks = pres.pose_landmarks[0] if pres.pose_landmarks else None
            except Exception as e:
                log("AI", f"Pose error: {e}")

        # ── 坐姿 (仅 mode=posture: pose + 人脸) ──
        posture = "unknown"
        pconf = 0.0
        pfeats = {}
        face_lmks = None
        posture_event = None
        dur = 0
        if mode == "posture":
            try:
                fres = face_lm.detect_for_video(mp_image, ms)
                face_lmks = fres.face_landmarks[0] if fres.face_landmarks else None
                posture, pconf, pfeats = classify_posture(pose_lmks, face_lmks)
            except Exception as e:
                log("AI", f"Face error: {e}")
            # 坐姿事件 (异常持续 ≥700ms, 10s 冷却 — posture_guardian 原样)
            if posture != prev_posture:
                prev_posture = posture
                abnormal_since = 0 if posture in ("normal", "unknown") else ms
            dur = (ms - abnormal_since) if abnormal_since else 0
            remind = bool(abnormal_since and dur >= REMINDER_AFTER_MS
                          and ms - posture_event_at >= REMINDER_COOLDOWN_MS)
            if remind:
                posture_event = {"state": posture, "ts": time.time()}
                posture_event_at = ms

        # ── 跌倒 (仅 mode=fall, 共用 pose 结果) ──
        fall_event = None
        fconf = 0.0
        ffeats = None
        person = False
        if mode == "fall":
            person = pose_lmks is not None
            if person:
                ffeats = fall_features(pose_lmks)
                fall_event = fsm.step(ffeats, ms)
                fconf = ffeats["visibility"]

        # ── 身体动作 (仅 mode=action, 共用 pose 结果) ──
        # 事件状态机 (浏览器版原样): 同一姿势稳定 ≥1000ms 触发一次, 冷却 2500ms
        action = "none"
        aconf = 0.0
        aheld = 0
        action_event = None
        if mode == "action":
            action, aconf = classify_pose(pose_lmks)
            if not pose_lmks or action == "none":
                action_since = 0
            elif action == last_action:
                aheld = ms - action_since
            else:
                last_action = action
                action_since = ms
                aheld = 0
            if (action != "none" and aconf >= MIN_ACTION_CONFIDENCE
                    and action == last_action and aheld >= HOLD_THRESHOLD_MS
                    and ms - action_last_trigger >= TRIGGER_COOLDOWN_MS):
                action_last_trigger = ms
                action_event = {"pose": action,
                                "confidence": round(aconf, 3),
                                "held_ms": aheld,
                                "ts": time.time()}

        now = time.time()
        with STATE.lock:
            STATE.frames += 1
            STATE.ts = now
            # 手势 (投票窗口)
            STATE.hands = hands
            STATE.last_raw = gesture
            if gesture:
                STATE.votes.append(gesture)
                if len(STATE.votes) > VOTE_WINDOW:
                    STATE.votes.pop(0)
                STATE.gesture = max(set(STATE.votes), key=STATE.votes.count)
                STATE.gesture_conf = conf
                STATE.gesture_ts = now
            else:
                STATE.votes.clear()
                STATE.gesture = None
                STATE.gesture_conf = 0.0
            # 坐姿
            STATE.posture = posture
            STATE.posture_conf = round(pconf, 3)
            STATE.posture_features = pfeats
            STATE.posture_duration_ms = dur
            STATE.posture_ts = now
            if posture_event:
                STATE.posture_event = posture_event
                log("EVENT", f"坐姿异常: {posture} (持续 {dur} ms)")
            # 跌倒
            STATE.person = person
            STATE.fall_state = fsm.state
            STATE.fall_conf = round(fconf, 3)
            STATE.fall_features = (None if ffeats is None else {
                "axis_angle_deg": round(ffeats["axisAngleDeg"], 1),
                "bbox_ratio": round(ffeats["bboxRatio"], 3),
                "person_height": round(ffeats["personHeight"], 3),
                "visibility": round(ffeats["visibility"], 3),
            })
            STATE.fall_ts = now
            if fall_event:
                STATE.fall_event = fall_event
                fsm.event = None
                log("EVENT", f"摔倒确认: axis={fall_event['axis_angle_deg']}° "
                             f"ratio={fall_event['bbox_ratio']}")
            # 身体动作 (低置信显示 none, 与独立版一致; 事件触发线 0.65)
            STATE.action = action if aconf >= MIN_ACTION_CONFIDENCE else "none"
            STATE.action_conf = round(aconf, 3)
            STATE.action_held_ms = aheld
            STATE.action_ts = now
            if action_event:
                STATE.action_event = action_event
                log("EVENT", f"身体动作确认: {action} "
                             f"(conf={aconf:.2f} held={aheld}ms)")

            now_m = time.monotonic()
            if now_m - last_log >= 5:
                STATE.fps = (STATE.frames - last_frames) / (now_m - last_log)
                last_frames = STATE.frames
                last_log = now_m
                log("AI", f"{STATE.frames} frames, {STATE.fps:.1f} fps | "
                          f"gesture={STATE.gesture or '—'} "
                          f"posture={posture} fall={fsm.state} "
                          f"action={action} person={person}")

        # ── 画合成画面 → /video ──
        draw_all(img, pose_lmks, face_lmks,
                 gres.hand_landmarks if gres is not None else None)
        if DISPLAY_Q.full():
            try:
                DISPLAY_Q.get_nowait()
            except queue.Empty:
                pass
        DISPLAY_Q.put_nowait(img)

    gesture_lm.close()
    pose_lm.close()
    face_lm.close()


def draw_all(img, pose_lmks, face_lmks, hand_lmks_list):
    """合成标注: 跌倒骨架色 + 坐姿人脸框色 + 手势手部色 + 动作色 + 状态角标。"""
    h, w = img.shape[:2]
    with STATE.lock:
        fall_color = FALL_COLORS.get(STATE.fall_state, (94, 197, 34))
        posture_color = POSTURE_COLORS.get(STATE.posture, (128, 128, 128))
        gesture = STATE.gesture
        posture = STATE.posture
        fall_state = STATE.fall_state
        action = STATE.action
        action_color = ACTION_COLORS.get(action, (94, 197, 34))

    if pose_lmks is not None:
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in pose_lmks]
        for a, b in POSE_CONNECTIONS:
            cv2.line(img, pts[a], pts[b], action_color, 2)
        for p in pts:
            cv2.circle(img, p, 3, action_color, -1)
    if face_lmks is not None:
        xs = [int(lm.x * w) for lm in face_lmks]
        ys = [int(lm.y * h) for lm in face_lmks]
        cv2.rectangle(img, (min(xs), min(ys)), (max(xs), max(ys)),
                      posture_color, 2)
    if hand_lmks_list:
        for hand in hand_lmks_list:
            pts = [(int(lm.x * w), int(lm.y * h)) for lm in hand]
            for a, b in HAND_CONNECTIONS:
                cv2.line(img, pts[a], pts[b], (0, 255, 255), 2)
            for p in pts:
                cv2.circle(img, p, 3, (0, 255, 255), -1)

    lines = [
        (f"手势: {GESTURE_EMOJI.get(gesture, '—')} {gesture or '无'}",
         (0, 255, 255)),
        (f"坐姿: {posture}", posture_color),
        (f"跌倒: {fall_state}", fall_color),
        (f"动作: {ACTION_LABELS.get(action, action or '无')}", action_color),
    ]
    y = 26
    for text, color in lines:
        cv2.putText(img, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 0, 0), 4)
        cv2.putText(img, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    color, 2)
        y += 26
    return img


# ── HTTP ──────────────────────────────────────────────────────────────────
DASHBOARD_HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>守护中心 · 手势/坐姿/跌倒/动作</title>
<style>
  body { background:#111; color:#eee; font-family:system-ui,sans-serif;
         margin:0; padding:16px; }
  .wrap { display:flex; gap:16px; flex-wrap:wrap; }
  video { width:640px; height:480px; background:#000; border-radius:8px; }
  img.stream { width:640px; height:480px; background:#000; border-radius:8px;
    object-fit:cover; display:block; }
  .panel { flex:1; min-width:260px; }
  .card { background:#1c1c1c; border-radius:8px; padding:12px 16px; margin-bottom:10px; }
  .card h3 { margin:0 0 6px; font-size:14px; color:#999; }
  .big { font-size:24px; font-weight:700; }
  .ok { color:#5ec522; } .warn { color:#f59e0b; } .danger { color:#ef4444; }
  .muted { color:#777; font-size:12px; }
  button { background:#2a2a2a; color:#eee; border:1px solid #444;
    border-radius:6px; padding:8px 14px; margin-right:8px; font-size:14px;
    cursor:pointer; }
</style></head><body>
<div class="wrap">
  <div><img class="stream" src="/video" alt="检测画面">
    <p class="muted" id="meta">连接中…</p></div>
  <div class="panel">
    <div class="card"><h3>🎛 检测模式 (四选一)</h3>
      <button data-mode="gesture">✋ 手势</button>
      <button data-mode="posture">🪑 坐姿</button>
      <button data-mode="fall">🧍 跌倒</button>
      <button data-mode="action">🙌 动作</button>
      <div class="muted" id="mode-meta"></div></div>
    <div class="card" id="card-gesture"><h3>✋ 手势</h3><div class="big" id="gesture">—</div>
      <div class="muted" id="gesture-meta"></div></div>
    <div class="card" id="card-posture"><h3>🪑 坐姿</h3><div class="big" id="posture">—</div>
      <div class="muted" id="posture-meta"></div></div>
    <div class="card" id="card-fall"><h3>🧍 跌倒</h3><div class="big" id="fall">—</div>
      <div class="muted" id="fall-meta"></div></div>
    <div class="card" id="card-action"><h3>🙌 身体动作</h3><div class="big" id="action">—</div>
      <div class="muted" id="action-meta"></div></div>
  </div>
</div>
<script>
const EMOJI = {"Closed_Fist":"✊","Open_Palm":"🖐","Pointing_Up":"☝️",
  "Thumb_Down":"👎","Thumb_Up":"👍","Victory":"✌️","ILoveYou":"🤟","OK":"👌"};
const MODES = {gesture:'✋ 手势', posture:'🪑 坐姿', fall:'🧍 跌倒',
  action:'🙌 动作'};
const ACTIONS = {hands_up:'🙌 双手举起', arms_crossed:'🙅 双臂交叉',
  t_pose:'⭐ T字展开'};
const CLS = {"normal":"ok","standing":"ok","unknown":"muted"};
function cls(k){ return CLS[k] || (["alert","lying","too_close","head_down",
  "falling"].includes(k) ? "danger" : "warn"); }
function paintMode(s){
  document.querySelectorAll('button[data-mode]').forEach(b => {
    const on = b.dataset.mode === s.mode;
    b.style.opacity = on ? 1 : 0.4;
    b.style.borderColor = on ? '#5ec522' : '#444';
  });
  for (const k of ['gesture','posture','fall','action'])
    document.getElementById('card-' + k).style.opacity = s.mode === k ? 1 : 0.35;
  document.getElementById('mode-meta').textContent =
    '当前: ' + (MODES[s.mode] || s.mode);
}
async function poll(){
  try {
    const s = await (await fetch('/status')).json();
    paintMode(s);
    document.getElementById('gesture').textContent =
      (s.gesture ? (EMOJI[s.gesture]||'') + ' ' + s.gesture : '无');
    document.getElementById('gesture').className = 'big ' +
      (s.gesture ? 'ok' : 'muted');
    document.getElementById('gesture-meta').textContent =
      `conf=${s.gesture_conf?.toFixed(2)} hands=${s.hands} fresh=${s.gesture_fresh_s}s`;
    const p = document.getElementById('posture');
    p.textContent = s.posture; p.className = 'big ' + cls(s.posture);
    document.getElementById('posture-meta').textContent =
      `conf=${s.posture_conf?.toFixed(2)} dur=${s.posture_duration_ms}ms`;
    const f = document.getElementById('fall');
    f.textContent = s.fall_state; f.className = 'big ' + cls(s.fall_state);
    document.getElementById('fall-meta').textContent =
      `person=${s.person} conf=${s.fall_conf?.toFixed(2)}`;
    const a = document.getElementById('action');
    a.textContent = ACTIONS[s.action] || s.action || '—';
    a.className = 'big ' + (s.action === 'none' ? 'muted' : 'ok');
    document.getElementById('action-meta').textContent =
      `conf=${s.action_conf?.toFixed(2)} held=${s.action_held_ms}ms`;
    document.getElementById('meta').textContent =
      `frames=${s.frames} fps=${s.fps?.toFixed(1)}`;
  } catch (e) { document.getElementById('meta').textContent = '服务不可达: ' + e; }
}
document.querySelectorAll('button[data-mode]').forEach(b =>
  b.addEventListener('click', async () => {
    document.getElementById('mode-meta').textContent = '切换中…';
    try {
      const r = await fetch('/mode', {method:'PUT',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({mode: b.dataset.mode})});
      const j = await r.json();
      document.getElementById('mode-meta').textContent =
        '→ ' + (MODES[j.mode] || j.mode || ('错误: ' + JSON.stringify(j)));
    } catch (e) {
      document.getElementById('mode-meta').textContent = '切换失败: ' + e;
    }
  }));
setInterval(poll, 500); poll();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _snap(self):
        with STATE.lock:
            now = time.time()
            gts = STATE.gesture_ts or 0
            pts = STATE.posture_ts or 0
            fts = STATE.fall_ts or 0
            ats = STATE.action_ts or 0
            return {
                "mode": STATE.mode,
                "gesture": STATE.gesture,
                "gesture_conf": round(STATE.gesture_conf, 3),
                "hands": STATE.hands,
                "last_raw": STATE.last_raw,
                "gesture_fresh_s": round(now - gts, 2) if gts else None,
                "posture": STATE.posture,
                "posture_conf": STATE.posture_conf,
                "posture_features": STATE.posture_features,
                "posture_duration_ms": STATE.posture_duration_ms,
                "posture_event": STATE.posture_event,
                "posture_fresh_s": round(now - pts, 2) if pts else None,
                "fall_state": STATE.fall_state,
                "person": STATE.person,
                "fall_conf": STATE.fall_conf,
                "fall_features": STATE.fall_features,
                "fall_event": STATE.fall_event,
                "fall_fresh_s": round(now - fts, 2) if fts else None,
                "action": STATE.action,
                "action_conf": STATE.action_conf,
                "action_held_ms": STATE.action_held_ms,
                "action_event": STATE.action_event,
                "action_fresh_s": round(now - ats, 2) if ats else None,
                "frames": STATE.frames,
                "fps": round(STATE.fps, 2),
                "ts": now,
            }

    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        if path == "/":
            body = DASHBOARD_HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/status":
            self._json(200, self._snap())
        elif path == "/mode":
            with STATE.lock:
                mode = STATE.mode
            self._json(200, {"mode": mode, "modes": list(MODES)})
        elif path == "/gesture":
            snap = self._snap()
            self._json(200, {
                "mode": snap["mode"],
                "active": snap["mode"] == "gesture",
                "gesture": snap["gesture"],
                "confidence": snap["gesture_conf"],
                "hands": snap["hands"],
                "ts": round(snap["ts"], 3),
                "fresh_s": snap["gesture_fresh_s"],
                "frames": snap["frames"],
                "last_raw": snap["last_raw"],
            })
        elif path == "/posture":
            snap = self._snap()
            self._json(200, {
                "mode": snap["mode"],
                "active": snap["mode"] == "posture",
                "state": snap["posture"],
                "confidence": snap["posture_conf"],
                "features": snap["posture_features"],
                "duration_ms": snap["posture_duration_ms"],
                "event": snap["posture_event"],
                "ts": round(snap["ts"], 3),
                "fresh_s": snap["posture_fresh_s"],
                "frames": snap["frames"],
            })
        elif path == "/fall":
            snap = self._snap()
            self._json(200, {
                "mode": snap["mode"],
                "active": snap["mode"] == "fall",
                "state": snap["fall_state"],
                "person": snap["person"],
                "confidence": snap["fall_conf"],
                "features": snap["fall_features"],
                "last_event": snap["fall_event"],
                "ts": round(snap["ts"], 3),
                "frames": snap["frames"],
                "fps": snap["fps"],
            })
        elif path == "/action":
            snap = self._snap()
            self._json(200, {
                "mode": snap["mode"],
                "active": snap["mode"] == "action",
                "state": snap["action"],
                "person": snap["person"],
                "confidence": snap["action_conf"],
                "held_ms": snap["action_held_ms"],
                "last_event": snap["action_event"],
                "ts": round(snap["ts"], 3),
                "frames": snap["frames"],
                "fps": snap["fps"],
            })
        elif path == "/video":
            self._stream_video()
        elif path == "/health":
            with STATE.lock:
                frames = STATE.frames
            self._json(200, {"status": "ok", "frames": frames})
        else:
            self._json(404, {"error": "not found"})

    def do_PUT(self):
        """切换检测模式 (四选一): PUT /mode {"mode": "gesture|posture|fall|action"}"""
        path = self.path.rstrip("/") or "/"
        if path != "/mode":
            self._json(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            self._json(400, {"error": "bad json body"})
            return
        mode = body.get("mode")
        if mode not in MODES:
            self._json(400, {"error": f"mode 必须是 {list(MODES)} 之一"})
            return
        with STATE.lock:
            STATE.mode = mode
        log("MODE", f"HTTP 切换模式 → {mode}")
        self._json(200, {"mode": mode, "modes": list(MODES)})

    def _stream_video(self):
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
                return

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(prog="guard_center.py", description=__doc__)
    ap.add_argument("--source", default=DEFAULT_INPUT,
                    help="视频源: 0=本机摄像头 / rtsp://... / 文件")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"HTTP 端口 (默认 {DEFAULT_PORT})")
    ap.add_argument("--mode", default=DEFAULT_MODE, choices=list(MODES),
                    help="初始检测模式 (默认取 GUARD_MODE 环境变量, 运行时可用 "
                         "PUT /mode 切换)")
    args = ap.parse_args()

    with STATE.lock:
        STATE.mode = args.mode

    for model in (GESTURE_MODEL, POSE_MODEL, FACE_MODEL):
        if not model.exists():
            log("INIT", f"模型缺失: {model} — 检查 extension/models/")
            return 1

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
    threading.Thread(target=read_frames_loop, args=(args.source, frame_q, stop),
                     daemon=True).start()
    threading.Thread(target=detect_loop, args=(frame_q, stop),
                     daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log("HTTP", f"guard center on http://127.0.0.1:{args.port}/ "
                f"(dashboard) /status /mode /gesture /posture /fall /action "
                f"/video — 模式: {args.mode} (四选一, PUT /mode 可切换)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        srv.server_close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
video_ai_processor.py — 地面站视频 AI 处理服务

拉取无人机/摄像头视频流，用 YOLO 做实时目标检测，把检测框叠加回画面，
再以新流名推回 MediaMTX —— 前端切到 "AI 视图" 即可看到叠加结果，原始流不动。

输入（二选一，默认 MediaMTX RTSP）：
  --input rtsp://127.0.0.1:8554/crazyflie-drone              # MediaMTX RTSP（低延迟）
  --input http://192.168.0.106/stream                         # AI-Deck MJPEG（低延迟）

输出：
  WHIP 推回 MediaMTX 新路径（默认 crazyflie-drone-ai）
  --no-push 只跑检测 + 打日志，不推流（调试用）

Usage:
  python video_ai_processor.py
  python video_ai_processor.py --input http://192.168.0.106/stream
  python video_ai_processor.py --classes dog,person --no-push
  python video_ai_processor.py --model yolov8n.pt --conf 0.5
"""
import argparse
import asyncio
import os
import queue
import threading
import time
from urllib.parse import urlparse

import cv2
import numpy as np
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
import aiohttp

# ── Configuration ──────────────────────────────────────────────────────────
MEDIAMTX_BASE_URL = os.environ.get("MEDIAMTX_URL", "http://127.0.0.1:8889")
MEDIAMTX_API_URL = os.environ.get("MEDIAMTX_API", "http://127.0.0.1:9997")
SOURCE_STREAM_ID = os.environ.get("SOURCE_STREAM_ID", "crazyflie-drone")
OUTPUT_STREAM_ID = os.environ.get("OUTPUT_STREAM_ID", "crazyflie-drone-ai")

DEFAULT_INPUT = f"rtsp://127.0.0.1:8554/{SOURCE_STREAM_ID}"  # MediaMTX RTSP (low latency)

STUN_SERVER = os.environ.get("STUN_SERVER", "")  # see simple_webcam.py for rationale
MONITOR_INTERVAL = 10  # seconds between stats / viewer log lines

# Detection tuning
DEFAULT_MODEL = "yolov8n.pt"   # tiny/fast; swap for yolo11n.pt, yolov8s.pt, ...
DEFAULT_CONF = 0.35            # confidence threshold
DEFAULT_IOU = 0.45
QUEUE_MAXSIZE = 2              # drop frames rather than build latency

# Box rendering
BOX_COLOR = (0, 255, 0)
BOX_THICKNESS = 2
LABEL_BG = (0, 0, 0)
LABEL_FG = (255, 255, 255)


def log(tag, msg):
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class AIVideoTrack(VideoStreamTrack):
    """WebRTC video track that serves the latest AI-processed frame.

    The detection thread writes into `state`; recv() just reads the newest
    frame, so a slow detector drops video frames (never blocks the peer).

    Timestamps use aiortc's next_timestamp() like simple_webcam.py does —
    RTP needs the 90 kHz clock, and a hand-rolled time_base corrupts the
    media stream (MediaMTX kills the WHIP session within seconds).
    """

    def __init__(self):
        super().__init__()
        self.state = None        # latest processed frame (BGR ndarray) or None
        self.stats = None        # latest detection stats dict or None
        self._first_frame = asyncio.Event()

    async def recv(self):
        # Block until the first AI frame exists; never send placeholder frames
        # (a mid-stream resolution change also breaks the RTP decoder).
        if self.state is None:
            await self._first_frame.wait()
        frame = self.state
        pts, time_base = await self.next_timestamp()
        new_frame = VideoFrame.from_ndarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), format="rgb24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame


# ── Frame ingestion ────────────────────────────────────────────────────────
def read_frames_loop(source_url, frame_q, stop):
    """Background thread: pull frames from a cv2-readable source (RTSP or
    MJPEG) and feed a bounded queue. Exits on stop or unrecoverable error.

    cv2 is used instead of PyAV on purpose: this process also encodes with
    aiortc, and mixing PyAV's libav (v62) with cv2's bundled libav (v61) in
    one process corrupts the WHIP stream (MediaMTX kills the session). cv2
    reading + aiortc encoding is the combination proven stable by
    simple_webcam.py.
    """
    while not stop.is_set():
        cap = cv2.VideoCapture(source_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low: don't buffer
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
                    frame_q.get_nowait()  # drop oldest; keep latency low
                except queue.Empty:
                    pass
            frame_q.put_nowait(img)
        cap.release()
        stop.wait(3)


# ── Detection ──────────────────────────────────────────────────────────────
class Detector:
    """Minimal wrapper around ultralytics YOLO (lazy init, thread-safe predict)."""

    def __init__(self, model_path, conf, iou, class_filter):
        self.model_path = model_path
        self.conf = conf
        self.iou = iou
        self.class_filter = class_filter
        self.model = None
        self.names = []

    def ensure_loaded(self):
        if self.model is None:
            from ultralytics import YOLO
            log("AI", f"Loading YOLO model: {self.model_path} (first run downloads it)...")
            self.model = YOLO(self.model_path)
            self.names = self.model.names
            if self.class_filter:
                log("AI", f"Filtering classes: {[self.names[c] for c in self.class_filter]}")
            log("AI", "Model ready.")
        return self.model

    def predict(self, img):
        """Run detection, return (annotated_bgr, stats_dict)."""
        self.ensure_loaded()
        t0 = time.monotonic()
        results = self.model.predict(img, conf=self.conf, iou=self.iou,
                                     classes=self.class_filter, verbose=False)
        infer_ms = (time.monotonic() - t0) * 1000
        r = results[0]
        boxes = r.boxes
        annotated = img.copy()
        dets = []
        if boxes is not None and len(boxes):
            xyxy = boxes.xyxy.cpu().numpy().astype(int)
            confs = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), c, cl in zip(xyxy, confs, cls):
                name = self.names.get(cl, f"class-{cl}")
                dets.append({"label": name, "conf": float(c),
                             "box": [int(x1), int(y1), int(x2), int(y2)]})
                cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)),
                              BOX_COLOR, BOX_THICKNESS)
                label = f"{name} {c:.2f}"
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                y1_txt = max(int(y1) - th - 6, 0)
                cv2.rectangle(annotated, (int(x1), y1_txt),
                              (int(x1) + tw + 6, int(y1)), LABEL_BG, -1)
                cv2.putText(annotated, label, (int(x1) + 3, int(y1) - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, LABEL_FG, 1, cv2.LINE_AA)
        stats = {"count": len(dets), "detections": dets, "infer_ms": infer_ms}
        return annotated, stats


def detect_loop(detector, frame_q, track, stop):
    """Background thread: consume frames, detect, annotate, publish to track."""
    last_log = 0
    frames = 0
    while not stop.is_set():
        try:
            img = frame_q.get(timeout=1)
        except queue.Empty:
            continue
        try:
            annotated, stats = detector.predict(img)
        except Exception as e:
            log("AI", f"Detection error: {e}")
            annotated, stats = img, {"count": 0, "detections": [], "infer_ms": 0}
        frames += 1
        stats["fps"] = frames
        stats["latency_ms"] = detector_latency(frame_q)
        track.state = annotated
        track.stats = stats
        track._first_frame.set()
        now = time.monotonic()
        if now - last_log >= 5:
            last_log = now
            labels = ", ".join(f"{d['label']} {d['conf']:.2f}" for d in stats["detections"][:4])
            log("AI", f"{frames} frames, {stats['count']} object(s), "
                      f"infer {stats['infer_ms']:.0f} ms | {labels or '—'}")


def detector_latency(frame_q):
    """Rough queue depth as a proxy for detection-induced latency."""
    return frame_q.qsize()


# ── WHIP publish (mirrors simple_webcam.py) ────────────────────────────────
def describe_sdp_candidates(sdp):
    found = []
    for line in sdp.splitlines():
        if not line.startswith("a=candidate:"):
            continue
        parts = line.split()
        try:
            ip, port = parts[4], parts[5]
            ctype = parts[parts.index("typ") + 1]
        except (ValueError, IndexError):
            continue
        found.append(f"{ip}:{port} ({ctype})")
    return found


def stream_path_name(server_url, stream_id):
    prefix = urlparse(server_url).path.strip("/")
    return f"{prefix}/{stream_id}" if prefix else stream_id


async def log_selected_ice_pair(pc):
    try:
        stats = await pc.getStats()
        for stat in stats.values():
            if getattr(stat, "type", None) != "candidate-pair":
                continue
            if not getattr(stat, "nominated", False) or getattr(stat, "state", None) != "succeeded":
                continue
            local = stats.get(stat.localCandidateId)
            remote = stats.get(stat.remoteCandidateId)
            l_desc = f"{getattr(local, 'ip', '?')}:{getattr(local, 'port', '?')} ({getattr(local, 'candidateType', '?')})"
            r_desc = f"{getattr(remote, 'ip', '?')}:{getattr(remote, 'port', '?')} ({getattr(remote, 'candidateType', '?')})"
            log("ICE", f"Selected path: local {l_desc} <-> remote {r_desc}")
            return
    except Exception as e:
        log("ICE", f"Could not read selected candidate pair: {e}")


async def monitor(pc, api_base, path_name, interval=MONITOR_INTERVAL):
    """Log upload bitrate and viewer counts from MediaMTX Control API."""
    api_ok = True
    last_bytes = 0
    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(interval)
            try:
                stats = await pc.getStats()
                for stat in stats.values():
                    if getattr(stat, "type", None) == "outbound-rtp" and getattr(stat, "kind", None) == "video":
                        mb = stat.bytesSent / 1_000_000
                        kbps = (stat.bytesSent - last_bytes) * 8 / 1000 / interval
                        last_bytes = stat.bytesSent
                        log("STATS", f"Uploading: {mb:.2f} MB total, {stat.packetsSent} packets, ~{kbps:.0f} kbps")
            except Exception as e:
                log("STATS", f"Could not read WebRTC stats: {e}")
            if not api_base:
                continue
            try:
                async with session.get(
                    f"{api_base.rstrip('/')}/v3/webrtcsessions/list",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    data = await resp.json()
                sessions = [s for s in data.get("items", []) if s.get("path") == path_name]
                viewers = [s for s in sessions if s.get("state") == "read"]
                publishers = [s for s in sessions if s.get("state") == "publish"]
                if not api_ok:
                    log("VIEWERS", "MediaMTX control API reachable again.")
                    api_ok = True
                log("VIEWERS", f"{len(viewers)} viewer(s) watching '{path_name}' "
                               f"(publish sessions: {len(publishers)})")
                for v in viewers:
                    log("VIEWERS", f"  - {v.get('remoteAddr', '?')} "
                                   f"({v.get('bytesSent', 0) / 1000:.0f} kB delivered)")
            except Exception as e:
                if api_ok:
                    log("VIEWERS", f"MediaMTX control API unreachable at {api_base} ({e}); "
                                   "viewer stats muted until it recovers.")
                    api_ok = False


async def whip_publish(track, server_url, stream_id):
    """WHIP handshake + pump until ICE dies (mirrors simple_webcam.py)."""
    whip_endpoint = f"{server_url}/{stream_id}/whip"
    path_name = stream_path_name(server_url, stream_id)
    log("WHIP", f"Publishing AI view to {whip_endpoint} (path '{path_name}')")

    rtc_config = RTCConfiguration(
        iceServers=[RTCIceServer(urls=[STUN_SERVER])] if STUN_SERVER else []
    )
    pc = RTCPeerConnection(configuration=rtc_config)
    pc.addTrack(track)

    ice_failed = asyncio.Event()

    @pc.on("iceconnectionstatechange")
    async def on_ice_state_change():
        log("ICE", f"ICE connection state -> {pc.iceConnectionState}")
        if pc.iceConnectionState == "connected":
            await log_selected_ice_pair(pc)
        elif pc.iceConnectionState in ("failed", "closed"):
            ice_failed.set()

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)

    async with aiohttp.ClientSession() as session:
        log("WHIP", f"POSTing SDP offer to {whip_endpoint} ...")
        try:
            async with session.post(
                whip_endpoint,
                data=pc.localDescription.sdp,
                headers={"Content-Type": "application/sdp"},
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log("WHIP", f"Handshake FAILED: HTTP {resp.status}")
                    log("WHIP", f"Error details: {text.strip()[:500]}")
                    return 1
                sdp_answer = await resp.text()
                log("WHIP", f"Handshake SUCCEEDED: HTTP {resp.status}")
        except Exception as e:
            log("WHIP", f"Handshake FAILED: could not reach {whip_endpoint} ({e})")
            return 1

    await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp_answer, type="answer"))
    log("LIVE", f"AI view LIVE as '{stream_id}'")

    monitor_task = asyncio.create_task(monitor(pc, MEDIAMTX_API_URL, path_name))
    try:
        await ice_failed.wait()
        log("LIVE", "ICE connection lost — exiting (restart to retry).")
    finally:
        monitor_task.cancel()
        await pc.close()
    return 1


# ── CLI ────────────────────────────────────────────────────────────────────
def parse_classes(raw):
    """'dog,person' -> [16, 0] (COCO ids); empty string -> None (all classes)."""
    if not raw:
        return None
    from ultralytics.utils import LOGGER  # noqa: F401  (force import check early)
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    from ultralytics import YOLO
    m = YOLO(DEFAULT_MODEL)  # just to resolve names
    names = m.names
    ids = []
    for token in (t.strip() for t in raw.split(",") if t.strip()):
        if token.isdigit():
            ids.append(int(token))
        else:
            matches = [i for i, n in names.items() if n.lower() == token.lower()]
            if not matches:
                raise SystemExit(f"Unknown class '{token}' — available: {', '.join(names.values())[:200]}...")
            ids.append(matches[0])
    return ids


def main():
    ap = argparse.ArgumentParser(description="Ground-station AI video processor (YOLO annotate -> MediaMTX)")
    ap.add_argument("--input", default=os.environ.get("VIDEO_AI_INPUT", DEFAULT_INPUT),
                    help=f"Source URL (default: {DEFAULT_INPUT})")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"YOLO model (default: {DEFAULT_MODEL})")
    ap.add_argument("--conf", type=float, default=DEFAULT_CONF, help="Confidence threshold")
    ap.add_argument("--iou", type=float, default=DEFAULT_IOU, help="NMS IoU threshold")
    ap.add_argument("--classes", default=None,
                    help="Comma-separated class names or ids to keep (e.g. 'dog,person'); default: all")
    ap.add_argument("--stream-id", default=OUTPUT_STREAM_ID,
                    help=f"Output MediaMTX path (default: {OUTPUT_STREAM_ID})")
    ap.add_argument("--no-push", action="store_true", help="Detect + log only, do not publish")
    args = ap.parse_args()

    log("INIT", f"Source: {args.input}")
    log("INIT", f"Output: {'(local only, --no-push)' if args.no_push else f'{args.stream_id} via WHIP -> {MEDIAMTX_BASE_URL}'}")

    class_filter = parse_classes(args.classes) if args.classes else None
    detector = Detector(args.model, args.conf, args.iou, class_filter)

    stop = threading.Event()
    frame_q = queue.Queue(maxsize=QUEUE_MAXSIZE)
    track = AIVideoTrack()

    threads = [
        threading.Thread(target=read_frames_loop, args=(args.input, frame_q, stop), daemon=True),
        threading.Thread(target=detect_loop, args=(detector, frame_q, track, stop), daemon=True),
    ]
    for t in threads:
        t.start()

    try:
        if args.no_push:
            log("INIT", "--no-push: running detector only (Ctrl+C to stop).")
            while True:
                time.sleep(1)
        else:
            asyncio.run(whip_publish(track, MEDIAMTX_BASE_URL, args.stream_id))
    except KeyboardInterrupt:
        log("INIT", "Interrupted.")
    finally:
        stop.set()


if __name__ == "__main__":
    main()

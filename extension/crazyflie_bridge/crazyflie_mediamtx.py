import asyncio
import os
import socket
import threading
import time
import urllib.request
from urllib.parse import urlparse

import cv2
import numpy as np
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
import aiohttp

# ── Configuration ──────────────────────────────────────────────────────────
# Publishes the REAL Crazyflie drone's camera to MediaMTX over WHIP, so any
# number of viewers can watch it via WHEP (e.g. the Real Drone page).
#
# Source: the MJPEG proxy from crazyflie_discovery_game/crazyflie_bridge
# (`start_bridge.sh` -> video_stream_proxy.py), which re-broadcasts the
# drone's ESP32 AI-Deck stream as multipart/x-mixed-replace.
#
# Local run (local MediaMTX):
#   MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 \
#     python crazyflie_mediamtx.py
#
# Env overrides:
#   CRAZYFLIE_STREAM_URL  MJPEG source      (default http://localhost:8082/stream)
#   LIVESTREAM_ID         MediaMTX path     (default crazyflie-drone)
#   MEDIAMTX_URL          WHIP base URL     (default https://drone-navigation.com/live)
#   MEDIAMTX_API          control API base  (default https://drone-navigation.com/control-api)
#   STATS_INTERVAL_S      periodic upload-stats log line in seconds
#                         (default 0 = quiet: logs only on state changes)
MEDIAMTX_BASE_URL = os.environ.get("MEDIAMTX_URL", "https://drone-navigation.com/live")

LIVESTREAM_HOSTNAME = os.environ.get("LIVESTREAM_ID", "crazyflie-drone")

MEDIAMTX_API_URL = os.environ.get("MEDIAMTX_API", "https://drone-navigation.com/control-api")

CRAZYFLIE_STREAM_URL = os.environ.get("CRAZYFLIE_STREAM_URL", "http://localhost:8082/stream")

STUN_SERVER = "stun:stun.l.google.com:19302"
MONITOR_INTERVAL = 10  # seconds between monitor ticks (not necessarily log lines)
# Periodic STATS/VIEWERS lines are OFF by default — the monitor logs on
# CHANGE only (viewer count, API up/down, stats errors). Set STATS_INTERVAL_S
# (e.g. 60) to re-enable a periodic upload-stats line for debugging.
STATS_INTERVAL_S = int(os.environ.get("STATS_INTERVAL_S", "0"))


def log(tag, msg):
    """Timestamped, tagged log line."""
    print(f"[{time.strftime('%H:%M:%S')}] [{tag}] {msg}", flush=True)


class MJPEGReader:
    """Background-thread reader for multipart/x-mixed-replace MJPEG streams.

    Parses frames by scanning for JPEG SOI/EOI markers (same approach as the
    bridge's own proxy), so it is immune to boundary-string quirks. Exposes
    the latest decoded BGR frame plus a sequence number for freshness checks.
    """

    def __init__(self, url):
        self.url = url
        self.connected = False
        self._frame = None
        self._seq = 0
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        # Bypass system HTTP proxies: the upstream is a localhost/LAN address.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while self._running:
            try:
                req = urllib.request.Request(
                    self.url,
                    headers={"User-Agent": "crazyflie-mediamtx/1.0", "Accept": "*/*"},
                )
                with opener.open(req, timeout=10) as resp:
                    self.connected = True
                    log("MJPEG", f"Connected to {self.url}")
                    buffer = bytearray()
                    while self._running:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        buffer.extend(chunk)
                        while True:
                            soi = buffer.find(b"\xff\xd8")
                            if soi < 0:
                                break
                            eoi = buffer.find(b"\xff\xd9", soi + 2)
                            if eoi < 0:
                                break
                            jpg = bytes(buffer[soi : eoi + 2])
                            buffer = bytearray(buffer[eoi + 2 :])
                            frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if frame is None:
                                continue
                            with self._lock:
                                self._frame = frame
                                self._seq += 1
            except Exception as e:
                if self._running:
                    log("MJPEG", f"Stream error: {e}; retrying in 2 s")
                self.connected = False
                time.sleep(2)

    def read(self):
        """Return (sequence_number, latest BGR frame or None)."""
        with self._lock:
            return self._seq, self._frame

    def stop(self):
        self._running = False

class CrazyflieStreamTrack(VideoStreamTrack):
    def __init__(self, reader):
        super().__init__()
        self.reader = reader
        self._last_seq = 0

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # Wait briefly for a FRESH frame; the ESP32 delivers ~10-15 fps while
        # WebRTC pacing asks at 30 fps, so reuse the last frame on starvation.
        deadline = time.monotonic() + 0.5
        seq, frame = self.reader.read()
        while seq == self._last_seq and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
            seq, frame = self.reader.read()
        if frame is None:
            raise Exception("No Crazyflie frame available yet")
        self._last_seq = seq

        # Copy before drawing so the reader's stored frame stays pristine
        # (a reused frame must not accumulate overlays).
        frame = frame.copy()

        # Overlay identifying text, scaled to the (small) drone resolution.
        h, w = frame.shape[:2]
        scale = max(0.4, min(1.0, w / 640))
        cv2.putText(
            frame,
            f"{LIVESTREAM_HOSTNAME} - {time.strftime('%H:%M:%S')}",
            (10, max(20, int(h * 0.12))),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (0, 255, 0),
            1 if scale < 0.7 else 2,
        )

        new_frame = VideoFrame.from_ndarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), format="rgb24")
        new_frame.pts = pts
        new_frame.time_base = time_base
        return new_frame


# STUN server configuration for NAT traversal
rtc_config = RTCConfiguration(
    iceServers=[RTCIceServer(urls=[STUN_SERVER])]
)


def describe_sdp_candidates(sdp):
    """Extract a list of candidate IPs/ports from an SDP block."""
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
    """'https://drone-navigation.com/live' + 'crazyflie-drone' -> 'live/crazyflie-drone'."""
    prefix = urlparse(server_url).path.strip("/")
    return f"{prefix}/{stream_id}" if prefix else stream_id


async def log_selected_ice_pair(pc):
    """Report active ICE candidate pair once connected."""
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
    """Watch upload stats and viewer counts; log on CHANGE only (quiet by
    default — a 10 s periodic line is ~17k lines/day/publisher)."""
    api_ok = True
    stats_ok = True
    last_bytes = 0
    last_counts = None  # (viewers, publishers) last logged
    ticks = 0
    async with aiohttp.ClientSession() as session:
        while True:
            await asyncio.sleep(interval)
            ticks += 1

            # Upload progress — periodic line only when STATS_INTERVAL_S > 0.
            try:
                stats = await pc.getStats()
                for stat in stats.values():
                    if getattr(stat, "type", None) == "outbound-rtp" and getattr(stat, "kind", None) == "video":
                        if STATS_INTERVAL_S and ticks % max(1, STATS_INTERVAL_S // interval) == 0:
                            mb = stat.bytesSent / 1_000_000
                            kbps = (stat.bytesSent - last_bytes) * 8 / 1000 / interval
                            log("STATS", f"Uploading: {mb:.2f} MB total, {stat.packetsSent} packets, ~{kbps:.0f} kbps")
                        last_bytes = stat.bytesSent
                if not stats_ok:
                    log("STATS", "WebRTC stats readable again.")
                    stats_ok = True
            except Exception as e:
                if stats_ok:  # log the failure once, not every tick
                    log("STATS", f"Could not read WebRTC stats ({e}); muted until it recovers.")
                    stats_ok = False

            # Viewer count via MediaMTX API — log only when the counts change.
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
                counts = (len(viewers), len(publishers))
                if counts != last_counts:
                    log("VIEWERS", f"{counts[0]} viewer(s) watching '{path_name}' "
                                   f"(publish sessions: {counts[1]})")
                    for v in viewers:
                        log("VIEWERS", f"  - {v.get('remoteAddr', '?')} "
                                       f"({v.get('bytesSent', 0) / 1000:.0f} kB delivered)")
                    last_counts = counts
            except Exception as e:
                if api_ok:
                    log("VIEWERS", f"MediaMTX control API unreachable at {api_base} ({e}); "
                                   "viewer stats muted until it recovers.")
                    api_ok = False


async def run_whip_publisher(server_url, stream_id):
    whip_endpoint = f"{server_url}/{stream_id}/whip"
    path_name = stream_path_name(server_url, stream_id)

    log("INIT", f"Stream ID: '{stream_id}' (MediaMTX path: '{path_name}')")
    log("INIT", f"WHIP endpoint: {whip_endpoint}")
    log("INIT", f"Crazyflie MJPEG source: {CRAZYFLIE_STREAM_URL}")

    # Resolve target host
    host = urlparse(server_url).hostname
    try:
        addrs = sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
        log("INIT", f"MediaMTX target host '{host}' resolves to: {', '.join(addrs)}")
    except Exception as e:
        log("INIT", f"Could not resolve host '{host}': {e}")

    log("INIT", f"Using STUN server: {STUN_SERVER}")

    pc = RTCPeerConnection(configuration=rtc_config)

    @pc.on("iceconnectionstatechange")
    async def on_ice_state_change():
        log("ICE", f"ICE connection state -> {pc.iceConnectionState}")
        if pc.iceConnectionState == "connected":
            await log_selected_ice_pair(pc)
        elif pc.iceConnectionState == "failed":
            log("ICE", "Handshake FAILED: check STUN server, firewalls, or UDP ports.")

    # 1. Start the MJPEG reader and wait for the first decoded frame.
    reader = MJPEGReader(CRAZYFLIE_STREAM_URL)
    reader.start()
    first = None
    for _ in range(100):  # up to 10 s for the drone/proxy to deliver a frame
        _, first = reader.read()
        if first is not None:
            break
        await asyncio.sleep(0.1)
    if first is None:
        log("INIT", f"ERROR: no frame from {CRAZYFLIE_STREAM_URL} within 10 s. "
                    "Is start_bridge.sh (video_stream_proxy.py) running?")
        reader.stop()
        return

    h, w = first.shape[:2]
    log("INIT", f"Crazyflie video: {w}x{h} (first frame received)")
    video_track = CrazyflieStreamTrack(reader)
    pc.addTrack(video_track)

    # 2. No audio: the drone's ESP32 camera is video-only.

    # 3. WebRTC Offer & ICE Gathering
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    log("ICE", f"Gathering ICE candidates (state: {pc.iceGatheringState})...")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)
    ours = describe_sdp_candidates(pc.localDescription.sdp)
    log("ICE", f"ICE gathering complete. Candidates: {', '.join(ours) if ours else 'none'}")

    # 4. WHIP Handshake over HTTPS/Caddy
    async with aiohttp.ClientSession() as session:
        log("WHIP", f"POSTing SDP offer to {whip_endpoint} ...")
        try:
            async with session.post(
                whip_endpoint,
                data=pc.localDescription.sdp,
                headers={"Content-Type": "application/sdp"}
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    log("WHIP", f"Handshake FAILED: HTTP {resp.status} from {whip_endpoint}")
                    log("WHIP", f"Error details: {text.strip()[:500]}")
                    reader.stop()
                    return
                sdp_answer = await resp.text()
                log("WHIP", f"Handshake SUCCEEDED: HTTP {resp.status}, SDP answer received.")
        except Exception as e:
            log("WHIP", f"Handshake FAILED: could not reach {whip_endpoint} ({e})")
            reader.stop()
            return

    theirs = describe_sdp_candidates(sdp_answer)
    log("WHIP", f"MediaMTX ICE candidates: {', '.join(theirs) if theirs else 'none in SDP'}")

    answer = RTCSessionDescription(sdp=sdp_answer, type="answer")
    await pc.setRemoteDescription(answer)

    log("LIVE", f"STREAM LIVE. Stream ID: '{stream_id}' — viewers watch via "
                f"WHEP at {server_url}/{stream_id}/whep")

    monitor_task = asyncio.create_task(monitor(pc, MEDIAMTX_API_URL, path_name))

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        monitor_task.cancel()
        await pc.close()
        reader.stop()
        log("CLEANUP", "MJPEG reader stopped.")
        log("LIVE", "Stream shutdown complete.")


if __name__ == "__main__":
    asyncio.run(run_whip_publisher(MEDIAMTX_BASE_URL, LIVESTREAM_HOSTNAME))

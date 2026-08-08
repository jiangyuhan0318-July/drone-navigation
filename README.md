# Drone Navigation

[English](README.md) | [中文](README-zh.md)

> 📘 **Detailed setup guides** → [Windows/WSL](README-setup.md) · [macOS](README-macos.md) · [Ubuntu](README-ubuntu.md) · [Production](deployment/README.md)

A full-stack drone navigation and control platform combining 3D aerial visualization, real-time telemetry, AI-powered gesture/pose/fall/action recognition, and natural-language copilot control — all from a single browser dashboard.

## Overview

Drone Navigation is an integrated system for remotely piloting and monitoring Crazyflie drones. It provides:

- **3D & 2D Visualization** — Cesium globe for 3D aerial views, Google Maps for 2D navigation, and street-level imagery
- **AI Vision Guard Center** — Real-time gesture, posture, fall, and body-action recognition via webcam, with automatic drone command execution
- **Natural Language Copilot** — OpenClaw-powered AI assistant that controls the drone and guard center via chat
- **Live Video Streaming** — WHIP/WHEP-based low-latency video from drone camera or local webcam via MediaMTX
- **Community Chat** — Matrix-based real-time messaging between pilots
- **Customer Service Bot** — OpenClaw-powered intelligent customer support

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (http://localhost:5173)                                 │
│  Vue 3 + Vite + Cesium + Google Maps                             │
│  3D Aerial │ 2D Map │ Real Drone │ Chat │ Settings │ Copilot    │
└──────┬───────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  FastAPI Backend (:8000)                                         │
│  Auth │ Telemetry │ Drone Commands │ Settings │ Copilot API      │
│  Safety Gate │ Matrix Token Brokering │ Stream Config            │
└──────┬───────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  Extension Layer                                                 │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ Crazyflie Bridge │  │ Guard Center (:8705)                 │   │
│  │ • Motion Control │  │ • Gesture Recognition (👍✌️🖐✊☝️👎🤟👌) │   │
│  │ • Telemetry Relay│  │ • Posture Guardian (head lean)      │   │
│  │ • Video Proxy    │  │ • Fall Detection (state machine)    │   │
│  │ • MediaMTX WHIP  │  │ • Body Action (T-pose, cross, up)   │   │
│  └─────────────────┘  │ • Unified Executor → Drone Actions   │   │
│                        └──────────────────────────────────────┘   │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ Simple Webcam   │  │ Models                              │   │
│  │ WHIP Publisher  │  │ • YOLOv8n (object detection)         │   │
│  └─────────────────┘  │ • MediaPipe Pose/Face/Gesture        │   │
│                        └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  Infrastructure                                                  │
│  PostgreSQL │ Synapse (Matrix) │ MediaMTX │ OpenClaw │ Caddy     │
└──────────────────────────────────────────────────────────────────┘
```

## Key Features

### 🛸 Drone Control
- Takeoff, land, emergency stop, hover, and directional flight
- Real-time telemetry: position, attitude, battery, link quality
- Waypoint-based flight planning with altitude gates
- Gimbal control and aerial photography
- Multi-drone provisioning with distinct radio channels

### 🤖 AI Vision Guard Center (v2)
**One process, one port (:8705), one webcam** — switch between four detection modes on the fly:

| Mode | Detects | Drone Action |
|------|---------|-------------|
| ✋ **Gesture** | Thumb_Up / Victory / Open_Palm / Closed_Fist / Pointing_Up / Thumb_Down / ILoveYou / OK | Takeoff / Land / E-Stop / Hover / Directional flight |
| 🪑 **Posture** | Head lean ≥16° for 2s | Auto-takeoff 0.5m |
| 🧍 **Fall** | Fall confirmed via state machine | Auto-takeoff 0.5m |
| 🙌 **Body Action** | Hands up / Arms crossed / T-pose | E-Stop / Land / Attitude control mode |

- **Web dashboard** at `http://127.0.0.1:8705/` — live MJPEG video + mode buttons + status panels
- **Dry-run mode** for safe testing; `--live` flag for real drone commands
- Safety gates: takeoff requires flight gate clearance + battery ≥ 3.5V

### 💬 AI Copilot (OpenClaw)
Natural language control of the entire system:
- "Switch to gesture mode" / "Check drone status" / "Take off 0.5 meters"
- Skills: guard-center, body-action-control, gesture-control, posture-guardian, fall-guardian
- Integrated with the FastAPI copilot endpoint for full command chain

### 🌍 Visualization
- **3D Aerial View** — Cesium globe with custom tilesets, altitude visualization, collision warnings
- **2D Map View** — Google Maps with waypoint picking, flight path planning
- **Street View** — Ground-level perspective integration

### 🔴 Live Streaming
- Low-latency video via MediaMTX (WHIP/WHEP/WebRTC)
- Drone camera or local webcam as video source
- Livestream viewer and host HUD with overlay

## Project Structure

```
drone-navigation/
├── client/                    # Vue 3 + Vite frontend
│   ├── src/
│   │   ├── views/             # Page components (Aerial, Map, Chat, Settings, etc.)
│   │   ├── 2d_map/            # Google Maps integration
│   │   ├── 3d_street/         # Street View integration
│   │   └── router/            # SPA routing
│   ├── composables/           # Vue composables (telemetry, auth, matrix, etc.)
│   ├── components/            # Reusable UI components (HUD, Dock, Disk, etc.)
│   └── icons/                 # SVG icon library
├── server/                    # FastAPI backend
│   ├── app/
│   │   ├── main.py            # FastAPI application entry
│   │   ├── drone_commands.py  # Drone command dispatch + safety gate
│   │   ├── telemetry.py       # Telemetry WebSocket relay
│   │   ├── copilot.py         # Copilot API endpoint
│   │   ├── safety.py          # Flight safety rules
│   │   ├── users.py           # User management (fastapi-users)
│   │   ├── matrix_auth.py     # Matrix token brokering
│   │   └── settings.py        # User settings API
│   └── migrations/            # PostgreSQL schema migrations
├── extension/                 # Standalone drone + vision services
│   ├── guard_center.py        # Guard center: 4-in-1 AI detection + dashboard
│   ├── guard_control.py       # Unified executor: detection → drone commands
│   ├── gesture_recognizer.py  # Hand gesture recognition (MediaPipe)
│   ├── posture_guardian.py    # Sitting posture monitoring
│   ├── fall_recognizer.py     # Fall detection state machine
│   ├── action_recognizer.py   # Body action recognition (T-pose, etc.)
│   ├── crazyflie_bridge/      # Crazyflie drone bridge
│   │   ├── motion_control_ws.py    # WebSocket motion control
│   │   ├── telemetry_relay.py      # Telemetry forwarding
│   │   ├── video_stream_proxy.py   # Camera stream proxy
│   │   └── provision_drone.py      # EEPROM provisioning tool
│   ├── simple_crazyflie/      # Step-by-step Crazyflie tutorials
│   ├── simple_webcam/         # WHIP webcam publisher (Windows)
│   ├── models/                # AI models (MediaPipe tasks, YOLOv8)
│   └── copilot/               # OpenClaw skill definitions
├── deployment/                # Production deployment configs
│   ├── caddy/                 # Caddy reverse proxy
│   ├── fastapi/               # Systemd service for backend
│   ├── mediamtx/              # MediaMTX configuration
│   ├── synapse/               # Matrix Synapse service
│   ├── squid/                 # Squid proxy config
│   └── openclaw/              # OpenClaw gateway config
└── docs/                      # Platform-specific READMEs
    ├── README.md              # Windows/WSL setup (English)
    ├── README-zh.md           # Windows/WSL setup (中文)
    ├── README-macos.md        # macOS setup (English)
    ├── README-macos-zh.md     # macOS setup (中文)
    ├── README-ubuntu.md       # Ubuntu setup (English)
    └── README-ubuntu-zh.md    # Ubuntu setup (中文)
```

## Quick Start

### Prerequisites

- **Windows 10/11** with WSL2 Ubuntu (recommended) — or macOS / Ubuntu natively
- **Python 3.12+**, **Node.js LTS**, **PostgreSQL**, **Conda**
- **Crazyflie drone** with Crazyradio PA (optional — simulation mode available)

### 1. Clone & Install

```bash
git clone https://github.com/kandeng/drone-navigation.git
cd drone-navigation

# Backend
cd server
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install -r requirements.txt
cp config.example.json config.json  # Edit with your values

# Frontend
cd ../client
npm install
cp config.example.json config.json  # Add googleApiKey, cesiumIonToken
```

### 2. Start Services

```bash
# Terminal 1: PostgreSQL
pg_ctl -D ~/pgdata -l ~/pgdata.log start

# Terminal 2: Backend
cd server && uvicorn app.main:app --reload --port 8000

# Terminal 3: Frontend (dev)
cd client && npm run dev

# Optional: MediaMTX for video streaming
./mediamtx

# Optional: Guard Center for AI vision control
cd extension && bash start_guard.sh --mode=gesture --live
```

### 3. Open in Browser

Navigate to `http://localhost:5173` — the 3D globe loads immediately. Register an account, configure your drone, and start flying.

## AI Models

Pre-packaged models (included in `extension/`):

| Model | File | Size | Purpose |
|-------|------|------|---------|
| YOLOv8n | `yolov8n.pt` | 6.5 MB | Object detection |
| MediaPipe Pose | `pose_landmarker_lite.task` | 5.8 MB | Body pose estimation |
| MediaPipe Face | `face_landmarker.task` | 3.8 MB | Face mesh detection |
| MediaPipe Gesture | `gesture_recognizer.task` | 8.4 MB | Hand gesture recognition |

## Platform Support

| Platform | Setup Guide |
|----------|------------|
| Windows 10/11 (WSL2) | [README-setup.md](README-setup.md) · [中文](README-setup-zh.md) |
| macOS | [README-macos.md](README-macos.md) · [中文](README-macos-zh.md) |
| Ubuntu | [README-ubuntu.md](README-ubuntu.md) · [中文](README-ubuntu-zh.md) |
| Production (Alibaba ECS) | [deployment/README.md](deployment/README.md) |

## Community & Copilot

- **Matrix Chat**: Built-in community messaging via Synapse homeserver
- **Customer Service**: OpenClaw-powered AI support bot
- **Flight Copilot**: AI copilot for natural-language drone control with safety guardrails

## Safety

- Takeoff refused when drone is on USB cable (radio only)
- Emergency stop (`estop`) always available, bypasses all gates
- Battery floor at 3.5V for takeoff commands
- Multiple drones: provision distinct radio channels ≥2 MHz apart
- Dry-run mode (`CF_NO_FLY=1`) for bench testing — refuses all takeoffs
- Config/token values never logged or printed to terminal

## License

See [LICENSE](LICENSE) for the full End-User License Agreement.

# Drone Navigation — macOS

A multi-view drone navigation dashboard combining 3D aerial visualization, 2D mapping, and mission-control interfaces.

This guide runs the **entire system natively on macOS** (Apple Silicon and Intel) — no server accounts, no VM. Other platforms and languages:

- Windows 10/11 (WSL2): [English](README.md) | [中文](README-zh.md)
- macOS: [English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu: [English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- Production deployment (Alibaba ECS, Caddy, Tailscale): [deployment/README.md](deployment/README.md)

macOS is actually the smoothest path: everything runs natively (no WSL layer, no USB pass-through), including the webcam publisher and the Crazyradio. The only macOS-specific notes are Homebrew paths, camera permission prompts, and `libusb` for the radio.

## Project structure

```
drone-navigation/
├── client/       # Vue 3 + Vite frontend (Cesium, Google Maps, Street View)
├── server/       # FastAPI backend (fastapi-users auth, settings, Matrix token brokering)
├── extension/    # Standalone publishers/tools (simple_webcam WHIP ingest, crazyflie_bridge)
└── deployment/   # Production configs + ops docs (Caddy, Squid, OpenClaw, MediaMTX, Synapse)
```

| Component | Port(s) |
|---|---|
| Client (Vite dev server) | 5173 |
| FastAPI backend | 8000 |
| PostgreSQL dev cluster | 5433 |
| Synapse (Community chat) | 8008 |
| OpenClaw (Customer Service) | 18789 |
| MediaMTX (Livestream) | 8889, 8888, 9997 |
| crazyflie_bridge (real drone) | 8082, 8765 |

## Section 1. macOS setup

```bash
xcode-select --install            # Command Line Tools (git, compilers)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git node postgresql@14 libusb
# libusb: needed by pyusb/cflib to talk to the Crazyradio — there is no
# usbipd equivalent on macOS; USB works natively.

# Miniconda (installer route — keeps shells consistent with the Linux guides)
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh   # Intel: ...-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init zsh && source ~/.zshrc

git clone https://github.com/kandeng/drone-navigation.git ~/drone-navigation
```

Checkpoint: `node -v`, `npm -v`, `conda --version`, `git --version` all print versions.

## Section 2. Client (Vue 3 + Vite)

```bash
cd ~/drone-navigation/client
npm install
cp config.example.json config.json   # fill in googleApiKey, cesiumIonToken, openclaw.token
npm run dev                          # http://localhost:5173
```

For API key prerequisites (Google Maps APIs, Cesium ion), see [client/README.md](client/README.md).

**Smoke test:** the `3D Aerial` globe and the `2D Map` render immediately — they need no backend.

## Section 3. PostgreSQL (user-owned dev cluster, port 5433)

Do **not** use `brew services` here — we run a throwaway user cluster like the Linux guides (paths below are Apple Silicon; on Intel replace `/opt/homebrew` with `/usr/local`):

```bash
# One-time init (trust auth on localhost, port 5433)
/opt/homebrew/opt/postgresql@14/bin/initdb -D ~/pgdata -U $USER -E UTF8 --auth=trust
printf "port = 5433\nunix_socket_directories = '$HOME/pgdata'\n" >> ~/pgdata/postgresql.conf

# Start / stop
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata stop

# Populate the schema (idempotent; run 002 after 001)
psql -h 127.0.0.1 -p 5433 -U $USER -v ON_ERROR_STOP=1 \
     -v app_password='local-dev-drone-api' \
     -f ~/drone-navigation/server/migrations/001_init_auth_schema.sql
psql -h 127.0.0.1 -p 5433 -U $USER -d drone_navigation \
     -v ON_ERROR_STOP=1 -f ~/drone-navigation/server/migrations/002_matrix_account.sql
```

(`psql` is at `/opt/homebrew/opt/postgresql@14/bin/psql` — add it to PATH or use the full path.)

## Section 4. FastAPI backend (auth + settings + Matrix brokering)

```bash
cd ~/drone-navigation/server
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install -r requirements.txt
cp config.example.json config.json   # local values: database_url → ...@127.0.0.1:5433/...,
                                     # frontend_base_url → http://localhost:5173,
                                     # cors_origins → ["http://localhost:5173"]
uvicorn app.main:app --reload --port 8000
```

Note: `--reload` watches only `.py` files — after editing `config.json`, `touch app/main.py` to force a reload.

**Smoke test:** `curl http://localhost:8000/api/health` → `{"status":"ok"}`; then `My Space -> Account` register + sign in, and a Settings save shows the green banner.

## Section 5. Synapse (Community chat)

Runs on `127.0.0.1:8008` with public registration disabled — the website is the only entrance:

```bash
python3 -m venv ~/synapse-venv   # or: conda create -n synapse python=3.12
~/synapse-venv/bin/pip install matrix-synapse==1.157.1
~/synapse-venv/bin/python -m synapse.app.homeserver \
  --server-name localhost --config-path ~/synapse-data/homeserver.yaml \
  --generate-config --report-stats=no
# Edit ~/synapse-data/homeserver.yaml: keep the 127.0.0.1:8008 listener
# (client+admin resources), verify `enable_registration: false`

# Start (background)
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver \
  -c ~/synapse-data/homeserver.yaml &

# Service admin + token for the backend's token brokering
~/synapse-venv/bin/register_new_matrix_user \
  -c ~/synapse-data/homeserver.yaml -u admin -p '<pick-a-password>' --admin \
  http://localhost:8008
curl -s -X POST localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"admin","password":"<same-password>"}'
# Add to server/config.json, then `touch app/main.py`:
#   "synapse": { "base_url": "http://127.0.0.1:8008",
#                "server_name": "localhost",
#                "admin_access_token": "<syt_... token>" }
```

**Smoke test:** with two accounts in two browser profiles, `Community -> Chat` DMs flow both ways and survive a reload.

## Section 6. OpenClaw (Customer Service)

```bash
npm install -g openclaw          # or: pnpm add -g openclaw
# Configure model provider + gateway token in ~/.openclaw/openclaw.json
# (see deployment/openclaw/openclaw.json for the reference shape)
openclaw gateway --port 18789    # foreground; `openclaw gateway install` for a daemon
```

The SPA connects to `ws://127.0.0.1:18789` — `openclaw.token` in `client/config.json` must match the gateway token in `~/.openclaw/openclaw.json`.

## Section 7. MediaMTX + webcam (both native)

**MediaMTX** (binary tarball keeps the config file next to it; `brew install mediamtx` also works):

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
# Apple Silicon: darwin_arm64; Intel: darwin_amd64
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_darwin_arm64.tar.gz
tar -xzf mediamtx_v1.9.0_darwin_arm64.tar.gz
# Recommended: enable the control API on loopback — in mediamtx.yml set
#   api: yes  and  apiAddress: 127.0.0.1:9997
./mediamtx                       # WHEP/WHIP on :8889, HLS :8888, control API :9997
# If Gatekeeper blocks the binary: xattr -d com.apple.quarantine ./mediamtx
```

**Webcam publisher** (native — unlike WSL, the camera works directly):

```bash
cd ~/drone-navigation/extension/simple_webcam
conda activate drone-navigation   # requirements already installed in Section 4
MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 \
  LIVESTREAM_ID=crazyflie-drone python simple_webcam.py
```

On first run macOS asks to grant **camera access to your terminal** (System Settings -> Privacy & Security -> Camera — enable Terminal/iTerm/VS Code, then restart the terminal). The stream publishes as `crazyflie-drone`, standing in for the real drone.

Which stream the SPA plays is decided by the backend at runtime (`server/config.json` -> `"mediamtx": { "streams": [...] }`, served at `GET /api/stream/config`); when the key is absent the SPA falls back to `http://127.0.0.1:8889/<id>/whep` locally.

**Smoke test:** `Real Drone -> Livestream Viewer` plays the webcam; the green `crazyflie-drone - HH:MM:SS` overlay ticks.

## Section 8. Whole-system smoke test

```bash
curl http://localhost:8000/api/health              # {"status":"ok"}
curl http://localhost:5173/_matrix/client/versions # via the Vite proxy
```

Browser checklist at `http://localhost:5173`:

1. `My Space -> Account`: register + sign in.
2. `My Space -> Settings`: change a value, click `Save` → green "saved" banner.
3. `Community -> Chat`: two accounts exchange DMs; reload → history persists.
4. `Community -> Customer Service`: connects to the local OpenClaw gateway.
5. `Real Drone -> Livestream Viewer` (and `Host`): plays the Section 7 broadcast.

## Section 9. Real Crazyflie drone

**New to the Crazyflie?** Start with [`extension/simple_crazyflie/README.md`](extension/simple_crazyflie/README.md) — it walks you through connecting your computer to the drone, reading its telemetry, and then flying it, one step at a time.

No USB pass-through needed — plug the **Crazyradio PA** in and it just works (`libusb` from Section 1 provides the userspace driver; no udev rules, no sudo):

```bash
system_profiler SPUSBDataType | grep -A3 1915   # Crazyradio PA present
```

Find the drone's camera IP (`nmap -sn 192.168.0.0/24`, or browse `http://192.168.0.x` candidates) until one shows the AI-Deck livestream.

**Changing the drone's EEPROM identity** (only needed when several drones share one room — same channel + same address = cross-control): connect the drone over the USB cable and run the provisioning script — it writes the new radio channel/address into the drone's EEPROM, then verifies it over the radio after a power-cycle:

```bash
cd ~/drone-navigation/extension/crazyflie_bridge
python provision_drone.py --channel 14 --address E7E7E7E707
# -> then connect with: ./start_bridge.sh --cf-uri radio://0/14/2M/E7E7E7E707
```

Give each drone a distinct channel, ≥2 MHz apart at 2M datarate (e.g. channels 2, 4, 6, ... with matching addresses `E7E7E7E702`, `E7E7E7E703`, ...). `--team N` applies that scheme automatically; `--read-only` just prints the current identity.

Start the whole bridge with one script (it self-activates the `drone-navigation` conda env):

```bash
cd ~/drone-navigation/extension/crazyflie_bridge
CRAZYFLIE_IP="192.168.0.110" RADIO_URL="radio://0/80/2M/E7E7E7E7E7" \
TELEMETRY_SERVER="ws://127.0.0.1:8000/api/drone/telemetry/publish" \
MEDIAMTX_URL="http://127.0.0.1:8889" MEDIAMTX_API="http://127.0.0.1:9997" \
  ./start_bridge.sh
#    = video_stream_proxy.py  (re-broadcasts http://$CRAZYFLIE_IP/stream on :8082)
#    + motion_control_ws.py   (ws://:8765; set RADIO_URL env var, or pass
#      --cf-uri to the script, to change the radio identity)
#    + telemetry_relay.py     (telemetry + flight commands, drone <-> FastAPI)
#    + crazyflie_mediamtx.py  (drone camera -> MediaMTX WHIP, id 'crazyflie-drone')
#    Stop: Ctrl+C (press twice to force) — lands the drone first if flying.
#    Bench safety: CF_NO_FLY=1 refuses every takeoff (dry-run).
```

**Smoke test (no flight):** `python e2e_command_check.py` validates the full command chain. Then the `Livestream Host` HUD shows `Link live | ~20 Hz` with real position / attitude / battery, and the Takeoff/Stop/Landing button + Flight disk fly the drone.

Safety rules that are always in effect:

- Takeoff is **refused on a USB cable** (`usb://*`); flight goes over the Crazyradio only.
- **Multiple drones in one room:** the default URI is for SOLO use — provision each drone with its own channel/address (steps above) and fly only on it.

## Section 10. Daily workflow + troubleshooting

Start order each session (one terminal tab each):

```bash
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
cd ~/drone-navigation/server && conda activate drone-navigation && uvicorn app.main:app --reload --port 8000
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml &
openclaw gateway --port 18789
~/mediamtx_v1.9.0/mediamtx
cd ~/drone-navigation/extension/simple_webcam && MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 LIVESTREAM_ID=crazyflie-drone python simple_webcam.py
cd ~/drone-navigation/client && npm run dev
# Real drone: Section 9
```

Stop: Ctrl+C each process; `pg_ctl -D ~/pgdata stop` for PostgreSQL.

- **Camera black / `cv2.VideoCapture(0)` fails:** camera permission missing for your terminal (Section 7), or another app (Zoom/FaceTime/Photo Booth) holds the camera.
- **`psql: command not found`:** use the full `/opt/homebrew/opt/postgresql@14/bin/` path or add it to PATH (`brew link --force postgresql@14`).
- **Apple Silicon vs Intel paths:** Homebrew prefixes are `/opt/homebrew` (M-series) and `/usr/local` (Intel) — substitute throughout.
- **Port already in use:** `lsof -i :<port>` to find the holder; AirPlay Receiver occupies 5000/7000 on some macOS versions but none of this stack's ports.

## License

See [LICENSE](LICENSE) for the full End-User License Agreement.

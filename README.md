# Drone Navigation

A multi-view drone navigation dashboard combining 3D aerial visualization, 2D mapping, and mission-control interfaces.

This guide runs the **entire system locally on Windows 10/11 with WSL2** — no server accounts needed. Other platforms and languages:

- Windows 10/11 (WSL2): [English](README.md) | [中文](README-zh.md)
- macOS: [English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu: [English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- Production deployment (Alibaba ECS, Caddy, Tailscale): [deployment/README.md](deployment/README.md)

## Project structure

```
drone-navigation/
├── client/       # Vue 3 + Vite frontend (Cesium, Google Maps, Street View)
├── server/       # FastAPI backend (fastapi-users auth, settings, Matrix token brokering)
├── extension/    # Standalone publishers/tools (simple_webcam WHIP ingest, crazyflie_bridge)
└── deployment/   # Production configs + ops docs (Caddy, Squid, OpenClaw, MediaMTX, Synapse)
```

## How it works on Windows (read this first)

Everything server-side runs **inside WSL2 Ubuntu**; you interact with it from Windows through WSL2's localhost forwarding — a service listening on a port inside WSL is reachable from Windows at `http://localhost:<port>`.

Two pieces are the exception:

- **The webcam publisher runs on native Windows Python.** WSL2 has no access to the laptop camera (there is no `/dev/video0`), so `simple_webcam.py` runs in Windows and pushes the stream *into* MediaMTX inside WSL via `127.0.0.1:8889` (the Windows→WSL direction of localhost forwarding).
- **The Crazyradio PA dongle needs usbipd-win** to pass the USB device into WSL (Section 9).

| Component | Runs in | Port(s) |
|---|---|---|
| Client (Vite dev server) | WSL | 5173 |
| FastAPI backend | WSL | 8000 |
| PostgreSQL dev cluster | WSL | 5433 |
| Synapse (Community chat) | WSL | 8008 |
| OpenClaw (Customer Service) | WSL | 18789 |
| MediaMTX (Livestream) | WSL | 8889, 8888, 9997 |
| simple_webcam publisher | **Windows** | — |
| crazyflie_bridge (real drone) | WSL (+ usbipd radio) | 8082, 8765 |

## Section 1. Windows + WSL2 setup

In **Windows PowerShell (Administrator)**:

```powershell
wsl --install                  # installs WSL2 + Ubuntu; reboot when asked
wsl --set-default-version 2
```

Then in the **Ubuntu (WSL) terminal**:

```bash
sudo apt update && sudo apt install -y git curl

# Miniconda
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init bash && source ~/.bashrc

# Node.js LTS
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs

# Clone into the WSL HOME — never under /mnt/c
# (npm install on the Windows filesystem is 10-50x slower)
git clone https://github.com/kandeng/drone-navigation.git ~/drone-navigation
```

Checkpoint: `node -v`, `npm -v`, `conda --version`, `git --version` all print versions.

## Section 2. Client (Vue 3 + Vite)

```bash
cd ~/drone-navigation/client
npm install
cp config.example.json config.json   # fill in googleApiKey, cesiumIonToken, openclaw.token
npm run dev
```

Open `http://localhost:5173` in your **Windows** browser (WSL forwards it). For API key prerequisites (Google Maps APIs, Cesium ion), see [client/README.md](client/README.md).

**Smoke test:** the `3D Aerial` globe and the `2D Map` render immediately — they need no backend. Most other pages come alive as you add the sections below.

## Section 3. PostgreSQL (dev cluster in WSL, port 5433)

A user-owned cluster, no systemd needed (WSL's apt also installs its own cluster on port 5432 — ignore it; we never touch it):

```bash
sudo apt install -y postgresql
VER=$(ls /usr/lib/postgresql)        # 14 on Ubuntu 22.04, 16 on 24.04

# One-time init (trust auth on localhost, port 5433)
/usr/lib/postgresql/$VER/bin/initdb -D ~/pgdata -U $USER -E UTF8 --auth=trust
printf "port = 5433\nunix_socket_directories = '$HOME/pgdata'\n" >> ~/pgdata/postgresql.conf

# Start / stop
/usr/lib/postgresql/$VER/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
/usr/lib/postgresql/$VER/bin/pg_ctl -D ~/pgdata stop

# Populate the schema (idempotent; run 002 after 001)
psql -h 127.0.0.1 -p 5433 -U $USER -v ON_ERROR_STOP=1 \
     -v app_password='local-dev-drone-api' \
     -f ~/drone-navigation/server/migrations/001_init_auth_schema.sql
psql -h 127.0.0.1 -p 5433 -U $USER -d drone_navigation \
     -v ON_ERROR_STOP=1 -f ~/drone-navigation/server/migrations/002_matrix_account.sql
```

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

**Smoke test:** `curl http://localhost:8000/api/health` → `{"status":"ok"}` — run it **in Windows PowerShell too**; it proves WSL→Windows forwarding works. Then in the browser: `My Space -> Account`, register + sign in; `My Space -> Settings`, change a value, `Save` → green banner.

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

## Section 7. MediaMTX (WSL) + webcam (native Windows)

**MediaMTX — inside WSL:**

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.9.0_linux_amd64.tar.gz
# Recommended: enable the control API on loopback — in mediamtx.yml set
#   api: yes  and  apiAddress: 127.0.0.1:9997
./mediamtx                       # WHEP/WHIP on :8889, HLS :8888, control API :9997
```

**Webcam publisher — on native Windows** (WSL2 has no camera device):

1. Install **Python 3.12 for Windows** from python.org (tick "Add python.exe to PATH").
2. Copy the publisher out of the WSL filesystem (replace `<wsl-user>` with your WSL username), in **Windows PowerShell**:

```powershell
Copy-Item -Recurse \\wsl.localhost\Ubuntu\home\<wsl-user>\drone-navigation\extension\simple_webcam $HOME\simple_webcam
cd $HOME\simple_webcam
py -m pip install -r requirements.txt    # opencv-python, aiortc, av, aiohttp (all have Windows wheels)

$env:MEDIAMTX_URL="http://127.0.0.1:8889"
$env:MEDIAMTX_API="http://127.0.0.1:9997"
$env:LIVESTREAM_ID="crazyflie-drone"     # stand in for the drone stream
py simple_webcam.py
```

`127.0.0.1:8889` from Windows reaches MediaMTX inside WSL via localhost forwarding. Allow Windows Defender Firewall's Python prompt if asked, and make sure Windows camera privacy settings allow desktop apps to use the camera.

Which stream the SPA plays is decided by the backend at runtime (`server/config.json` -> `"mediamtx": { "streams": [...] }`, served at `GET /api/stream/config`); when the key is absent the SPA falls back to `http://127.0.0.1:8889/<id>/whep` locally. The `Livestream Viewer` subpage lists every catalog entry as a clickable card (default: the first entry, `crazyflie-drone`).

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

## Section 9. Real Crazyflie drone (usbipd-win + crazyflie_bridge)

**New to the Crazyflie?** Start with [`extension/simple_crazyflie/README.md`](extension/simple_crazyflie/README.md) — it walks you through connecting your computer to the drone, reading its telemetry, and then flying it, one step at a time.

WSL2 cannot see USB devices by default. Pass the **Crazyradio PA** into WSL with usbipd-win — in **Windows PowerShell (Administrator)**:

```powershell
winget install usbipd
usbipd list                          # find the Crazyradio PA (Nordic, VID 1915 PID 7777) -> note BUSID
usbipd bind --busid <BUSID>          # one-time, persists across reboots
usbipd attach --wsl --busid <BUSID>  # repeat after each replug / WSL restart
```

In **WSL**, grant user access (one-time), then verify:

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-crazyradio.rules
sudo udevadm control --reload && sudo udevadm trigger
lsusb | grep 1915        # Nordic Semiconductor — the dongle is visible
# If WSL has no udev running (no systemd): sudo chmod 0666 /dev/bus/usb/<bus>/<dev>
# (find <bus>/<dev> via lsusb)
```

Find the drone's camera IP: browse `http://192.168.0.x` candidates from a Windows browser (`nmap -sn 192.168.0.0/24` inside WSL lists them) until one shows the AI-Deck livestream — WSL can reach it directly (outbound LAN works).

**Changing the drone's EEPROM identity** (only needed when several drones share one room — same channel + same address = cross-control): connect the drone over its USB cable, attach it to WSL with usbipd the same way as the radio, then run the provisioning script — it writes the new radio channel/address into the drone's EEPROM, then verifies it over the radio after a power-cycle:

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

- Takeoff is **refused on a USB cable** (`usb://*`); flight goes over the Crazyradio only. (Using `usb://0` in WSL also requires attaching the drone's USB cable via usbipd.)
- **Multiple drones in one room:** the default URI is for SOLO use — provision each drone with its own channel/address (steps above) and fly only on it.

## Section 10. Daily workflow + troubleshooting

Start order each session (one WSL terminal tab each, except the webcam in Windows PowerShell):

```bash
/usr/lib/postgresql/$(ls /usr/lib/postgresql)/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
cd ~/drone-navigation/server && conda activate drone-navigation && uvicorn app.main:app --reload --port 8000
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml &
openclaw gateway --port 18789
~/mediamtx_v1.9.0/mediamtx
cd ~/drone-navigation/client && npm run dev
# Windows PowerShell: cd $HOME\simple_webcam; $env:MEDIAMTX_URL=...; py simple_webcam.py
# Real drone: Section 9 (usbipd attach first)
```

Stop: Ctrl+C each process; `pg_ctl -D ~/pgdata stop` for PostgreSQL.

- **`localhost:<port>` unreachable from Windows:** confirm the process is actually listening inside WSL (`ss -tlnp | grep <port>`); `wsl --shutdown` in PowerShell resets a wedged network.
- **Firewall prompts:** allow Python/MediaMTX when Windows Defender asks (private networks).
- **Slow `npm install` / file ops:** you are in `/mnt/c/...` — move the repo to the WSL home (Section 1).
- **Camera black on the Windows publisher:** Windows Settings -> Privacy & security -> Camera -> allow desktop apps; only ONE app can hold the camera — close Teams/Zoom/Camera app.
- **Editing WSL files from Windows:** use `\\wsl.localhost\Ubuntu\home\<wsl-user>\...` (VS Code's WSL extension is the comfortable option).

## License

See [LICENSE](LICENSE) for the full End-User License Agreement.

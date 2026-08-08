# Drone Navigation — Ubuntu

A multi-view drone navigation dashboard combining 3D aerial visualization, 2D mapping, and mission-control interfaces.

This guide runs the **entire system locally on a native Ubuntu desktop** — no ECS dependency. In dev, the SPA calls FastAPI cross-origin at `http://localhost:8000` and reaches Synapse through the Vite `/_matrix` proxy — **no Caddy needed locally** (Caddy, Squid, and Tailscale are production-only). Other platforms and languages:

- Windows 10/11 (WSL2): [English](README.md) | [中文](README-zh.md)
- macOS: [English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu: [English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- Production deployment (Alibaba ECS, Caddy, Tailscale): [deployment/README.md](deployment/README.md)

Everything runs natively. Ubuntu is also the only platform with optional systemd user services (Section 11) that run the whole stack in the background, no terminals.

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

## Section 1. Ubuntu setup

```bash
sudo apt update && sudo apt install -y git curl postgresql nmap

# Miniconda
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init bash && source ~/.bashrc

# Node.js LTS
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs

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

No sudo, separate from any system cluster (details: deployment/README.md §3.3.3):

```bash
VER=$(ls /usr/lib/postgresql)        # 14 on Ubuntu 22.04

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

**Smoke test:** `curl http://localhost:8000/api/health` → `{"status":"ok"}`; then `My Space -> Account` register + sign in, and a Settings save shows the green banner.

## Section 5. Synapse (Community chat)

Runs on `127.0.0.1:8008` with public registration disabled — the website is the only entrance (a conda env works equally well as the venv shown):

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

**MediaMTX** (v1.9.0, same as ECS 2):

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.9.0_linux_amd64.tar.gz
# Recommended: enable the control API on loopback — in mediamtx.yml set
#   api: yes  and  apiAddress: 127.0.0.1:9997
./mediamtx                   # WHEP/WHIP on :8889, HLS :8888, control API :9997
```

**Webcam publisher** (separate terminal):

```bash
cd ~/drone-navigation/extension/simple_webcam
conda activate drone-navigation
MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 \
  LIVESTREAM_ID=crazyflie-drone python simple_webcam.py   # WHIP-ingests the 'crazyflie-drone' stream
```

With a real Crazyflie drone, `extension/crazyflie_bridge/crazyflie_mediamtx.py` publishes its camera under the same `crazyflie-drone` id instead of the webcam (Section 9).

Which stream the SPA plays is decided by the backend at runtime (`server/config.json` -> `"mediamtx": { "streams": [...] }`, served at `GET /api/stream/config`); when the key is absent the SPA falls back to `http://127.0.0.1:8889/<id>/whep` locally (production: `https://drone-navigation.com/live/<id>/whep`). The `Livestream Viewer` subpage lists every catalog entry as a clickable card (default: the first entry, `crazyflie-drone`); the publishers default to production — the `MEDIAMTX_URL` / `MEDIAMTX_API` env vars above point them at the local server.

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

Everything is native here — the only preparation is a one-time udev rule granting user access to the Crazyradio PA, and to the drone itself over USB (used for classroom provisioning):

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="5740", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-crazyflie.rules
sudo udevadm control --reload && sudo udevadm trigger
lsusb | grep 1915        # Nordic Semiconductor — the Crazyradio is visible
```

Find the drone's camera IP (`nmap -sn 192.168.0.0/24`, then browse `http://192.168.0.x` candidates) until one shows the AI-Deck livestream.

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
#    Omit TELEMETRY_SERVER / MEDIAMTX_* / RADIO_URL to relay + publish
#    to PRODUCTION (drone-navigation.com).
```

**Smoke test (no flight):** `python e2e_command_check.py` validates the full command chain. Then the `Livestream Host` HUD shows `Link live | ~20 Hz` with real position / attitude / battery, and the Takeoff/Stop/Landing button + Flight disk fly the drone.

Safety rules that are always in effect:

- Takeoff is **refused on a USB cable** (`usb://*`); flight goes over the Crazyradio only.
- **Multiple drones in one room:** each drone flies only on its own provisioned channel/address (see the steps above).

The telemetry path mirrors the video path: `motion_control_ws.py` owns the Crazyflie link and broadcasts telemetry on `ws://127.0.0.1:8765`; `telemetry_relay.py` forwards it to the server (`WS /api/drone/telemetry/publish`), which fans out to browsers (`WS /api/drone/telemetry`). Set `"drone": { "telemetry_token": "..." }` in the deployed `server/config.json` to require `TELEMETRY_TOKEN=<same>` on the relay (empty = open, fine locally).

## Section 10. Daily workflow + troubleshooting

Start order each session (one terminal each) — or use the systemd services in Section 11:

```bash
/usr/lib/postgresql/$(ls /usr/lib/postgresql)/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
cd ~/drone-navigation/server && conda activate drone-navigation && uvicorn app.main:app --reload --port 8000
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml &
openclaw gateway --port 18789
~/mediamtx_v1.9.0/mediamtx
cd ~/drone-navigation/extension/simple_webcam && conda activate drone-navigation && \
  MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 LIVESTREAM_ID=crazyflie-drone \
  python simple_webcam.py
cd ~/drone-navigation/client && npm run dev
# Real drone: Section 9
```

Stop: Ctrl+C each process; `pg_ctl -D ~/pgdata stop` for PostgreSQL.

- The Vite dev server stays manual — it's the frontend you're actively developing.
- `drone-fastapi` keeps `--reload`: `.py` edits auto-apply; after editing `server/config.json`, `touch server/app/main.py` (works from any shell, no restart needed).
- If the `drone-webcam` service (Section 11) is running, don't also run `simple_webcam.py` manually — that would double-publish the same stream id.

## Section 11. Background services (optional — systemd user services)

Once Sections 3–7 are installed, every backend can run as a systemd **user** service — auto-started at boot (user lingering is enabled), no terminals needed:

```bash
cp deployment/local-systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam
```

| Service | Role | Port(s) |
|---|---|---|
| `drone-pg` | PostgreSQL dev cluster (`~/pgdata`) | 5433 |
| `drone-fastapi` | FastAPI backend (uvicorn `--reload`) | 8000 |
| `drone-synapse` | Matrix Synapse homeserver | 8008 |
| `drone-mediamtx` | MediaMTX (WHIP/WHEP, HLS, control API) | 8889, 8888, 9997 |
| `drone-webcam` | Demo webcam → WHIP publisher | — |
| `openclaw-gateway` | OpenClaw gateway (self-installed by `openclaw gateway install`) | 18789 |

Management cheatsheet:

```bash
systemctl --user status drone-fastapi         # state
journalctl --user -u drone-fastapi -f         # follow logs
systemctl --user restart drone-fastapi        # restart one
systemctl --user disable --now drone-webcam   # stop the webcam publisher (e.g. a real drone publishes instead)
```

Demo-day policy on the maintainer's desktop: all six services are **disabled** so they stay off across reboots — start them manually only when needed:

```bash
# Bring the whole backend stack up for a demo
systemctl --user start drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam openclaw-gateway

# Shut it down again afterwards
systemctl --user stop drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam openclaw-gateway
```

Note: `openclaw-gateway.service` is created by OpenClaw's own installer — it's listed only for completeness; don't copy a unit for it.

## License

See [LICENSE](LICENSE) for the full End-User License Agreement.

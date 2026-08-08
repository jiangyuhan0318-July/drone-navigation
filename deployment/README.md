# Drone\-Navigation Website

This document describes how the `drone-navigation` project is deployed and operated in production.


# 1. Domain Name

## 1.1 Porkbun Domain Name Registrar

The domain `drone-navigation.com` is registered through [Porkbun](https://porkbun.com/).

Use Porkbun to manage DNS records (A / AAAA / CNAME) that point the domain to the Alibaba Cloud ECS instance. Screenshots of the Porkbun DNS configuration are attached below for reference.

![Porkbun login](assets/porkbun_01.png)

![Porkbun Domain management](assets/porkbun_02.png)

![Porkbun DNS records](assets/porkbun_03.png)

![Porkbun DNS edit record](assets/porkbun_04.png)

&nbsp;
## 1.2 Alibaba Cloud

The production server runs on an Alibaba Cloud ECS instance (Ubuntu 24.04.4 LTS).

**Login portal**

```plain
URL:      https://signin.aliyun.com/
```

### 1. Network Security Group

Ensure the ECS security group allows inbound traffic on the ports used by the services:

| Port | Protocol | Purpose                |
|------|----------|------------------------|
| 22   | TCP      | SSH remote access      |
| 80   | TCP      | HTTP (Caddy)           |
| 443  | TCP      | HTTPS (Caddy)          |
| 3128 | TCP      | Squid HTTPS proxy      |

A screenshot of the security group rules is attached below.

![Alibaba Login](assets/alibaba_01.png)

![Alibaba Cloud security group rules](assets/alibaba_02.png)

The table above covers ECS 1 (the Caddy host). ECS 2 (`47.85.110.135`, MediaMTX + Synapse) needs its own inbound rules: TCP `8889` (WHIP/WHEP signaling — Caddy proxies `/live/*` to it), TCP `9997` (control API — Caddy proxies `/control-api/*` to it), and UDP `8189` (WebRTC ICE media). Synapse's port 8008 needs no rule at all — it binds only to the Tailscale interface (section 3.5).


&nbsp;
### 2. CDN

To configure an Alibaba Cloud CDN distribution in front of Caddy, pointing its origin to the ECS public IP or `drone-navigation.com`, coordinate with Alibaba Cloud's support team.

First, navigate to the detail page of our domain `drone-navigation.com` on `porkbun.com`.

![Click the detail button of our domain](assets/cdn_entry.png)

Next, download the **SSL bundle** for `drone-navigation.com`, which includes the domain certificate, public key, and private key.

![The SSL bundle of our domain](assets/cdn_ssl.png)

The most critical step is creating the **direct domain record** for `drone-navigation.com` that points directly to our ECS server running the Caddy web engine.

In addition, create the **CDN edge domain names** — `www.drone-navigation.com` and `cdn.drone-navigation.com` — as CNAMEs pointing to `drone-navigation.com`.

Contact Alibaba Cloud support for assistance with this configuration.

![The CDN domain names (CNAMEs)](assets/cdn_cname.png)


&nbsp;
### 3. WebSocket and the CDN (option 2: apex-pinned WS)

Alibaba's base CDN **cannot proxy WebSocket** (that requires the DCDN product and Alibaba staff involvement), so the SPA never upgrades through the CDN edge. Instead, the OpenClaw WebSocket URL is **pinned to the apex** in the production `client/config.json`:

```json
"openclaw": { "url": "wss://drone-navigation.com/ws", "token": "..." }
```

An explicitly configured non-loopback URL always wins in `client/composables/useOpenClaw.js`, so every visitor — whether the page was loaded via `drone-navigation.com`, `www`, or `cdn` — opens the WebSocket directly against the apex (which resolves to ECS 1, bypassing the CDN edge). This is bandwidth-neutral for the origin (WebSocket payloads are never edge-cached anyway); the only thing given up is the edge's TCP-junk absorption, and it is 100% self-service (DNS, Caddy, and OpenClaw are all ours — no Alibaba ticket).

Two hardening requirements, both satisfied:

1. **Origin allowlist on `/ws`** — WebSocket has no CORS, so the server must validate the browser `Origin` itself. The `/ws` blocks in [`deployment/caddy/Caddyfile`](./caddy/Caddyfile) return `403` for any `Origin` outside `https://drone-navigation.com`, `https://www.drone-navigation.com`, `https://cdn.drone-navigation.com` (requests with no `Origin` header — curl, server-to-server — are allowed).
2. **`wss://` with a publicly trusted certificate** — the apex uses Caddy's Let's Encrypt cert (auto-renewed); `tls internal` is only for the CDN edge domains and must never be browser-facing.

Verify after deploy (expect `101 Switching Protocols` for an allowed or absent Origin, `403` for a foreign Origin):

```bash
curl -i -N --max-time 5 \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Origin: https://www.drone-navigation.com" \
  https://drone-navigation.com/ws
```


&nbsp;
# 2. Frontend Servers

## 2.1 Caddy Web Engine

`Caddy` is installed and run on `launch-advisor-20260213/i-0xi7m4xb72am9kjxn9mr 8.221.124.43`, an Alibaba ECS server in Virginia USA. 

### 1. Caddy Installation

Install Caddy on Ubuntu using the official Cloudsmith repository.

```bash
# 1. Update system packages and install prerequisites
sudo apt update && sudo apt install -y ca-certificates curl gnupg

# 2. Install additional apt tooling for third-party repositories
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl

# 3. Add the official Caddy GPG key
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg

# 4. Add the official Caddy apt repository
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  tee /etc/apt/sources.list.d/caddy-stable.list

# 5. Update package lists and install Caddy
sudo apt update
sudo apt install caddy -y

# 6. Verify installation and service status
caddy version
sudo systemctl status caddy
```

If the GPG key download fails due to DNS or network issues, check `/etc/resolv.conf` and retry from a stable connection.


&nbsp;
### 2. drone\-navigation Deployment

Build the Vue frontend and deploy it behind Caddy.

```bash
# 1. Download the entire repository
cd ~
git clone https://github.com/kandeng/drone-navigation.git
cd drone-navigation/client/

# 2. Fetch latest code + merge into your local branch
cd ~/drone-navigation
git pull origin main

# 3. Install dependencies and build the production bundle
npm install -g npm@11.12.1    # (Optional) Upgrade npm if needed
npm install

# 4. Configure API keys
# Edit client/config.json with your Google Maps API key and Cesium Ion token.
vim config.json

# 5. Populate the video clips for splashing.
cp ~/drone-navigation/client/assets/media/*.mp4 ~/drone-navigation/client/public/splash/.
rm ~/drone-navigation/client/public/splash/drone_earth*.mp4

# 6. Re-build after configuration changes
npm run build

# 7. Create the web root directory and copy the built assets
sudo mkdir -p /var/www/drone-navigation/client/dist
sudo cp -r ~/drone-navigation/client/dist/* /var/www/drone-navigation/client/dist/

# 8. Deploy the runtime config.json (this file is gitignored and must be copied manually)
sudo cp ~/drone-navigation/client/config.json /var/www/drone-navigation/client/dist/config.json
```

After copying the files, configure Caddy (see the next section) and reload the service:

```bash
sudo systemctl reload caddy
sudo systemctl status caddy
```

To inspect Caddy logs:

```bash
sudo journalctl -u caddy -f
```


&nbsp;
### 3. Caddy Configuration

Create or edit `/etc/caddy/Caddyfile` to serve the built frontend. Caddy will automatically provision and renew HTTPS certificates for the listed domains.

See [`deployment/caddy/Caddyfile`](./caddy/Caddyfile) for the full configuration.

After editing:

```bash
# Format the Caddyfile including indention
caddy fmt --overwrite /etc/caddy/Caddyfile
# Validate cleanly without any ACME errors or syntax issues
caddy validate --config /etc/caddy/Caddyfile

# Reload Caddy to apply the new configuration
sudo systemctl reload caddy
sudo systemctl status caddy
```


&nbsp;
## 2.2 Squid Proxy

`Squid` is installed and run on `launch-advisor-20260213/i-0xi7m4xb72am9kjxn9mr 8.221.124.43`, an Alibaba ECS server in Virginia USA. 

### 1. Squid Installation

Install Squid on the same Ubuntu server:

```bash
sudo apt update
sudo apt install -y squid openssl

# Verify installation
squid -v

# Create directories for TLS certificates and passwords
sudo mkdir -p /etc/squid/certs
sudo mkdir -p /var/log/squid
sudo mkdir -p /var/spool/squid

# (Optional) Create a self-signed certificate for HTTPS proxy testing
# In production, use Let's Encrypt or another trusted CA.
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/squid/certs/www.drone-navigation.com.key \
  -out /etc/squid/certs/www.drone-navigation.com.crt \
  -subj "/CN=www.drone-navigation.com"
```


&nbsp;
### 2. Squid Configuration

Edit `/etc/squid/squid.conf` to enable an authenticated HTTPS proxy on port `3128`.

See [`deployment/squid/squid.conf`](./squid/squid.conf) for the full configuration.

After editing, validate and restart Squid:

```bash
sudo squid -k parse
sudo systemctl restart squid
sudo systemctl status squid
```

&nbsp;
### 3. Squid Passwords

Create and manage the password file used by Squid's basic authentication helper.

```bash
# 1. Generate an htpasswd-compatible hash for the user
openssl passwd -apr1 <your-plain-password>

# 2. Create /etc/squid/passwords with the username and hashed password.
# The format is:  username:hash
# Example (replace <hash> with the output from the previous command):
echo "<your-username>:<hash>" | sudo tee /etc/squid/passwords

# 3. Verify the credentials against the password file
echo "<your-username> <your-plain-password>" | /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
```

If the verification prints `OK`, authentication is configured correctly. Make sure the file is readable by the Squid process:

```bash
sudo chmod 640 /etc/squid/passwords
sudo chown root:proxy /etc/squid/passwords
```


&nbsp;
### 4. Squid Usage

Test the HTTPS proxy from a MacBook or Ubuntu desktop using `curl`:

```bash
# Without authentication (expected to fail with 407)
curl --proxy-insecure -x https://www.drone-navigation.com:3128 -I https://www.google.com

# With inline authentication
curl --proxy-insecure -x https://<proxy-user>:<proxy-password>@www.drone-navigation.com:3128 -I https://www.google.com
```

A successful request returns:

```plain
HTTP/1.1 200 Connection established
HTTP/2 200
...
```

**Known platform notes**

- **iOS / macOS**: Direct OS-level HTTPS proxy settings are strict and often reject self-signed certificates. Both iPhone and MacBook may fail to use `drone-navigation.com:3128` when configured in system network settings.
- **macOS (Clash Verge)**: You can theoretically route traffic through Clash Verge pointing at `drone-navigation.com:3128`, but configuration is challenging.
- **Ubuntu**: Setting the proxy server is straightforward, but providing authenticated credentials at the OS level can be tricky.
- **Windows / Android**: Not yet tested.


&nbsp;
# 3. Backend Servers

## 3.1. OpenClaw for Customer Service

`Openclaw` is installed and run on `launch-advisor-20260213/i-0xi7m4xb72am9kjxn9mr 8.221.124.43`, an Alibaba ECS server in Virginia USA. 

We use OpenClaw as the customer service assistant.
Follow [Alibaba's OpenClaw installation guide](https://help.aliyun.com/zh/model-studio/openclaw)
to deploy it on an Alibaba ECS server located in Virginia, USA.

### 1. Prerequisites

Before installing, request the following from your AI model provider: `baseUrl`, `apiKey`, `api`, and the list of available AI models.
These values are used in the OpenClaw configuration file at `~/.openclaw/openclaw.json`.

~~~
  "models": {
    "mode": "merge",
    "providers": {
      "bailian-token-plan": {
        "baseUrl": "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
        "apiKey": "YOUR_API_KEY",
        "api": "anthropic-messages",
        "models": [
          {
            "id": "qwen3.8-max-preview",
            "name": "qwen3.8-max-preview",
            "reasoning": true,
            "input": ["text", "image"],
            "contextWindow": 983616,
            "maxTokens": 131072,
            "cost": { "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0 },
            "compat": { "thinkingFormat": "openai" }
          },
          ...
        ]
      }
    }
  }
~~~

&nbsp;
### 2. openclaw.json

See [`deployment/openclaw/openclaw.json`](./openclaw/openclaw.json) for the full configuration.

&nbsp;
### 3. Restart OpenClaw from Scratch

~~~
# Stop the systemd service first
openclaw gateway stop

# Force kill any remaining processes using port 18789
sudo fuser -k 18789/tcp

# Alternatively, kill all running openclaw processes
pkill -9 -f openclaw

# Run this to make sure nothing is listening on 18789
ss -tulpn | grep 18789
```
root@iZ0xi7m4xb72am9kjxn9mrZ:~/.openclaw# ss -tulpn | grep 18789
tcp   LISTEN 0      511              127.0.0.1:18789      0.0.0.0:*    users:(("openclaw-gatewa",pid=2714644,fd=22))             
tcp   LISTEN 0      511                  [::1]:18789         [::]:*    users:(("openclaw-gatewa",pid=2714644,fd=23)) 

sudo kill -9 2714644
```

# Verify the syntax of openclaw.json
jq . openclaw.json

# Perform a complete re-registration and setup of the OpenClaw gateway
# as a system background service (daemon),
# overwriting any existing service configurations.
openclaw gateway install --force 

openclaw gateway restart

openclaw gateway status

View recent logs, e.g.: `tail -n 100 /tmp/openclaw-0/openclaw-2026-07-21.log`
~~~


&nbsp;
## 3.2. MediaMTX for Livestream

`MediaMTX` is installed and run on `launch-advisor-20260723/i-0xif3f3l5j6qwh8kapws 47.85.110.135`, an Alibaba ECS server in Virginia USA. 


### 1. Installation

~~~
root@iZ0xif3f3l5j6qwh8kapwsZ:~# mkdir mediamtx_v1.9.0
root@iZ0xif3f3l5j6qwh8kapwsZ:~# cd mediamtx_v1.9.0/

root@iZ0xif3f3l5j6qwh8kapwsZ:~/mediamtx_v1.9.0# wget https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_amd64.tar.gz
root@iZ0xif3f3l5j6qwh8kapwsZ:~/mediamtx_v1.9.0# tar -xzf mediamtx_v1.9.0_linux_amd64.tar.gz
root@iZ0xif3f3l5j6qwh8kapwsZ:~/mediamtx_v1.9.0# ls -l
total 44156
-rw-r--r-- 1 root root     1062 Aug 26  2024 LICENSE
-rwxr-xr-x 1 root root 29860595 Aug 26  2024 mediamtx
-rw-r--r-- 1 root root 15317195 Aug 27  2024 mediamtx_v1.9.0_linux_amd64.tar.gz
-rw-r--r-- 1 root root    28112 Aug 26  2024 mediamtx.yml
~~~

Start up `MediaMTX` using the executable file `mediamtx` for testing purpose.

~~~
root@iZ0xif3f3l5j6qwh8kapwsZ:~/mediamtx_v1.9.0# ./mediamtx
2026/07/25 16:13:11 INF MediaMTX v1.9.0
2026/07/25 16:13:11 INF configuration loaded from /root/mediamtx_v1.9.0/mediamtx.yml
2026/07/25 16:13:11 INF [RTSP] listener opened on :8554 (TCP), :8000 (UDP/RTP), :8001 (UDP/RTCP)
2026/07/25 16:13:11 INF [RTMP] listener opened on :1935
2026/07/25 16:13:11 INF [HLS] listener opened on :8888
2026/07/25 16:13:11 INF [WebRTC] listener opened on :8889 (HTTP), :8189 (ICE/UDP)
2026/07/25 16:13:11 INF [SRT] listener opened on :8890 (UDP)
~~~

&nbsp;
### 2. Configuration

See [`deployment/mediamtx/mediamtx.yml`](./mediamtx/mediamtx.yml) for the full configuration.

&nbsp;
### 3. System daemon service

Register the MediaMTX as a new systemd service.

~~~
# 1. Reload systemd to recognize the new service:
sudo systemctl daemon-reload

# 2. Enable MediaMTX to start automatically on system boot:
sudo systemctl enable mediamtx
~~~

Start, stop, restart, reload, status, journal log.

~~~
# 1. Start the service immediately:
sudo systemctl start mediamtx

# 2. Verify service status and logs
sudo systemctl status mediamtx
# (You should see an active (running) state in green).

# 3. View live logs:
journalctl -u mediamtx -f

# 4. Stop service: 
sudo systemctl stop mediamtx

# 5. Restart service: 
#    Reload configuration: If you update mediamtx.yml, simply run sudo systemctl restart mediamtx.
sudo systemctl restart mediamtx
~~~


&nbsp;
## 3.3. PostgreSQL Database

`PostgreSQL` stores the identity data for the `My Space -> Account` page (fastapi-users tables `"user"` and `oauth_account`) and the per-user settings document (`user_settings`, single-row JSONB) written by the `Save` button. It runs on the same ECS instance as Caddy (`8.221.124.43`, PostgreSQL 16 on Ubuntu 24.04).

### 1. Installation

```bash
# Install the server (Ubuntu 24.04 ships PostgreSQL 16)
sudo apt update
sudo apt install -y postgresql postgresql-contrib

# Verify the cluster is up (cluster name: 16-main)
systemctl status postgresql@16-main
sudo systemctl enable postgresql@16-main
```

&nbsp;
### 2. Populate the schema (idempotent migration script)

All tables, the login role, and the database are created by one idempotent script — [`server/migrations/001_init_auth_schema.sql`](../server/migrations/001_init_auth_schema.sql). Its table DDL is generated from `server/app/models.py` (SQLAlchemy `CreateTable`/`CreateIndex` with the PostgreSQL dialect), so the schema is guaranteed to match what the FastAPI app expects. It creates:

| Object | Name | Notes |
|--------|------|-------|
| Login role | `drone_api` | Password is (re)aligned on every run via `-v app_password=...` |
| Database | `drone_navigation` | Owner: `drone_api` |
| Tables | `"user"`, `oauth_account`, `user_settings` | FK `ON DELETE CASCADE`; `user_settings.settings` is JSONB with `'{}'::jsonb` default |

```bash
# 1. Generate a strong password for the drone_api role (save it — it goes
#    into server/config.json in the next section)
openssl rand -hex 24

# 2. Copy the script somewhere the postgres user can read it
#    (postgres cannot read /root on the ECS)
sudo cp ~/drone-navigation/server/migrations/001_init_auth_schema.sql /tmp/
sudo chmod 644 /tmp/001_init_auth_schema.sql

# 3. Run it (safe to re-run; ON_ERROR_STOP aborts on the first failure)
sudo -u postgres psql -v ON_ERROR_STOP=1 \
     -v app_password='<paste-generated-password>' \
     -f /tmp/001_init_auth_schema.sql

# 4. Verify: connect as the application role over TCP and list tables
psql -h 127.0.0.1 -U drone_api -d drone_navigation -c '\dt'
```

Two implementation notes, both handled inside the script: `"user"` is a reserved word in PostgreSQL and must stay double-quoted, and `psql` does not substitute `:variables` inside `DO $$ ... $$` blocks, so the role bootstrap uses `SELECT ... \gexec` instead.

&nbsp;
### 3. Local development variant (no sudo, user-owned cluster)

The system cluster on port 5432 requires the sudo password; for local dev we instead run a user-owned PostgreSQL cluster:

```bash
# One-time init (trust auth on localhost, port 5433 to avoid the system cluster)
/usr/lib/postgresql/14/bin/initdb -D ~/pgdata -U robot -E UTF8 --auth=trust
printf "port = 5433\nunix_socket_directories = '/home/robot/pgdata'\n" >> ~/pgdata/postgresql.conf

# Start / stop
/usr/lib/postgresql/14/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
/usr/lib/postgresql/14/bin/pg_ctl -D ~/pgdata stop

# Populate the same schema (as superuser 'robot', trust auth)
psql -h 127.0.0.1 -p 5433 -U robot -v ON_ERROR_STOP=1 \
     -v app_password='local-dev-drone-api' \
     -f server/migrations/001_init_auth_schema.sql
```

&nbsp;
### 4. Regenerating DDL after model changes

Whenever `server/app/models.py` changes, regenerate the table blocks and review them before re-running the migration:

```bash
cd server && ~/miniconda3/envs/drone-navigation/bin/python -m migrations.generate_ddl
```

&nbsp;
## 3.4. FastAPI for My\-Space (fastapi-users)

`FastAPI` + [`fastapi-users`](https://fastapi-users.github.io/) provides the `My Space -> Account` flows: email/password register + login (JWT), password reset and email verification (SMTP), Google OAuth, and `GET`/`PUT /api/users/me/settings` — the endpoints behind the `Save` button (logged-in: settings persisted to `user_settings`; logged-out: the SPA redirects to the Account page with a "please log in" banner). It runs on the same ECS instance as Caddy (`8.221.124.43`), behind the Caddy `/api/*` reverse proxy.

### 1. Installation

```bash
cd ~/drone-navigation/server

# 1. Create a conda environment (system Python 3.12 works)
conda create -n drone-navigation python=3.12 -y
conda config --set auto_activate_base false
conda activate drone-navigation

# 2. Install dependencies — see server/requirements.txt:
#    fastapi-users[sqlalchemy]  (FastAPIUsers, JWT strategy, OAuth routers)
#    sqlalchemy[asyncio] + asyncpg  (async PostgreSQL driver)
#    aiosmtplib + email-validator   (verification / password-reset emails)
#    httpx-oauth                    (Google OAuth)
pip install -r requirements.txt
```

&nbsp;
### 2. Configuration

`server/config.json` is gitignored (contains secrets) — create it from [`server/config.example.json`](../server/config.example.json):

```bash
cp config.example.json config.json
nano config.json
```

| Key | Production (ECS) | Local dev |
|-----|------------------|-----------|
| `secret` | Long random string (`openssl rand -hex 32`) — signs JWTs | any dev string |
| `database_url` | `postgresql+asyncpg://drone_api:<app_password>@127.0.0.1:5432/drone_navigation` | `postgresql+asyncpg://drone_api:local-dev-drone-api@127.0.0.1:5433/drone_navigation` |
| `frontend_base_url` | `https://drone-navigation.com` | `http://localhost:5173` |
| `cors_origins` | `[]` (same-origin behind Caddy) | `["http://localhost:5173"]` |
| `smtp` | Real provider credentials (verification/reset emails) | leave placeholders — emails are skipped |
| `oauth.google` | Google Cloud OAuth client id/secret | can stay empty (Google button hidden) |

&nbsp;
### 3. Run

```bash
# Development (auto-reload) in CLI terminal
cd ~/drone-navigation/server
conda activate drone-navigation
uvicorn app.main:app --reload --port 8000
```

```bash
# Production (loopback only; Caddy proxies /api/* to it)
# Run as a system daemon service

# 1. Edit the content of the systemd configuration. 
nano /etc/systemd/system/drone-fastapi.service

# 2. Reload systemd to parse the new service file
sudo systemctl daemon-reload

# 3. Enable service on server boot AND start it immediately
sudo systemctl enable --now drone-fastapi

# 4. Check process health
sudo systemctl status drone-fastapi

# 5. View real-time logs (replacing terminal output)
sudo journalctl -u drone-fastapi -f
```

Refer to [`./fastapi/drone-fastapi.service`](./fastapi/drone-fastapi.service) for its content.

On startup the app runs `Base.metadata.create_all` as a dev convenience; on a fresh server you should still run the migration script from section 3.3 first, because it also creates the `drone_api` role, the database, and the GRANTs. For production, wrap the uvicorn command in a systemd unit (same pattern as the MediaMTX unit in section 3.2).

&nbsp;
### 4. Smoke test

```bash
# 1. Health
curl -s http://127.0.0.1:8000/api/health        # {"status":"ok"}

# 2. Register + login (JWT)
curl -s -X POST http://127.0.0.1:8000/api/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"email":"me@example.com","password":"Secret123!","display_name":"Me"}'
curl -s -X POST http://127.0.0.1:8000/api/auth/jwt/login \
     -H 'Content-Type: application/x-www-form-urlencoded' \
     -d 'username=me@example.com&password=Secret123!'

# 3. Settings round-trip (use the access_token from step 2)
curl -s -X PUT http://127.0.0.1:8000/api/users/me/settings \
     -H "Authorization: Bearer <access_token>" -H 'Content-Type: application/json' \
     -d '{"version":1,"locale":"en","font":{"fontSize":"18px"}}'
curl -s http://127.0.0.1:8000/api/users/me/settings \
     -H "Authorization: Bearer <access_token>"   # returns the saved JSONB document
```

End-to-end check from the browser (the goal of sections 3.3–3.4): open `My Space -> Account`, register and sign in; then on `My Space -> Settings` change a value and click the `Save` button in the left dock — a green "Your settings have been saved." banner appears and the document is persisted in PostgreSQL. Clicking `Save` while logged out instead redirects to `My Space -> Account` with a green "Please log in before saving." banner.


&nbsp;
## 3.5. Synapse Matrix

`Synapse` powers the `Community -> Chat` page: in-site direct messages and team rooms. It runs on ECS 2 (`47.85.110.135`, alongside MediaMTX) and is reached **exclusively through the Tailscale mesh** (section 4.1) — its only listener binds to the Tailscale interface, so nothing Matrix-specific is exposed on the public internet.

Website users never see Matrix: registering in `My Space -> Account` auto-provisions a hidden Synapse account (`@u_<id>:drone-navigation.com`), and logging in transparently brokers a client access token via the Synapse Admin API (single-account illusion). Public registration on the homeserver itself is disabled — the website is the only entrance.

v1 scope: federation is **OFF** (no 8448 listener, no `.well-known`, no `matrix.drone-navigation.com` DNS record), rooms are not end-to-end encrypted, and storage is SQLite (migrate to PostgreSQL later with `synapse_port_db` if volume demands it).

**Prerequisites**

- Section 4.1 (Tailscale) completed on BOTH servers. Below, `<TAILSCALE_B>` = Tailscale IPv4 of ECS 2 (Synapse host), `<TAILSCALE_A>` = Tailscale IPv4 of ECS 1 (Caddy/FastAPI host).
- Sections 3.3 (PostgreSQL) and 3.4 (FastAPI) already done on ECS 1.

&nbsp;
### 1. Installation (on ECS 2)

```bash
# Run on 47.85.110.135 as root (same account style as the MediaMTX setup)

# 1. Create a virtualenv from the SYSTEM python3 (3.12+). Do NOT use a conda
#    python here: the Anaconda "defaults" SQLite build lacks FTS4/FTS5, and
#    Synapse's schema needs FTS4 ('no such module: fts4' at first start).
python3 -m venv --without-pip /root/synapse-venv
curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
/root/synapse-venv/bin/python /tmp/get-pip.py

# 2. Install Synapse (pinned to the version verified locally).
#    NOTE: this host's /etc/pip.conf points at Alibaba's VPC-internal mirror
#    (mirrors.cloud.aliyuncs.com), which does not always resolve — pass the
#    public index explicitly:
/root/synapse-venv/bin/pip install --index-url https://pypi.org/simple matrix-synapse==1.157.1

# 3. Generate the initial config + data directory. cd INTO the data dir first:
#    generate-config embeds CWD-absolute paths (database, media_store, pid,
#    log) — running it from ~ would litter /root with homeserver.db etc.
#    server-name = the PUBLIC domain: user IDs will be @user:drone-navigation.com
mkdir -p ~/synapse-data && cd ~/synapse-data
/root/synapse-venv/bin/python -m synapse.app.homeserver \
  --server-name drone-navigation.com \
  --config-path ~/synapse-data/homeserver.yaml \
  --generate-config --report-stats=no
```

&nbsp;
### 2. homeserver.yaml — Tailscale-only listener

Edit `~/synapse-data/homeserver.yaml` on ECS 2:

1. Keep exactly **one** listener entry, bound to the Tailscale IP (NOT `127.0.0.1`, NOT `0.0.0.0`):

```yaml
listeners:
  - port: 8008
    tls: false
    type: http
    x_forwarded: true
    bind_addresses: ['<TAILSCALE_B>']
    resources:
      - names: [client]
        compress: false
```

There is no 8448 entry (federation stays off) and no `federation` resource above. The Admin API (`/_synapse/admin/*`) is served by the `client` listener itself — Synapse has no separate `admin` resource name (passing one fails config validation at startup). `x_forwarded: true` lets Synapse log the real client IPs that Caddy forwards.

2. Verify registration stays closed (users are provisioned by FastAPI, never by the public):

```yaml
enable_registration: false
```

3. Keep the generated SQLite `database` block, `macaroon_secret_key`, and `registration_shared_secret` unchanged.

&nbsp;
### 3. First start + service admin (on ECS 2)

```bash
# Foreground smoke run — Ctrl-C after verifying
/root/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml
```

From **ECS 1**, prove the mesh path before going further:

```bash
curl http://<TAILSCALE_B>:8008/_matrix/client/versions
# -> {"versions":[...,"v1.11"]}
```

Back on **ECS 2**, create the service admin user and harvest its long-lived access token:

```bash
/root/synapse-venv/bin/register_new_matrix_user \
  -c ~/synapse-data/homeserver.yaml \
  -u admin -p '<generate-a-strong-password>' --admin \
  http://<TAILSCALE_B>:8008

curl -s -X POST http://<TAILSCALE_B>:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"admin","password":"<same-password>"}'
# -> save the returned "access_token" (starts with syt_...); it goes into
#    server/config.json on ECS 1 in step 5
```

&nbsp;
### 4. systemd service (on ECS 2)

Copy [`deployment/synapse/drone-synapse.service`](./synapse/drone-synapse.service) to `/etc/systemd/system/drone-synapse.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now drone-synapse
sudo systemctl status drone-synapse        # active (running)
sudo journalctl -u drone-synapse -f        # live logs
```

Synapse coexists with MediaMTX without port conflicts: 8008 binds only to the Tailscale interface, while MediaMTX uses 8554/1935/8888/8889/8890 on the public interface.

&nbsp;
### 5. FastAPI wiring (on ECS 1)

1. Add the `matrix_account` table (idempotent migration):

```bash
sudo cp ~/drone-navigation/server/migrations/002_matrix_account.sql /tmp/
sudo chmod 644 /tmp/002_matrix_account.sql
sudo -u postgres psql -v ON_ERROR_STOP=1 -d drone_navigation -f /tmp/002_matrix_account.sql
```

2. Edit `~/drone-navigation/server/config.json` — point the backend at Synapse over the mesh:

```json
"synapse": {
  "base_url": "http://<TAILSCALE_B>:8008",
  "server_name": "drone-navigation.com",
  "admin_access_token": "<syt_... token from step 3>"
}
```

3. Restart the backend:

```bash
sudo systemctl restart drone-fastapi
sudo journalctl -u drone-fastapi -f
```

&nbsp;
### 6. Caddy route (on ECS 1)

Add a `/_matrix/*` block to BOTH site blocks in `/etc/caddy/Caddyfile` (apex `drone-navigation.com` and CDN edge `www.drone-navigation.com`), right after the existing `/api/*` block. Plain `handle` keeps the path prefix (Synapse routes include `/_matrix`):

```plain
# Synapse Matrix client API (over the Tailscale mesh)
handle /_matrix/* {
    reverse_proxy <TAILSCALE_B>:8008 {
        header_up Host {host}
        header_up X-Real-IP {remote_host}
    }
}
```

Then format, validate, and reload:

```bash
caddy fmt --overwrite /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The repo copy [`deployment/caddy/Caddyfile`](./caddy/Caddyfile) carries this block with the live Tailscale IP — keep the two in sync on every route change.

&nbsp;
### 7. Smoke tests

```bash
# 1. Mesh + homeserver (from ECS 1)
curl http://<TAILSCALE_B>:8008/_matrix/client/versions

# 2. Public client API through Caddy (apex direct, and via the CDN edge)
curl https://drone-navigation.com/_matrix/client/versions
curl https://www.drone-navigation.com/_matrix/client/versions

# 3. Token brokering through the whole stack
TOKEN=$(curl -s -X POST https://drone-navigation.com/api/auth/jwt/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'username=me@example.com&password=Secret123!' | jq -r .access_token)
curl -s https://drone-navigation.com/api/matrix/token \
  -H "Authorization: Bearer $TOKEN"
# -> {"homeserver_url":"","access_token":"syt_...",
#     "user_id":"@u_...:drone-navigation.com","device_id":null}
```

The first `/api/matrix/token` call for any pre-existing website user lazily provisions their hidden Synapse account — no manual step needed.

Browser end-to-end: sign in as two different accounts (two browsers or profiles), open `Community -> Chat`, start a New chat with the other user, exchange messages both ways, reload and confirm history persists; then create a team room containing both.

&nbsp;
### 8. Deleting a website user (incl. Matrix cleanup)

Deleting the PostgreSQL row alone is NOT enough: the hidden Synapse account and its access tokens survive. Token brokering issues *admin-puppeted* tokens — they live in `access_tokens` under `@admin:drone-navigation.com` with `puppets_user_id` set to the hidden account — and Synapse's deactivation does not revoke them (an old chat token keeps passing `whoami` until the row is gone).

1. **PostgreSQL (ECS 1)** — deleting from `"user"` cascades to `matrix_account`, `user_settings`, and `oauth_account`:

```bash
sudo -u postgres psql -d drone_navigation \
  -c "DELETE FROM \"user\" WHERE email = '<user@example.com>';"
```

2. **Synapse (ECS 2)** — deactivate + erase the hidden account (erases its messages; the mxid was stored in `matrix_account`, format `@u_<hex8>:drone-navigation.com`; URL-encode `@` -> `%40`, `:` -> `%3A`):

```bash
curl -s -X POST http://<TAILSCALE_B>:8008/_synapse/admin/v1/deactivate/<url-encoded-mxid> \
  -H "Authorization: Bearer <admin syt_ token>" -H 'Content-Type: application/json' \
  -d '{"erase": true}'
```

3. **Kill its live tokens (ECS 2)**, then restart to flush Synapse's in-process auth cache:

```bash
/root/synapse-venv/bin/python -c "import sqlite3; \
  db = sqlite3.connect('/root/synapse-data/homeserver.db'); \
  db.execute(\"DELETE FROM access_tokens WHERE puppets_user_id = '<mxid>'\"); db.commit()"
sudo systemctl restart drone-synapse
```

Verify: website login -> `LOGIN_BAD_CREDENTIALS`; old chat token -> `M_UNKNOWN_TOKEN` from `https://drone-navigation.com/_matrix/client/v3/account/whoami`.

&nbsp;
### 9. Troubleshooting

| Symptom | Likely cause / check |
|---------|----------------------|
| `503 Chat service unavailable` from `/api/matrix/token` | Wrong `base_url`/token in `server/config.json`, or Synapse down — `journalctl -u drone-fastapi -f` (ECS 1) and `journalctl -u drone-synapse -f` (ECS 2) |
| `curl http://<TAILSCALE_B>:8008/...` times out from ECS 1 | Tailscale down (`tailscale status`), or listener bound to the wrong IP — `ss -tulpn \| grep 8008` on ECS 2 must show the 100.x address |
| `sqlite3.OperationalError: no such module: fts4` at first start | The python's bundled SQLite lacks FTS4 (conda's Anaconda-"defaults" build) — rebuild the env from the SYSTEM python3 per step 1 |
| `table background_updates already exists` at first start | Stale DB from a previously crashed first start — delete `homeserver.db*` (check BOTH `~/synapse-data/` and `~/`, see step 1 note) and start again |
| pip `Failed to resolve 'mirrors.cloud.aliyuncs.com'` | `/etc/pip.conf` points at Alibaba's VPC-internal mirror, which doesn't resolve outside the VPC — always pass `--index-url https://pypi.org/simple` |
| DNS stops resolving right after `tailscale up` | tailscaled's MagicDNS wedged systemd-resolved — re-run `tailscale up --accept-dns=false` on the server (persistent pref), then `systemctl restart tailscaled systemd-resolved`; if still broken, `resolvectl revert tailscale0` |
| Chat works via apex but `/sync` drops every ~30–60 s when the page is loaded via `www` | CDN edge killing long-polls (same family as the customer-service WebSocket issue) — use the apex domain until the CDN behavior is addressed |
| Old chat access token still works after the website user was deleted | Admin-puppeted tokens survive Synapse deactivation — complete steps 2–3 of section 3.5.8 (delete `access_tokens` by `puppets_user_id`, then restart) |

Deferred to later phases (explicit v1 non-goals): federation Variant A provisioning (8448 listener, `.well-known/matrix/server`, `matrix.drone-navigation.com` A record), E2EE, media attachments, OpenClaw appservice bridge, SQLite→PostgreSQL migration, stale-device cleanup, message retention, push notifications.



&nbsp;
# 4. Server Cluster

## 4.1. Tailscale VPN

`Tailscale` builds a private WireGuard mesh ("tailnet") between the two ECS servers. It carries the **private plane**: Caddy's `/_matrix/*` reverse-proxy traffic and FastAPI's Synapse Admin API calls. Because Synapse binds only to the `tailscale0` interface (section 3.5), no Matrix port is ever exposed on the public internet. Both servers join the same tailnet under one Tailscale account.

&nbsp;
### 1. Install + join (on BOTH servers)

```bash
# Run on BOTH 8.221.124.43 and 47.85.110.135
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# -> prints an authentication URL; open it in a browser, sign in, and approve
#    the machine. Use the SAME Tailscale account for both servers.
```

&nbsp;
### 2. Verify the mesh

```bash
tailscale ip -4                  # this server's 100.x.y.z address — record it
tailscale status                 # both machines listed
ping -c 3 <other-100.x>          # ICMP over the mesh
tailscale ping <other-100.x>     # shows the direct path or DERP relay in use
```

Record the addresses — they are the `<TAILSCALE_A>` / `<TAILSCALE_B>` placeholders used in section 3.5:

| Server | Public IP | Tailscale IPv4 | Role |
|--------|-----------|----------------|------|
| ECS 1 | `8.221.124.43` | `<TAILSCALE_A>` | Caddy + FastAPI + PostgreSQL + OpenClaw |
| ECS 2 | `47.85.110.135` | `<TAILSCALE_B>` | Synapse + MediaMTX |

&nbsp;
### 3. Disable key expiry (mandatory for servers)

In the Tailscale admin console (`https://login.tailscale.com/admin/machines`), for each of the two machines: `...` menu -> **Disable key expiry**. Otherwise each machine's key expires after 180 days and the mesh silently breaks.

&nbsp;
### 4. Notes

- **Server DNS**: join with `tailscale up --accept-dns=false` on servers. MagicDNS is meant for client devices; on these Alibaba Ubuntu images it wedged systemd-resolved (all lookups timed out until reverted). See the section 3.5 troubleshooting table.
- **Alibaba security groups**: no new inbound rules are needed — Tailscale NAT-traverses using outbound connections and falls back to DERP relays. Optionally open UDP `41641` on both servers for faster direct links.
- **ACLs**: the default tailnet policy lets all nodes reach each other (fine for two servers). An ACL restricting port 8008 to just these two machines can be added later.
- Renaming the machines in the admin console (e.g. `ecs-caddy`, `ecs-synapse`) makes `tailscale status` output and logs easier to read.



&nbsp;
# 5. Extension

The two extensions under `extension/` run where the hardware is — in practice the maintainer's Ubuntu desktop — and publish **into** the production servers:

| Extension | What it does | Publishes into production |
|---|---|---|
| `extension/simple_webcam` | Grabs the desktop webcam and WHIP-ingests it as one MediaMTX stream | MediaMTX on ECS 2, via Caddy (`https://drone-navigation.com/live/*` -> `:8889`) |
| `extension/crazyflie_bridge` | Four processes around one Crazyradio link: MJPEG video proxy (`:8082`), motion-control WebSocket (`:8765`), telemetry relay (drone <-> FastAPI), drone-camera WHIP publisher | Video -> MediaMTX on ECS 2; telemetry -> FastAPI on ECS 1 (`wss://drone-navigation.com/api/drone/telemetry/publish`, via the Caddy `/api/*` proxy) |

Both default to PRODUCTION — no environment variables are needed to serve the real site. Set `MEDIAMTX_URL` / `MEDIAMTX_API` / `TELEMETRY_SERVER` only when targeting a local stack instead (that local flow is covered by the platform READMEs at the repository root).

&nbsp;
## 5.1. Prerequisites (Ubuntu desktop)

1. Clone the repo to `~/drone-navigation` and create the shared conda environment:

```bash
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install -r ~/drone-navigation/extension/simple_webcam/requirements.txt
pip install -r ~/drone-navigation/extension/crazyflie_bridge/requirements.txt
```

2. (Drone only) one-time udev rules so userland can reach the Crazyradio PA, and the drone itself over USB (used when changing its EEPROM identity):

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="5740", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-crazyflie.rules
sudo udevadm control --reload && sudo udevadm trigger
lsusb | grep 1915        # Nordic Semiconductor — the Crazyradio is visible
```

3. (Drone only) the drone's AI-Deck joins the same LAN as the desktop — find its IP (`nmap -sn 192.168.0.0/24`, then browse the `http://192.168.0.x` candidates until one shows the livestream). The examples below use `192.168.0.110`.

&nbsp;
## 5.2. simple_webcam (webcam -> production MediaMTX)

```bash
cd ~/drone-navigation/extension/simple_webcam
conda activate drone-navigation
python simple_webcam.py            # publishes stream id 'ubuntu-webcam' to PRODUCTION
```

Environment variables (defaults target production):

| Variable | Default | Meaning |
|---|---|---|
| `MEDIAMTX_URL` | `https://drone-navigation.com/live` | WHIP base URL (Caddy proxies `/live/*` -> ECS 2 `:8889`) |
| `MEDIAMTX_API` | `https://drone-navigation.com/control-api` | control API (Caddy proxies `/control-api/*` -> ECS 2 `:9997`) |
| `LIVESTREAM_ID` | `ubuntu-webcam` | MediaMTX path / stream id |

Verify: `curl https://drone-navigation.com/control-api/v3/paths/list` shows the id, and the website's `Real Drone -> Livestream Viewer` plays it. Which ids the SPA lists comes from the `"mediamtx": { "streams": [...] }` catalog in the deployed `server/config.json` — both `crazyflie-drone` and `ubuntu-webcam` are present by default (see `server/config.example.json`).

systemd variant: [`deployment/local-systemd/drone-webcam.service`](./local-systemd/drone-webcam.service) wraps the same publisher as a systemd **user** service — but note it overrides `MEDIAMTX_URL` / `MEDIAMTX_API` to `127.0.0.1` (it is meant for the local stack, section 11 of `README-ubuntu.md`). For production publishing, run the publisher manually as above or edit the unit's `Environment=` lines first.

&nbsp;
## 5.3. crazyflie_bridge (real drone -> production)

Plug in the Crazyradio PA and power the drone, then launch all four processes with one script (it self-activates the `drone-navigation` conda env):

```bash
cd ~/drone-navigation/extension/crazyflie_bridge
CRAZYFLIE_IP="192.168.0.110" RADIO_URL="radio://0/80/2M/E7E7E7E7E7" ./start_bridge.sh
#    = video_stream_proxy.py  (re-broadcasts http://$CRAZYFLIE_IP/stream on :8082)
#    + motion_control_ws.py   (ws://:8765; set RADIO_URL env var, or pass
#      --cf-uri to the script, to change the radio identity)
#    + telemetry_relay.py     (telemetry + flight commands, drone <-> FastAPI)
#    + crazyflie_mediamtx.py  (drone camera -> MediaMTX WHIP, id 'crazyflie-drone')
#    Stop: Ctrl+C (press twice to force) — lands the drone first if flying.
```

Environment variables (defaults target production):

| Variable | Default | Meaning |
|---|---|---|
| `CRAZYFLIE_IP` | `192.168.0.106` (script default) | drone AI-Deck IP — override as shown above |
| `RADIO_URL` | — | convenience alias for `--cf-uri`; pass a different radio URI, e.g. `radio://0/14/2M/E7E7E7E707`, to connect to a specific drone (the CLI `--cf-uri` still wins if both are given) |
| `TELEMETRY_SERVER` | `wss://drone-navigation.com/api/drone/telemetry/publish` | FastAPI ingest WebSocket; the command downlink derives from it (`.../command/downlink`) |
| `TELEMETRY_TOKEN` | empty | must match `"drone": { "telemetry_token" }` in the deployed `server/config.json` if set there (empty = open) |
| `MEDIAMTX_URL` / `MEDIAMTX_API` | production `/live` + `/control-api` | same meaning as in 5.2 |
| `LIVESTREAM_ID` | `crazyflie-drone` | stream id for the drone camera |
| `CF_NO_FLY` | — | `=1` refuses every takeoff (bench dry-run) |

Smoke test without flying: `python e2e_command_check.py` validates the full command chain. Then the website's `Livestream Host` HUD shows `Link live | ~20 Hz` with real position / attitude / battery, and the Takeoff/Stop/Landing button + Flight disk fly the drone. Safety rule that is always in effect: takeoff is **refused on a USB cable** (`usb://*`) — flight goes over the Crazyradio only.

Multi-drone note: the default radio URI is for SOLO use — same channel + same address = cross-control. To fly several drones in one room, provision each drone's EEPROM identity once over its USB cable (`python provision_drone.py --channel 14 --address E7E7E7E707` writes the identity, then verifies it over the radio after a power-cycle) and connect with `RADIO_URL="radio://0/14/2M/E7E7E7E707" ./start_bridge.sh` (or `./start_bridge.sh --cf-uri radio://0/14/2M/E7E7E7E707`). Give each drone a distinct channel, >=2 MHz apart at 2M datarate; `--read-only` prints the current identity without writing.



# 无人机导航 —— Ubuntu

多视角无人机导航仪表盘，融合 3D 空中可视化、2D 地图与任务控制界面。

本指南在**原生 Ubuntu 桌面上完整本地运行整个系统** —— 不依赖 ECS。开发环境下 SPA 跨源调用 `http://localhost:8000` 的 FastAPI，并经 Vite 的 `/_matrix` 代理访问 Synapse —— **本地无需 Caddy**（Caddy、Squid、Tailscale 仅生产环境使用）。其他平台与语言：

- Windows 10/11（WSL2）：[English](README.md) | [中文](README-zh.md)
- macOS：[English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu：[English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- 生产部署（阿里云 ECS、Caddy、Tailscale）：[deployment/README.md](deployment/README.md)

一切都原生运行。Ubuntu 也是唯一提供可选 systemd 用户服务（第 11 节）的平台，可让整套技术栈在后台运行，无需开着终端。

## 项目结构

```
drone-navigation/
├── client/       # Vue 3 + Vite 前端（Cesium、Google Maps、Street View）
├── server/       # FastAPI 后端（fastapi-users 认证、设置、Matrix 令牌中转）
├── extension/    # 独立推流/工具（simple_webcam WHIP 推流、crazyflie_bridge）
└── deployment/   # 生产配置与运维文档（Caddy、Squid、OpenClaw、MediaMTX、Synapse）
```

| 组件 | 端口 |
|---|---|
| 客户端（Vite 开发服务器） | 5173 |
| FastAPI 后端 | 8000 |
| PostgreSQL 开发集群 | 5433 |
| Synapse（社区聊天） | 8008 |
| OpenClaw（客服） | 18789 |
| MediaMTX（直播） | 8889, 8888, 9997 |
| crazyflie_bridge（真实无人机） | 8082, 8765 |

## 第 1 节. Ubuntu 环境准备

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

检查点：`node -v`、`npm -v`、`conda --version`、`git --version` 都能打印版本号。

## 第 2 节. 客户端（Vue 3 + Vite）

```bash
cd ~/drone-navigation/client
npm install
cp config.example.json config.json   # 填写 googleApiKey、cesiumIonToken、openclaw.token
npm run dev                          # http://localhost:5173
```

API 密钥的前置条件（Google Maps API、Cesium ion）见 [client/README.md](client/README.md)。

**冒烟测试：** `3D Aerial` 地球和 `2D Map` 应立即渲染 —— 它们不依赖后端。

## 第 3 节. PostgreSQL（用户自有的开发集群，端口 5433）

无需 sudo，与任何系统集群相互独立（详见 deployment/README.md §3.3.3）：

```bash
VER=$(ls /usr/lib/postgresql)        # Ubuntu 22.04 为 14

# 一次性初始化（localhost trust 认证，端口 5433）
/usr/lib/postgresql/$VER/bin/initdb -D ~/pgdata -U $USER -E UTF8 --auth=trust
printf "port = 5433\nunix_socket_directories = '$HOME/pgdata'\n" >> ~/pgdata/postgresql.conf

# 启动 / 停止
/usr/lib/postgresql/$VER/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
/usr/lib/postgresql/$VER/bin/pg_ctl -D ~/pgdata stop

# 导入表结构（幂等；先执行 001 再执行 002）
psql -h 127.0.0.1 -p 5433 -U $USER -v ON_ERROR_STOP=1 \
     -v app_password='local-dev-drone-api' \
     -f ~/drone-navigation/server/migrations/001_init_auth_schema.sql
psql -h 127.0.0.1 -p 5433 -U $USER -d drone_navigation \
     -v ON_ERROR_STOP=1 -f ~/drone-navigation/server/migrations/002_matrix_account.sql
```

## 第 4 节. FastAPI 后端（认证 + 设置 + Matrix 中转）

```bash
cd ~/drone-navigation/server
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install -r requirements.txt
cp config.example.json config.json   # 本地取值：database_url → ...@127.0.0.1:5433/...,
                                     # frontend_base_url → http://localhost:5173,
                                     # cors_origins → ["http://localhost:5173"]
uvicorn app.main:app --reload --port 8000
```

注意：`--reload` 只监听 `.py` 文件 —— 修改 `config.json` 后，用 `touch app/main.py` 强制重载。

**冒烟测试：** `curl http://localhost:8000/api/health` → `{"status":"ok"}`；然后 `My Space -> Account` 注册并登录，在 Settings 保存一次会出现绿色提示条。

## 第 5 节. Synapse（社区聊天）

运行在 `127.0.0.1:8008`，关闭公开注册 —— 网站是唯一入口（用 conda 环境和下面展示的 venv 一样可行）：

```bash
python3 -m venv ~/synapse-venv   # 或：conda create -n synapse python=3.12
~/synapse-venv/bin/pip install matrix-synapse==1.157.1
~/synapse-venv/bin/python -m synapse.app.homeserver \
  --server-name localhost --config-path ~/synapse-data/homeserver.yaml \
  --generate-config --report-stats=no
# 编辑 ~/synapse-data/homeserver.yaml：保留 127.0.0.1:8008 监听器
# （client+admin 资源），确认 `enable_registration: false`

# 启动（后台）
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver \
  -c ~/synapse-data/homeserver.yaml &

# 服务管理员 + 供后端令牌中转使用的 token
~/synapse-venv/bin/register_new_matrix_user \
  -c ~/synapse-data/homeserver.yaml -u admin -p '<pick-a-password>' --admin \
  http://localhost:8008
curl -s -X POST localhost:8008/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password","user":"admin","password":"<same-password>"}'
# 加入 server/config.json，然后 `touch app/main.py`：
#   "synapse": { "base_url": "http://127.0.0.1:8008",
#                "server_name": "localhost",
#                "admin_access_token": "<syt_... token>" }
```

**冒烟测试：** 用两个浏览器 profile 各登录一个账号，`Community -> Chat` 私信双向可达，刷新后聊天记录仍在。

## 第 6 节. OpenClaw（客服）

```bash
npm install -g openclaw          # 或：pnpm add -g openclaw
# 在 ~/.openclaw/openclaw.json 中配置模型提供商 + 网关令牌
# （参考形状见 deployment/openclaw/openclaw.json）
openclaw gateway --port 18789    # 前台运行；要装成守护进程用 `openclaw gateway install`
```

SPA 连接 `ws://127.0.0.1:18789` —— `client/config.json` 中的 `openclaw.token` 必须与 `~/.openclaw/openclaw.json` 中的网关令牌一致。

## 第 7 节. MediaMTX + 摄像头（均原生）

**MediaMTX**（v1.9.0，与 ECS 2 一致）：

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.9.0_linux_amd64.tar.gz
# 建议：在回环地址启用控制 API —— 在 mediamtx.yml 中设置
#   api: yes  和  apiAddress: 127.0.0.1:9997
./mediamtx                   # WHEP/WHIP 端口 :8889，HLS :8888，控制 API :9997
```

**摄像头推流程序**（另开一个终端）：

```bash
cd ~/drone-navigation/extension/simple_webcam
conda activate drone-navigation
MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 \
  LIVESTREAM_ID=crazyflie-drone python simple_webcam.py   # WHIP 推流 'crazyflie-drone'
```

接真实 Crazyflie 无人机时，改由 `extension/crazyflie_bridge/crazyflie_mediamtx.py` 以同一个 `crazyflie-drone` id 发布其摄像头画面，替代 webcam（第 9 节）。

SPA 播放哪一路流由后端在运行时决定（`server/config.json` -> `"mediamtx": { "streams": [...] }`，通过 `GET /api/stream/config` 下发）；该键缺失时，SPA 本地回退为 `http://127.0.0.1:8889/<id>/whep`（生产环境：`https://drone-navigation.com/live/<id>/whep`）。`Livestream Viewer` 子页把目录中的每一路流列为可点击卡片（默认：第一项 `crazyflie-drone`）；推流程序默认指向生产环境 —— 上面的 `MEDIAMTX_URL` / `MEDIAMTX_API` 环境变量把它们指向本地服务器。

**冒烟测试：** `Real Drone -> Livestream Viewer` 播放摄像头画面；绿色的 `crazyflie-drone - HH:MM:SS` 时间戳叠加层在跳动。

## 第 8 节. 全系统冒烟测试

```bash
curl http://localhost:8000/api/health              # {"status":"ok"}
curl http://localhost:5173/_matrix/client/versions # 经 Vite 代理
```

浏览器检查清单 `http://localhost:5173`：

1. `My Space -> Account`：注册 + 登录。
2. `My Space -> Settings`：改一个值，点 `Save` → 绿色“已保存”提示条。
3. `Community -> Chat`：两个账号互发私信；刷新 → 历史仍在。
4. `Community -> Customer Service`：连上本地 OpenClaw 网关。
5. `Real Drone -> Livestream Viewer`（及 `Host`）：播放第 7 节的广播。

## 第 9 节. 真实 Crazyflie 无人机

**第一次接触 Crazyflie？** 请从 [`extension/simple_crazyflie/README.md`](extension/simple_crazyflie/README.md)（英文）开始 —— 它会一步步带你完成：从电脑连接无人机、读取遥测数据，再到让它飞起来。

这里一切原生 —— 唯一的准备是一条一次性 udev 规则，授予用户对 Crazyradio PA 以及 USB 连接的无人机本体的访问权限（用于修改其 EEPROM 身份标识）：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="5740", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-crazyflie.rules
sudo udevadm control --reload && sudo udevadm trigger
lsusb | grep 1915        # Nordic Semiconductor —— 能看到 Crazyradio
```

查找无人机摄像头 IP（`nmap -sn 192.168.0.0/24`，然后逐个浏览 `http://192.168.0.x` 候选地址）直到出现 AI-Deck 直播画面。

**修改无人机的 EEPROM 身份标识**（仅在多架无人机共处一室时需要 —— 相同信道 + 相同地址 = 交叉控制）：用 USB 线连接无人机并运行 provisioning 脚本 —— 它把新的无线信道/地址写入无人机的 EEPROM，并在重新上电后通过无线链路验证：

```bash
cd ~/drone-navigation/extension/crazyflie_bridge
python provision_drone.py --channel 14 --address E7E7E7E707
# -> 然后用以下方式连接：./start_bridge.sh --cf-uri radio://0/14/2M/E7E7E7E707
```

给每架无人机分配不同信道，2M 速率下间隔 ≥2 MHz（例如信道 2、4、6……，地址对应 `E7E7E7E702`、`E7E7E7E703`……）；`--read-only` 只打印当前标识而不写入。

用一个脚本启动整个 bridge（它会自动激活 `drone-navigation` conda 环境）：

```bash
cd ~/drone-navigation/extension/crazyflie_bridge
CRAZYFLIE_IP="192.168.0.110" RADIO_URL="radio://0/80/2M/E7E7E7E7E7" \
TELEMETRY_SERVER="ws://127.0.0.1:8000/api/drone/telemetry/publish" \
MEDIAMTX_URL="http://127.0.0.1:8889" MEDIAMTX_API="http://127.0.0.1:9997" \
  ./start_bridge.sh
#    = video_stream_proxy.py  （在 :8082 转发 http://$CRAZYFLIE_IP/stream）
#    + motion_control_ws.py   （ws://:8765；设置 RADIO_URL 环境变量，或直接传
#      --cf-uri 参数，即可改变电台身份）
#    + telemetry_relay.py     （遥测 + 飞行指令，无人机 <-> FastAPI）
#    + crazyflie_mediamtx.py  （无人机摄像头 -> MediaMTX WHIP，id 为 'crazyflie-drone'）
#    停止：Ctrl+C（按两次强制）—— 若在飞行会先降落。
#    台架安全：CF_NO_FLY=1 拒绝一切起飞（干跑演练）。
#    省略 TELEMETRY_SERVER / MEDIAMTX_* / RADIO_URL 则中继 + 发布
#    到生产环境（drone-navigation.com）。
```

**冒烟测试（不飞行）：** `python e2e_command_check.py` 验证完整指令链路。随后 `Livestream Host` HUD 显示 `Link live | ~20 Hz` 以及真实位置 / 姿态 / 电量，起飞/停止/降落按钮 + Flight 圆盘即可操控无人机。

始终生效的安全规则：

- 在 USB 线上**拒绝起飞**（`usb://*`）；飞行只走 Crazyradio。
- **多机同室：** 每架无人机只在自己 provision 的信道/地址上飞行（步骤见上文）。

遥测路径与视频路径镜像：`motion_control_ws.py` 持有 Crazyflie 链路并在 `ws://127.0.0.1:8765` 广播遥测；`telemetry_relay.py` 把它转发到服务器（`WS /api/drone/telemetry/publish`），服务器再扇出到各浏览器（`WS /api/drone/telemetry`）。在部署的 `server/config.json` 中设置 `"drone": { "telemetry_token": "..." }` 可要求 relay 端提供 `TELEMETRY_TOKEN=<相同值>`（留空 = 开放，本地无妨）。

## 第 10 节. 日常工作流程 + 故障排查

每次会话的启动顺序（每个一个终端）—— 或使用第 11 节的 systemd 服务：

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
# 真实无人机：第 9 节
```

停止：各进程 Ctrl+C；PostgreSQL 用 `pg_ctl -D ~/pgdata stop`。

- Vite 开发服务器保持手动 —— 它是你正在积极开发的前端。
- `drone-fastapi` 保留 `--reload`：`.py` 修改自动生效；修改 `server/config.json` 后 `touch server/app/main.py`（任何 shell 都可以，无需重启）。
- 若 `drone-webcam` 服务（第 11 节）正在运行，不要再手动跑 `simple_webcam.py` —— 那会对同一个流 id 重复推流。

## 第 11 节. 后台服务（可选 —— systemd 用户服务）

完成第 3–7 节后，每个后端都可以作为 systemd **用户**服务运行 —— 开机自启（已启用 user lingering），无需终端：

```bash
cp deployment/local-systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam
```

| 服务 | 作用 | 端口 |
|---|---|---|
| `drone-pg` | PostgreSQL 开发集群（`~/pgdata`） | 5433 |
| `drone-fastapi` | FastAPI 后端（uvicorn `--reload`） | 8000 |
| `drone-synapse` | Matrix Synapse 家庭服务器 | 8008 |
| `drone-mediamtx` | MediaMTX（WHIP/WHEP、HLS、控制 API） | 8889, 8888, 9997 |
| `drone-webcam` | 演示摄像头 → WHIP 推流 | — |
| `openclaw-gateway` | OpenClaw 网关（由 `openclaw gateway install` 自行安装） | 18789 |

管理速查：

```bash
systemctl --user status drone-fastapi         # 状态
journalctl --user -u drone-fastapi -f         # 跟踪日志
systemctl --user restart drone-fastapi        # 重启单个服务
systemctl --user disable --now drone-webcam   # 停止摄像头推流（例如改由真实无人机推流时）
```

维护者桌面的演示日策略：六个服务全部**禁用**，重启后保持关闭 —— 只在需要时手动启动：

```bash
# 演示时拉起整套后端
systemctl --user start drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam openclaw-gateway

# 结束后再关闭
systemctl --user stop drone-pg drone-fastapi drone-synapse drone-mediamtx drone-webcam openclaw-gateway
```

注意：`openclaw-gateway.service` 由 OpenClaw 自己的安装器创建 —— 这里仅为完整起见列出；不要为它拷贝 unit 文件。

## 许可证

完整的最终用户许可协议见 [LICENSE](LICENSE)。

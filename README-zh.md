# 无人机导航（Drone Navigation）

多视角无人机导航仪表盘，融合 3D 空中可视化、2D 地图与任务控制界面。

本指南在 **Windows 10/11 + WSL2 上完整本地运行整个系统** —— 无需任何服务器账号。其他平台与语言：

- Windows 10/11（WSL2）：[English](README.md) | [中文](README-zh.md)
- macOS：[English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu：[English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- 生产部署（阿里云 ECS、Caddy、Tailscale）：[deployment/README.md](deployment/README.md)

## 项目结构

```
drone-navigation/
├── client/       # Vue 3 + Vite 前端（Cesium、Google Maps、Street View）
├── server/       # FastAPI 后端（fastapi-users 认证、设置、Matrix 令牌中转）
├── extension/    # 独立推流/工具（simple_webcam WHIP 推流、crazyflie_bridge）
└── deployment/   # 生产配置与运维文档（Caddy、Squid、OpenClaw、MediaMTX、Synapse）
```

## 在 Windows 上的工作方式（先读这里）

所有服务端组件都运行在 **WSL2 Ubuntu 内部**；你通过 WSL2 的 localhost 转发从 Windows 访问它们 —— 在 WSL 内监听某个端口的服务，可以在 Windows 中通过 `http://localhost:<port>` 访问。

有两个例外：

- **摄像头推流程序运行在原生 Windows Python 上。** WSL2 无法访问笔记本摄像头（没有 `/dev/video0`），所以 `simple_webcam.py` 在 Windows 中运行，并通过 `127.0.0.1:8889`（localhost 转发的 Windows→WSL 方向）把流推进 WSL 内的 MediaMTX。
- **Crazyradio PA 需要 usbipd-win** 把 USB 设备传入 WSL（第 9 节）。

| 组件 | 运行位置 | 端口 |
|---|---|---|
| 客户端（Vite 开发服务器） | WSL | 5173 |
| FastAPI 后端 | WSL | 8000 |
| PostgreSQL 开发集群 | WSL | 5433 |
| Synapse（社区聊天） | WSL | 8008 |
| OpenClaw（客服） | WSL | 18789 |
| MediaMTX（直播） | WSL | 8889, 8888, 9997 |
| simple_webcam 推流程序 | **Windows** | — |
| crazyflie_bridge（真实无人机） | WSL（+ usbipd 电台） | 8082, 8765 |

## 第 1 节. Windows + WSL2 环境准备

在 **Windows PowerShell（管理员）** 中：

```powershell
wsl --install                  # 安装 WSL2 + Ubuntu；按提示重启
wsl --set-default-version 2
```

然后在 **Ubuntu（WSL）终端** 中：

```bash
sudo apt update && sudo apt install -y git curl

# Miniconda
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init bash && source ~/.bashrc

# Node.js LTS
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs

# 克隆到 WSL 的 HOME —— 绝不要放在 /mnt/c 下
# （在 Windows 文件系统上 npm install 慢 10-50 倍）
git clone https://github.com/kandeng/drone-navigation.git ~/drone-navigation
```

检查点：`node -v`、`npm -v`、`conda --version`、`git --version` 都能打印版本号。

## 第 2 节. 客户端（Vue 3 + Vite）

```bash
cd ~/drone-navigation/client
npm install
cp config.example.json config.json   # 填写 googleApiKey、cesiumIonToken、openclaw.token
npm run dev
```

在 **Windows** 浏览器中打开 `http://localhost:5173`（WSL 会转发过来）。API 密钥的前置条件（Google Maps API、Cesium ion）见 [client/README.md](client/README.md)。

**冒烟测试：** `3D Aerial` 地球和 `2D Map` 应立即渲染 —— 它们不依赖后端。随着你完成下面各节，其余页面会逐步可用。

## 第 3 节. PostgreSQL（WSL 内的开发集群，端口 5433）

用户自有的集群，无需 systemd（WSL 的 apt 也会在 5432 端口装一个它自己的集群 —— 忽略它，我们从不碰它）：

```bash
sudo apt install -y postgresql
VER=$(ls /usr/lib/postgresql)        # Ubuntu 22.04 为 14，24.04 为 16

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

**冒烟测试：** `curl http://localhost:8000/api/health` → `{"status":"ok"}` —— 也要**在 Windows PowerShell 里**运行一次；它能证明 WSL→Windows 转发正常。然后在浏览器中：`My Space -> Account` 注册并登录；`My Space -> Settings` 改一个值，`Save` → 绿色提示条。

## 第 5 节. Synapse（社区聊天）

运行在 `127.0.0.1:8008`，关闭公开注册 —— 网站是唯一入口：

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

## 第 7 节. MediaMTX（WSL）+ 摄像头（原生 Windows）

**MediaMTX —— 在 WSL 内：**

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_linux_amd64.tar.gz
tar -xzf mediamtx_v1.9.0_linux_amd64.tar.gz
# 建议：在回环地址启用控制 API —— 在 mediamtx.yml 中设置
#   api: yes  和  apiAddress: 127.0.0.1:9997
./mediamtx                       # WHEP/WHIP 端口 :8889，HLS :8888，控制 API :9997
```

**摄像头推流程序 —— 在原生 Windows 上**（WSL2 没有摄像头设备）：

1. 从 python.org 安装 **Windows 版 Python 3.12**（勾选 "Add python.exe to PATH"）。
2. 把推流程序从 WSL 文件系统拷贝出来（把 `<wsl-user>` 换成你的 WSL 用户名），在 **Windows PowerShell** 中：

```powershell
Copy-Item -Recurse \\wsl.localhost\Ubuntu\home\<wsl-user>\drone-navigation\extension\simple_webcam $HOME\simple_webcam
cd $HOME\simple_webcam
py -m pip install -r requirements.txt    # opencv-python、aiortc、av、aiohttp（均有 Windows wheel）

$env:MEDIAMTX_URL="http://127.0.0.1:8889"
$env:MEDIAMTX_API="http://127.0.0.1:9997"
$env:LIVESTREAM_ID="crazyflie-drone"     # 暂代无人机视频流
py simple_webcam.py
```

Windows 上的 `127.0.0.1:8889` 通过 localhost 转发到达 WSL 内的 MediaMTX。若 Windows Defender 防火墙弹出 Python 提示请允许，并确保 Windows 相机隐私设置允许桌面应用使用相机。

SPA 播放哪一路流由后端在运行时决定（`server/config.json` -> `"mediamtx": { "streams": [...] }`，通过 `GET /api/stream/config` 下发）；该键缺失时，SPA 本地回退为 `http://127.0.0.1:8889/<id>/whep`。`Livestream Viewer` 子页把目录中的每一路流列为可点击卡片（默认：第一项 `crazyflie-drone`）。

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

## 第 9 节. 真实 Crazyflie 无人机（usbipd-win + crazyflie_bridge）

**第一次接触 Crazyflie？** 请从 [`extension/simple_crazyflie/README.md`](extension/simple_crazyflie/README.md)（英文）开始 —— 它会一步步带你完成：从电脑连接无人机、读取遥测数据，再到让它飞起来。

WSL2 默认看不到 USB 设备。用 usbipd-win 把 **Crazyradio PA** 传入 WSL —— 在 **Windows PowerShell（管理员）** 中：

```powershell
winget install usbipd
usbipd list                          # 找到 Crazyradio PA（Nordic，VID 1915 PID 7777）-> 记下 BUSID
usbipd bind --busid <BUSID>          # 一次性，重启后仍有效
usbipd attach --wsl --busid <BUSID>  # 每次重新插拔 / 重启 WSL 后都要重跑
```

在 **WSL** 中授予用户访问权限（一次性），然后验证：

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1915", ATTR{idProduct}=="7777", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-crazyradio.rules
sudo udevadm control --reload && sudo udevadm trigger
lsusb | grep 1915        # Nordic Semiconductor —— 能看到加密狗
# 若 WSL 没有运行 udev（无 systemd）：sudo chmod 0666 /dev/bus/usb/<bus>/<dev>
# （<bus>/<dev> 通过 lsusb 查找）
```

查找无人机摄像头 IP：在 Windows 浏览器中逐个尝试 `http://192.168.0.x` 候选地址（在 WSL 内用 `nmap -sn 192.168.0.0/24` 列出）直到出现 AI-Deck 直播画面 —— WSL 可以直接访问它（出站 LAN 正常）。

**修改无人机的 EEPROM 身份标识**（仅在多架无人机共处一室时需要 —— 相同信道 + 相同地址 = 交叉控制）：用 USB 线连接无人机，像电台一样用 usbipd 把它传入 WSL，然后运行 provisioning 脚本 —— 它把新的无线信道/地址写入无人机的 EEPROM，并在重新上电后通过无线链路验证：

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
```

**冒烟测试（不飞行）：** `python e2e_command_check.py` 验证完整指令链路。随后 `Livestream Host` HUD 显示 `Link live | ~20 Hz` 以及真实位置 / 姿态 / 电量，起飞/停止/降落按钮 + Flight 圆盘即可操控无人机。

始终生效的安全规则：

- 在 USB 线上**拒绝起飞**（`usb://*`）；飞行只走 Crazyradio。（在 WSL 中使用 `usb://0` 也需要先用 usbipd 传入无人机的 USB 线。）
- **多机同室：** 默认 URI 仅供单机使用 —— 按上述步骤给每架无人机 provision 自己的信道/地址，并只在该信道/地址上飞行。

## 第 10 节. 日常工作流程 + 故障排查

每次会话的启动顺序（每个一个 WSL 终端标签页，摄像头在 Windows PowerShell 中）：

```bash
/usr/lib/postgresql/$(ls /usr/lib/postgresql)/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
cd ~/drone-navigation/server && conda activate drone-navigation && uvicorn app.main:app --reload --port 8000
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml &
openclaw gateway --port 18789
~/mediamtx_v1.9.0/mediamtx
cd ~/drone-navigation/client && npm run dev
# Windows PowerShell：cd $HOME\simple_webcam；$env:MEDIAMTX_URL=...；py simple_webcam.py
# 真实无人机：第 9 节（先 usbipd attach）
```

停止：各进程 Ctrl+C；PostgreSQL 用 `pg_ctl -D ~/pgdata stop`。

- **从 Windows 访问 `localhost:<port>` 不通：** 确认进程确实在 WSL 内监听（`ss -tlnp | grep <port>`）；在 PowerShell 中 `wsl --shutdown` 可重置卡死的网络。
- **防火墙提示：** Windows Defender 询问时允许 Python/MediaMTX（专用网络）。
- **`npm install` / 文件操作很慢：** 你在 `/mnt/c/...` 下 —— 把仓库挪到 WSL home（第 1 节）。
- **Windows 推流程序画面黑：** Windows 设置 -> 隐私和安全性 -> 相机 -> 允许桌面应用；相机同时只能被一个应用占用 —— 关掉 Teams/Zoom/相机应用。
- **从 Windows 编辑 WSL 文件：** 用 `\\wsl.localhost\Ubuntu\home\<wsl-user>\...`（VS Code 的 WSL 扩展最顺手）。

## 许可证

完整的最终用户许可协议见 [LICENSE](LICENSE)。

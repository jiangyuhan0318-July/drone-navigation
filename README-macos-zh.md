# 无人机导航 —— macOS

多视角无人机导航仪表盘，融合 3D 空中可视化、2D 地图与任务控制界面。

本指南在 **macOS 上原生运行整个系统**（Apple Silicon 与 Intel）—— 无需服务器账号，无需虚拟机。其他平台与语言：

- Windows 10/11（WSL2）：[English](README.md) | [中文](README-zh.md)
- macOS：[English](README-macos.md) | [中文](README-macos-zh.md)
- Ubuntu：[English](README-ubuntu.md) | [中文](README-ubuntu-zh.md)
- 生产部署（阿里云 ECS、Caddy、Tailscale）：[deployment/README.md](deployment/README.md)

macOS 其实是最顺的路径：一切都原生运行（没有 WSL 层、没有 USB 透传），包括摄像头推流程序和 Crazyradio。macOS 特有的注意点只有 Homebrew 路径、相机权限弹窗，以及电台所需的 `libusb`。

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

## 第 1 节. macOS 环境准备

```bash
xcode-select --install            # 命令行工具（git、编译器）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install git node postgresql@14 libusb
# libusb：pyusb/cflib 与 Crazyradio 通信所需 —— macOS 上
# 没有 usbipd 的等价物；USB 原生可用。

# Miniconda（安装包方式 —— 与 Linux 指南保持 shell 一致）
curl -LO https://repo.anaconda.com/miniconda/Miniconda3-latest-MacOSX-arm64.sh   # Intel：...-MacOSX-x86_64.sh
bash Miniconda3-latest-MacOSX-arm64.sh -b -p ~/miniconda3
~/miniconda3/bin/conda init zsh && source ~/.zshrc

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

这里**不要**用 `brew services` —— 我们像 Linux 指南一样跑一个用完即弃的用户集群（以下路径为 Apple Silicon；Intel 请把 `/opt/homebrew` 换成 `/usr/local`）：

```bash
# 一次性初始化（localhost trust 认证，端口 5433）
/opt/homebrew/opt/postgresql@14/bin/initdb -D ~/pgdata -U $USER -E UTF8 --auth=trust
printf "port = 5433\nunix_socket_directories = '$HOME/pgdata'\n" >> ~/pgdata/postgresql.conf

# 启动 / 停止
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata stop

# 导入表结构（幂等；先执行 001 再执行 002）
psql -h 127.0.0.1 -p 5433 -U $USER -v ON_ERROR_STOP=1 \
     -v app_password='local-dev-drone-api' \
     -f ~/drone-navigation/server/migrations/001_init_auth_schema.sql
psql -h 127.0.0.1 -p 5433 -U $USER -d drone_navigation \
     -v ON_ERROR_STOP=1 -f ~/drone-navigation/server/migrations/002_matrix_account.sql
```

（`psql` 位于 `/opt/homebrew/opt/postgresql@14/bin/psql` —— 把它加入 PATH 或使用完整路径。）

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

## 第 7 节. MediaMTX + 摄像头（均原生）

**MediaMTX**（二进制 tarball 让配置文件就在它旁边；`brew install mediamtx` 也可以）：

```bash
mkdir ~/mediamtx_v1.9.0 && cd ~/mediamtx_v1.9.0
# Apple Silicon：darwin_arm64；Intel：darwin_amd64
curl -LO https://github.com/bluenviron/mediamtx/releases/download/v1.9.0/mediamtx_v1.9.0_darwin_arm64.tar.gz
tar -xzf mediamtx_v1.9.0_darwin_arm64.tar.gz
# 建议：在回环地址启用控制 API —— 在 mediamtx.yml 中设置
#   api: yes  和  apiAddress: 127.0.0.1:9997
./mediamtx                       # WHEP/WHIP 端口 :8889，HLS :8888，控制 API :9997
# 若 Gatekeeper 拦截该二进制：xattr -d com.apple.quarantine ./mediamtx
```

**摄像头推流程序**（原生 —— 与 WSL 不同，相机直接可用）：

```bash
cd ~/drone-navigation/extension/simple_webcam
conda activate drone-navigation   # 依赖已在第 4 节装好
MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 \
  LIVESTREAM_ID=crazyflie-drone python simple_webcam.py
```

首次运行时 macOS 会要求授予**终端的相机权限**（系统设置 -> 隐私与安全性 -> 相机 —— 启用 Terminal/iTerm/VS Code，然后重启终端）。流以 `crazyflie-drone` 发布，暂代真实无人机。

SPA 播放哪一路流由后端在运行时决定（`server/config.json` -> `"mediamtx": { "streams": [...] }`，通过 `GET /api/stream/config` 下发）；该键缺失时，SPA 本地回退为 `http://127.0.0.1:8889/<id>/whep`。

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

无需 USB 透传 —— 插上 **Crazyradio PA** 即可用（第 1 节的 `libusb` 提供用户态驱动；无需 udev 规则，无需 sudo）：

```bash
system_profiler SPUSBDataType | grep -A3 1915   # Crazyradio PA 已就位
```

查找无人机摄像头 IP（`nmap -sn 192.168.0.0/24`，或逐个浏览 `http://192.168.0.x` 候选地址）直到出现 AI-Deck 直播画面。

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
```

**冒烟测试（不飞行）：** `python e2e_command_check.py` 验证完整指令链路。随后 `Livestream Host` HUD 显示 `Link live | ~20 Hz` 以及真实位置 / 姿态 / 电量，起飞/停止/降落按钮 + Flight 圆盘即可操控无人机。

始终生效的安全规则：

- 在 USB 线上**拒绝起飞**（`usb://*`）；飞行只走 Crazyradio。
- **多机同室：** 默认 URI 仅供单机使用 —— 按上述步骤给每架无人机 provision 自己的信道/地址，并只在该信道/地址上飞行。

**手势识别与控制（本地、免费、毫秒级）：** 手势服务吃视频流（默认本地摄像头；无人机接上后切共享 RTSP），任何程序或 OpenClaw agent 都能查询当前手势：

```bash
cd ~/drone-navigation/extension
./start_gesture.sh              # 手势服务 :8700 + 执行器（默认 dry-run 只打日志）
./start_gesture.sh --live       # 真发命令（需 gate 打开 + 无人机在线）
curl http://127.0.0.1:8700/gesture   # → {"gesture":"thumb_up","confidence":0.93,...}
```

映射表（`extension/gesture_control.py` 的 `MAP`）：👍 起飞 / ✌️ 降落 / 🖐 急停 / ✊ 悬停 / ☝️ 向前 / 👎 向后 / 🤟 向左 / 👌 向右（方向移动 0.3 m）。

- 手势**只是感知/触发输入**，飞行动令仍走 `/api/copilot/command` 门控链路 —— 不会绕过飞行门控。
- 🖐 急停、✌️ 降落、✊ 悬停不受门控限制（永远可恢复，安全通道）。
- OpenClaw 侧已注册 skill：`~/.openclaw/skills/drone-gesture/`（agent 查手势用）。

## 第 10 节. 日常工作流程 + 故障排查

每次会话的启动顺序（每个一个终端标签页）：

```bash
/opt/homebrew/opt/postgresql@14/bin/pg_ctl -D ~/pgdata -l ~/pgdata.log start
cd ~/drone-navigation/server && conda activate drone-navigation && uvicorn app.main:app --reload --port 8000
nohup ~/synapse-venv/bin/python -m synapse.app.homeserver -c ~/synapse-data/homeserver.yaml &
openclaw gateway --port 18789
~/mediamtx_v1.9.0/mediamtx
cd ~/drone-navigation/extension/simple_webcam && MEDIAMTX_URL=http://127.0.0.1:8889 MEDIAMTX_API=http://127.0.0.1:9997 LIVESTREAM_ID=crazyflie-drone python simple_webcam.py
cd ~/drone-navigation/client && npm run dev
cd ~/drone-navigation/extension && ./start_gesture.sh   # 手势识别（可选，见第 9 节）
# 真实无人机：第 9 节
```

停止：各进程 Ctrl+C；PostgreSQL 用 `pg_ctl -D ~/pgdata stop`。

- **画面黑 / `cv2.VideoCapture(0)` 失败：** 终端缺少相机权限（第 7 节），或另一个应用（Zoom/FaceTime/Photo Booth）占着相机。
- **`psql: command not found`：** 使用完整的 `/opt/homebrew/opt/postgresql@14/bin/` 路径，或加入 PATH（`brew link --force postgresql@14`）。
- **Apple Silicon 与 Intel 路径：** Homebrew 前缀分别是 `/opt/homebrew`（M 系列）和 `/usr/local`（Intel）—— 全文对应替换。
- **端口被占用：** 用 `lsof -i :<port>` 找占用者；某些 macOS 版本上 AirPlay 接收器会占用 5000/7000，但与本技术栈的端口无关。

## 许可证

完整的最终用户许可协议见 [LICENSE](LICENSE)。

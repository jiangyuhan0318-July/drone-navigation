# Drone Navigation

[English](README_NEW.md) | [中文](README_NEW_zh.md)

> 📘 **详细安装指南（原版）** → [Windows/WSL](README.md) · [macOS](README-macos.md) · [Ubuntu](README-ubuntu.md) · [生产部署](deployment/README.md)

一个全栈无人机导航与控制平台，集成 3D 空中可视化、实时遥测、AI 手势/坐姿/跌倒/身体动作识别，以及自然语言副驾驶控制——全部在一个浏览器仪表盘中完成。

## 概述

Drone Navigation 是一套用于远程操控和监控 Crazyflie 无人机的集成系统，提供：

- **3D 与 2D 可视化** — Cesium 地球 3D 空中视图，Google Maps 2D 导航，以及街景级别影像
- **AI 视觉守护中心** — 通过摄像头实时识别手势、坐姿、跌倒和身体动作，并自动执行无人机指令
- **自然语言副驾驶** — 基于 OpenClaw 的 AI 助手，通过聊天即可控制无人机和守护中心
- **实时视频推流** — 基于 WHIP/WHEP 的低延迟视频，来自无人机摄像头或本地摄像头，经由 MediaMTX
- **社区聊天** — 基于 Matrix 的实时消息系统，支持飞手之间交流
- **智能客服** — 基于 OpenClaw 的智能客服机器人

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  浏览器 (http://localhost:5173)                                  │
│  Vue 3 + Vite + Cesium + Google Maps                             │
│  3D空中 │ 2D地图 │ 实机操控 │ 聊天 │ 设置 │ 副驾驶              │
└──────┬───────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  FastAPI 后端 (:8000)                                            │
│  认证 │ 遥测 │ 飞控指令 │ 设置 │ 副驾驶 API                      │
│  安全门控 │ Matrix Token 中介 │ 推流配置                         │
└──────┬───────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  扩展层                                                          │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ Crazyflie 桥接  │  │ 守护中心 (:8705)                     │   │
│  │ • 运动控制      │  │ • 手势识别 (👍✌️🖐✊☝️👎🤟👌)           │   │
│  │ • 遥测中继      │  │ • 坐姿守护 (头部前倾检测)            │   │
│  │ • 视频代理      │  │ • 跌倒检测 (状态机)                  │   │
│  │ • MediaMTX WHIP │  │ • 身体动作 (T字/交叉/举手)           │   │
│  └─────────────────┘  │ • 统一执行器 → 无人机动作            │   │
│                        └──────────────────────────────────────┘   │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐   │
│  │ 简易摄像头      │  │ AI 模型                              │   │
│  │ WHIP 发布器     │  │ • YOLOv8n (物体检测)                  │   │
│  └─────────────────┘  │ • MediaPipe 姿态/人脸/手势            │   │
│                        └──────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
       │
┌──────▼───────────────────────────────────────────────────────────┐
│  基础设施                                                        │
│  PostgreSQL │ Synapse (Matrix) │ MediaMTX │ OpenClaw │ Caddy     │
└──────────────────────────────────────────────────────────────────┘
```

## 核心功能

### 🛸 无人机控制
- 起飞、降落、急停、悬停及方向飞行
- 实时遥测：位置、姿态、电量、链路质量
- 基于航点的飞行规划与高度门控
- 云台控制和航拍
- 多无人机信道分配与管理

### 🤖 AI 视觉守护中心 (v2)
**一个进程、一个端口 (:8705)、一路摄像头** — 四种检测模式随时切换：

| 模式 | 检测内容 | 无人机动作 |
|------|---------|-----------|
| ✋ **手势** | 点赞 / 剪刀手 / 张开手掌 / 握拳 / 食指上指 / 倒赞 / 摇滚手势 / OK | 起飞 / 降落 / 急停 / 悬停 / 方向飞行 |
| 🪑 **坐姿** | 头部前倾 ≥16° 持续 2s | 自动起飞 0.5m |
| 🧍 **跌倒** | 跌倒状态机确认 | 自动起飞 0.5m |
| 🙌 **身体动作** | 双手举起 / 双臂交叉 / T字展开 | 急停 / 降落 / 姿态控制模式 |

- **网页仪表盘** `http://127.0.0.1:8705/` — 实时 MJPEG 视频 + 模式按钮 + 状态面板
- **Dry-run 模式** 安全测试；`--live` 参数启用实机指令
- 安全门控：起飞需飞行门控通过 + 电量 ≥ 3.5V

### 💬 AI 副驾驶 (OpenClaw)
用自然语言控制整个系统：
- "切到手势模式" / "查看无人机状态" / "起飞 0.5 米"
- 技能：守护中心、身体动作控制、手势控制、坐姿守护、跌倒守护
- 通过 FastAPI 副驾驶端点接入完整指令链路

### 🌍 可视化
- **3D 空中视图** — Cesium 地球，自定义瓦片源、高度可视化、碰撞警告
- **2D 地图视图** — Google Maps，航点选择、飞行路径规划
- **街景视图** — 地面视角集成

### 🔴 直播推流
- MediaMTX 低延迟视频 (WHIP/WHEP/WebRTC)
- 支持无人机摄像头或本地摄像头作为视频源
- 直播观看和主播 HUD 叠加

## 项目结构

```
drone-navigation/
├── client/                    # Vue 3 + Vite 前端
│   ├── src/
│   │   ├── views/             # 页面组件 (空中/地图/聊天/设置等)
│   │   ├── 2d_map/            # Google Maps 集成
│   │   ├── 3d_street/         # 街景集成
│   │   └── router/            # 单页应用路由
│   ├── composables/           # Vue 组合式函数 (遥测/认证/Matrix等)
│   ├── components/            # 可复用 UI 组件 (HUD/Dock/Disk等)
│   └── icons/                 # SVG 图标库
├── server/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py            # FastAPI 应用入口
│   │   ├── drone_commands.py  # 飞控指令分发 + 安全门控
│   │   ├── telemetry.py       # 遥测 WebSocket 中继
│   │   ├── copilot.py         # 副驾驶 API 端点
│   │   ├── safety.py          # 飞行安全规则
│   │   ├── users.py           # 用户管理 (fastapi-users)
│   │   ├── matrix_auth.py     # Matrix Token 中介
│   │   └── settings.py        # 用户设置 API
│   └── migrations/            # PostgreSQL 迁移脚本
├── extension/                 # 独立无人机 + 视觉服务
│   ├── guard_center.py        # 守护中心: 四合一 AI 检测 + 仪表盘
│   ├── guard_control.py       # 统一执行器: 检测 → 无人机指令
│   ├── gesture_recognizer.py  # 手势识别 (MediaPipe)
│   ├── posture_guardian.py    # 坐姿监测
│   ├── fall_recognizer.py     # 跌倒检测状态机
│   ├── action_recognizer.py   # 身体动作识别 (T字等)
│   ├── crazyflie_bridge/      # Crazyflie 无人机桥接
│   │   ├── motion_control_ws.py    # WebSocket 运动控制
│   │   ├── telemetry_relay.py      # 遥测转发
│   │   ├── video_stream_proxy.py   # 摄像头流代理
│   │   └── provision_drone.py      # EEPROM 烧录工具
│   ├── simple_crazyflie/      # Crazyflie 逐步教程
│   ├── simple_webcam/         # WHIP 摄像头发布器 (Windows)
│   ├── models/                # AI 模型 (MediaPipe 任务文件, YOLOv8)
│   └── copilot/               # OpenClaw 技能定义
├── deployment/                # 生产部署配置
│   ├── caddy/                 # Caddy 反向代理
│   ├── fastapi/               # 后端 systemd 服务
│   ├── mediamtx/              # MediaMTX 配置
│   ├── synapse/               # Matrix Synapse 服务
│   ├── squid/                 # Squid 代理配置
│   └── openclaw/              # OpenClaw 网关配置
└── docs/                      # 平台专用安装指南
    ├── README.md              # Windows/WSL 安装 (英文)
    ├── README-zh.md           # Windows/WSL 安装 (中文)
    ├── README-macos.md        # macOS 安装 (英文)
    ├── README-macos-zh.md     # macOS 安装 (中文)
    ├── README-ubuntu.md       # Ubuntu 安装 (英文)
    └── README-ubuntu-zh.md    # Ubuntu 安装 (中文)
```

## 快速开始

### 前置条件

- **Windows 10/11** + WSL2 Ubuntu (推荐) — 或 macOS / Ubuntu 原生
- **Python 3.12+**、**Node.js LTS**、**PostgreSQL**、**Conda**
- **Crazyflie 无人机** + Crazyradio PA（可选 — 支持模拟模式）

### 1. 克隆并安装

```bash
git clone https://github.com/kandeng/drone-navigation.git
cd drone-navigation

# 后端
cd server
conda create -n drone-navigation python=3.12 -y
conda activate drone-navigation
pip install -r requirements.txt
cp config.example.json config.json  # 填入你的配置

# 前端
cd ../client
npm install
cp config.example.json config.json  # 填入 googleApiKey, cesiumIonToken
```

### 2. 启动服务

```bash
# 终端 1: PostgreSQL
pg_ctl -D ~/pgdata -l ~/pgdata.log start

# 终端 2: 后端
cd server && uvicorn app.main:app --reload --port 8000

# 终端 3: 前端 (开发模式)
cd client && npm run dev

# 可选: MediaMTX 视频推流
./mediamtx

# 可选: 守护中心 AI 视觉控制
cd extension && bash start_guard.sh --mode=gesture --live
```

### 3. 打开浏览器

访问 `http://localhost:5173` — 3D 地球立即加载。注册账号、配置无人机，即可开始飞行。

## AI 模型

预置模型（已包含在 `extension/` 中）：

| 模型 | 文件 | 大小 | 用途 |
|------|------|------|------|
| YOLOv8n | `yolov8n.pt` | 6.5 MB | 物体检测 |
| MediaPipe Pose | `pose_landmarker_lite.task` | 5.8 MB | 身体姿态估计 |
| MediaPipe Face | `face_landmarker.task` | 3.8 MB | 人脸网格检测 |
| MediaPipe Gesture | `gesture_recognizer.task` | 8.4 MB | 手势识别 |

## 平台支持

| 平台 | 安装指南 |
|------|---------|
| Windows 10/11 (WSL2) | [README.md](README.md) · [中文](README-zh.md) |
| macOS | [README-macos.md](README-macos.md) · [中文](README-macos-zh.md) |
| Ubuntu | [README-ubuntu.md](README-ubuntu.md) · [中文](README-ubuntu-zh.md) |
| 生产部署 (阿里云 ECS) | [deployment/README.md](deployment/README.md) |

## 社区与副驾驶

- **Matrix 聊天**: 通过 Synapse 家庭服务器内置的社区消息功能
- **智能客服**: OpenClaw 驱动的 AI 客服机器人
- **飞行副驾驶**: AI 副驾驶，自然语言控制无人机，带安全护栏

## 安全机制

- USB 线缆连接时禁止起飞（仅允许无线电模式）
- 紧急停止 (`estop`) 始终可用，绕过所有门控
- 起飞电量下限 3.5V
- 多无人机：分配独立信道，间距 ≥ 2 MHz
- Dry-run 模式 (`CF_NO_FLY=1`) 用于桌面测试 — 拒绝所有起飞指令
- 配置/Token 值永不打日志或打印到终端

## 许可证

详见 [LICENSE](LICENSE) 完整最终用户许可协议。

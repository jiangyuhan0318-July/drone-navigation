# AI 飞行副驾驶（/copilot）实现说明

> 总结 `http://localhost:5173/copilot` 这个页面从聊天框到无人机螺旋桨的完整实现。
> 涉及代码：前端 `CopilotView.vue`（新增）、后端 `copilot.py`（新增）+ 两个小改动、
> agent 侧 `extension/copilot/`（新增，未提交）。

## 一、页面是什么

一个「聊天开飞机」的界面，分三块：

| 区块 | 内容 | 数据源 |
|---|---|---|
| 左：AI 聊天 | 与 OpenClaw agent 对话（"查询无人机状态""起飞"） | WS `127.0.0.1:18789`（OpenClaw 网关） |
| 右：飞行许可 | 人工专用开关（`gate`），关闭时 agent 只能查询、不能动飞机 | `GET/PUT /api/copilot/gate` |
| 右：实时遥测 | Link 频率 / X,Y,Z / 姿态 / 电量 | WS `localhost:8000/api/drone/telemetry` |
| 右：实时画面 | 无人机摄像头直播 | MediaMTX WHEP（首条流目录） |

## 二、端到端链路

```
用户打字"起飞"
  → CopilotView.vue → useOpenClaw → ws://127.0.0.1:18789（OpenClaw 网关）
    → agent 模型（zai/glm-5v-turbo，fallback deepseek-v4-flash）
      → drone-copilot 技能（extension/copilot/skill/SKILL.md）
        → 调用 copilot_ctl.py command takeoff
          → POST /api/copilot/command（FastAPI）
            → _validate 白名单+钳位 → 飞行许可闸门检查
              → drone_commands.forward_command()
                → WS /api/drone/command/downlink
                  → telemetry_relay.py command_forwarder()
                    → motion_control_ws.py ws://:8765 → _dispatch_command
                      → MotionCommander → Crazyradio → 飞机起飞
```

反向（遥测）复用现成管道：`飞机 → motion_control_ws → telemetry_relay → 服务端扇出 →
useDroneTelemetry(ws://:8000/api/drone/telemetry) → 面板刷新`。

关键设计：**agent 和浏览器 HUD 走同一条已验证命令路径**（`forward_command`），
没有给 LLM 单独开旁路。

## 三、逐文件实现要点

### 1. 前端 `client/src/views/CopilotView.vue`（新增，576 行）

- **复用共享骨架**：`ViewComposer` 布局 + `useDockRegistry`/`usePageRegistry` 注册页面。
  页面入口两处：`router/index.js` 加懒加载路由 `/copilot`；
  `AerialView.vue` 的 `registerPage({ id:'copilot', route:'/copilot' })` 让它在主菜单"页面"里出现。
- **聊天**：直接用现成共享 composable `useOpenClaw.js`（客服页同款）。它封装了
  OpenClaw 网关协议：`connect.challenge` 握手 → `connect`（role=operator，scopes
  operator.read/write，token 鉴权）→ `sessions.list/create` → `chat.send`；
  流式渲染 `partial` → `final` 消息；过滤网关心跳 `HEARTBEAT_OK`；3s~30s 指数退避重连。
- **飞行许可**：`GET/PUT /api/copilot/gate`。前端只是开关 UI —— **强制在服务端**，
  前端断网或造假都不影响安全。
- **遥测**：共享单例 `useDroneTelemetry.js`（Real Drone HUD 同款）。模块级单例跨页面保活；
  2s 重连 + 10s 握手看门狗 + 30s 静默探活 + 2.5s 陈旧判定 `linked`；每秒滚动计算 Hz。
- **视频**：`useStreamConfig`（服务端 `/api/stream/config` 下发流目录，首条为 primary）
  + `createWhepPlayer`（复用 Real Drone 的 WHEP 播放器，`attach()` 可跨页面复用同一路 PeerConnection）。
- **i18n**：`CopilotView.zh.i18n.json` / `.en` 两份，页面文案全部走 `t()`。

### 2. 后端 `server/app/copilot.py`（新增，151 行）

薄 REST 层，复用现有 `drone_commands` / `telemetry` 模块，四个路由：

| 路由 | 作用 |
|---|---|
| `GET /api/copilot/gate` | 读闸门状态 |
| `PUT /api/copilot/gate` | 设闸门 —— **只能人来按**（agent 工具没有此能力） |
| `GET /api/copilot/status` | 一调用汇总：闸门 + 链路健康 + 遥测快照 + 直播流目录（agent 最常用的入口） |
| `POST /api/copilot/command` | 发一条飞行命令，返回 `delivered` + `reason` + 最新遥测快照 |

实现要点：

- **飞行许可闸门**：`_FLIGHT_ACTIONS = {takeoff, move, up, down, forward, back, left, right}`
  全部被闸门拦截；`land/stop/estop` **永不受限** —— 救机动作永远可用。
- **闸门持久化**：写到 `server/data/copilot_gate.json`（"on"/"off"）—— 服务重启不会静默复飞。
- **命令校验复用**：`drone_commands._validate` 与浏览器 HUD 完全同一条路径：
  - takeoff 高度钳位 **0.1–1.5 m**（默认 0.5）
  - move 速度 **±0.5 m/s**，yawrate **±120°/s**
  - 单步距离 **0.05–1.0 m**（默认 0.2）
  - 未知 action → 400 拒绝
- **状态合并**：`telemetry.snapshot()` + `drone_commands.downlink_connected()` +
  `telemetry.publisher_connected()` —— 后两个是给 copilot 加的两个小 helper。
- **认证**：`config.json → drone.telemetry_token`，设置了就必须带 `?token=`；
  当前本地是空串 = 开放（生产必须设）。

### 3. 服务端小改动（给 copilot 打的桩）

- `server/app/drone_commands.py`（+23 行）：`downlink_connected()` 判断 relay 是否挂载；
  `forward_command(cmd)` 把已验证命令写进 downlink WS（带日志）。
- `server/app/telemetry.py`（+10 行）：`publisher_connected()`、`snapshot()`（最近一帧各分类）。
- `server/app/main.py`（+4 行）：`include_router(copilot_router, prefix="/api")`。

### 4. agent 侧 `extension/copilot/`（新增）

- **`copilot_ctl.py`**（纯标准库，零依赖）：agent 的 CLI 工具。
  `status` / `command <takeoff|move|forward|...>`，输出 JSON 供模型解析；
  `BATTERY_FLOOR_V = 3.5` 本地先拦一次低电量起飞（与服务端闸门形成双保险）。
- **`skill/SKILL.md`**（frontmatter `name: drone-copilot`）：技能定义，包含
  命令清单 + 8 条安全规则（先查闸门、查电量、一次一个动作、`delivered=false` 时把
  `reason` 原样报给用户、任务结束必须 `land`、estop 仅紧急）。
- **挂载方式**：`~/.openclaw/openclaw.json` → `skills.load.extraDirs` 指向
  `/Users/gaowenbo/drone-navigation/extension/copilot/skill` —— 网关启动时加载。

### 5. 同批但无关的改动（别被迷惑）

- `server/app/matrix_admin.py`：httpx → aiohttp 迁移（聊天账号管理，与 copilot 无关）。
- `client/package.json`：`allowScripts`（npm 安装策略）。
- `client/public/splash/`、`simple_crazyflie/*`：其他实验。

## 四、安全设计（LLM 乱来也飞不起来）

1. **闸门只能人开**：agent 工具集里只有 `POST command`，没有 `PUT gate`；
   闸门状态落盘，服务重启默认恢复"关"。
2. **服务端强制校验**：白名单 + 数值钳位（高度/速度/距离），不合法直接 400 ——
   模型编造的离谱参数到不了飞机。
3. **恢复动作永不拦截**：land / stop / estop 不受闸门限制，任何时候都能救机。
4. **诚实报告**：`delivered: false` 必须带 `reason`（`flight_gate_off` / `no drone link`），
   技能规则强制 agent 原样转述，禁止谎称已执行。
5. **底层叠加**：桥接侧还有现有安全层兜底 —— 移动看门狗（0.5s 不刷新自动悬停）、
   USB 线互锁拒飞、`CF_NO_FLY=1` 干跑模式。

## 五、一次"起飞"的完整旅程（时序）

1. 用户输入"起飞" → `handleSend` → `chat.send`（WS 18789）
2. agent 按 SKILL.md 先跑 `copilot_ctl.py status` → 确认 `gate.enabled=true`、电量 ≥3.5V
3. `copilot_ctl.py command takeoff --height 0.5` → `POST /api/copilot/command`
4. 服务端 `_validate` → 闸门检查 → `forward_command` → downlink WS
5. `telemetry_relay.py` → 写进 bridge WS → `motion_control_ws._dispatch_command`
   → MotionCommander 进入上下文 → 起飞到 0.5m
6. 响应回传：`{delivered: true, action: "takeoff", telemetry: {...}}` → agent 汇报"已起飞"
7. 面板：遥测开始跳动（Link Hz 有值）、视频出画面

## 六、运行依赖清单

| 层 | 需要什么 |
|---|---|
| 前端 | Vue3/Vite + vue-i18n（复用）；`client/config.json` 里 `openclaw.url/token` 与网关一致 |
| OpenClaw | 网关 `--port 18789`；`~/.openclaw/openclaw.json` 配置模型（GLM-5V-Turbo）+ `extraDirs` 技能目录 |
| 后端 | FastAPI :8000；`/api/copilot/*` 已注册；drone_commands/telemetry helper 就位 |
| 无人机链路 | `start_bridge.sh` 四进程（motion_control_ws :8765 + relay + 视频代理/推流）；真机 + Crazyradio |
| 验证 | `extension/crazyflie_bridge/e2e_command_check.py`（无浏览器全链自检）；`GET /api/copilot/status`（无真机可查闸门/链路） |

## 七、如何扩展

- 加新命令：`drone_commands._validate` 加白名单分支 → `motion_control_ws._dispatch_command`
  加动作 → `copilot_ctl.py` 加 argparse 子命令 → SKILL.md 补示例。
- 换模型/网关：改 `~/.openclaw/openclaw.json`，前端无感知。
- 上生产：必须设 `telemetry_token`（前端暂不支持带 token 的 copilot API 调用，需同步改造）。

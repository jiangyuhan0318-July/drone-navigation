# 项目总结 — 守护中心四合一 (手势/坐姿/跌倒/身体动作)

> 生成时间: 2026-08-07
> 范围: drone-navigation 项目中「守护中心」相关全部工作

---

## 1. 一句话概况

**一个进程、一个端口 (:8705)、一路摄像头、一次只跑一个检测 (四选一)** —
把手势遥控、坐姿监护、跌倒响应、身体动作控制集成进统一守护中心;
网页仪表盘 = 实时视频 + 状态面板 + 模式切换按钮, **切模式即检测+控制一起换,
视频流不断**; 副驾驶 (OpenClaw) 可用自然语言切换模式。

---

## 2. 模式 → 无人机动作对照表 (用户定义, 最终语义)

| 模式 | 检测到 | 无人机动作 | 门控 |
|---|---|---|---|
| ✋ 手势 | 👍 Thumb_Up | 起飞 0.5m | 受门控 |
| ✋ 手势 | ✌️ Victory | 降落 | 可恢复 |
| ✋ 手势 | 🖐 Open_Palm | **急停 estop** | 可恢复 |
| ✋ 手势 | ✊ Closed_Fist | 悬停 | 可恢复 |
| ✋ 手势 | ☝️ Pointing_Up | 向前 0.3m | 受门控 |
| ✋ 手势 | 👎 Thumb_Down | 向后 0.3m | 受门控 |
| ✋ 手势 | 🤟 ILoveYou | 向左 0.3m | 受门控 |
| ✋ 手势 | 👌 OK | 向右 0.3m | 受门控 |
| 🪑 坐姿 | 头前倾 ≥16° 持续 2s / 距离过近 | **起飞 0.5m** | 受门控+电量护栏 |
| 🧍 跌倒 | 摔倒确认 (跌倒状态机) | **起飞 0.5m** | 受门控+电量护栏 |
| 🙌 动作 | 双手举起 (hands_up) | **急停 estop** | 可恢复 |
| 🙌 动作 | 双臂交叉 (arms_crossed) | **降落 land** | 可恢复 |
| 🙌 动作 | T字展开 (t_pose) | 切换姿态控制模式 (姿态状态机, 不直接飞) | — |

事件规则: 姿态/手势持握 ≥1000ms 且置信度 ≥0.65 触发一次; 触发后 2500ms 冷却;
目标丢失立即清零。

---

## 3. 架构

```
┌─────────────────────────────────────────────────────────┐
│ 浏览器: http://127.0.0.1:8705/                          │
│   实时视频 (MJPEG <img>) + 模式按钮 + 四路状态卡片        │
└──────────────┬──────────────────────────────────────────┘
               │ PUT /mode {"mode":"..."}  (按钮/HTTP/副驾驶)
┌──────────────▼──────────────────────────────────────────┐
│ guard_center.py (:8705, 单进程)                          │
│   摄像头(30fps) → MediaPipe → 当前模式唯一检测            │
│   切模式: fsm 重置 + 四路状态清空, 视频流不断              │
│   端点: / /status /mode /gesture /posture /fall /action  │
│          /video (MJPEG 带骨架/姿势标注) /health           │
└──────────────┬──────────────────────────────────────────┘
┌──────────────▼──────────────────────────────────────────┐
│ guard_control.py (统一执行器, 单进程)                     │
│   读 /status 当前模式 → 自动消费对应模式事件 → 上升沿触发  │
│   dry-run 默认只打日志; --live 真发                       │
│   estop/land/stop 不受门控; takeoff 受门控+电量≥3.5V护栏  │
└──────────────┬──────────────────────────────────────────┘
               │ POST /api/drone/action
┌──────────────▼──────────────────────────────────────────┐
│ server (uvicorn :8000, app/main.py)                      │
│   /api/drone/action  飞行动令 (confirm 门控)             │
│   /api/pose/event    t_pose 姿态状态机                   │
│   /api/copilot/status 电量等遥测                         │
└──────────────────────────────────────────────────────────┘
```

四个独立服务保留 (:8700 手势 / :8703 坐姿 / :8704 跌倒 / :8706 动作),
用于单独调试; 与守护中心互斥 (摄像头独占, ctl 已内置保护)。

---

## 4. 文件清单

### 核心 (extension/)
| 文件 | 说明 |
|---|---|
| `guard_center.py` | 守护中心: 四选一检测 + 仪表盘 + MJPEG 视频 |
| `guard_control.py` | **统一执行器** (四模式合一, 自动跟随模式切换) |
| `start_guard.sh` | 启动/停止: 中心 + 统一执行器 (--mode / --live / --stop) |
| `gesture_recognizer.py` / `gesture_control.py` | 独立手势服务 (:8700) |
| `posture_guardian.py` / `posture_control.py` | 独立坐姿服务 (:8703) |
| `fall_recognizer.py` / `fall_control.py` | 独立跌倒服务 (:8704) |
| `action_recognizer.py` / `action_control.py` | 独立身体动作服务 (:8706) |

### 副驾驶 (OpenClaw skills)
| 文件 | 说明 |
|---|---|
| `~/.openclaw/skills/guard-center/` | SKILL.md + guard_ctl.py (status/start/stop/mode) |
| `~/.openclaw/skills/body-action-control/` | SKILL.md + action_ctl.py (独立版调试) |

### 服务端 (server/app/)
| 文件 | 说明 |
|---|---|
| `drone_commands.py` | 替换为桌面版 580 行超集: /api/drone/action、pending-action、gesture/pose 事件, 并恢复 downlink_connected() + forward_command() (copilot/safety 依赖) |

---

## 5. 使用方法

### 网页 (首选)
```bash
bash start_guard.sh --mode=action --live   # 启动, 真发模式
open http://127.0.0.1:8705/                # 仪表盘
```
网页上: 点模式按钮切检测+控制; 看实时视频/骨架/当前姿势。

### 副驾驶 (OpenClaw 自然语言)
- 「开守护中心」→ start
- 「切到坐姿/测跌倒/开动作检测/用手势」→ mode <name>
- 「检测状态」→ status
- 「关掉」→ stop
- 真发模式: `guard_ctl.py start --live --mode=X`

### 直接命令
```bash
bash start_guard.sh --mode=posture --live   # 坐姿模式, 真发
curl -X PUT :8705/mode -d '{"mode":"fall"}' # 切模式
curl http://127.0.0.1:8705/status           # 状态 JSON
```

---

## 6. 关键参数与调优

| 参数 | 默认 | 说明 |
|---|---|---|
| `POSTURE_LEAN_DEG` | 16.0 | 坐姿头前倾阈值 (原 11° 太灵敏, 已调低) |
| `POSTURE_HOLD_MS` | 2000 | 坐姿异常持续判定 (原 700ms, 已调低) |
| 动作持握/冷却 | 1000ms / 2500ms | 身体动作触发条件 |
| `BATTERY_FLOOR_V` | 3.5 | 起飞前电量下限 (guard_control) |
| `GUARD_PORT` | 8705 | 守护中心端口 |

---

## 7. 踩过的坑 (防再犯)

1. **macOS 摄像头字符串陷阱**: `cv2.VideoCapture("0")` 打不开,
   必须 `cv2.VideoCapture(0)` (int)。新写识别器一律对纯数字 source 转 int,
   并带启动重试 10 次 + 断流自动重开。
2. **Safari 不渲染 MJPEG**: `<video>` 标签黑屏 → 用 `<img src="/video">`。
3. **start_*.sh 末尾 `wait` 永久阻塞**: 自动化调用一律 `nohup ... &`,
   ctl 脚本用 subprocess.Popen 异步, 不能同步等。
4. **pkill 竞态**: pkill 后垂死进程仍被 pgrep 匹配 → 启动脚本误判
   "already running" 跳过。重启脚本时先等 1s 或双次 pkill。
5. **模式切换状态残留**: 切模式必须重置 fsm + 清空四路状态 + 清空
   执行器事件记忆 (guard_control 的 last_ev), 否则旧模式事件跨模式触发。
6. **守护中心补起执行器**: guard_ctl mode 子命令只 PUT /mode,
   统一执行器自动跟随; 执行器没跑时补起 (不再按模式起独立执行器)。
7. **配置/令牌**: token 值永不打印到终端/日志 (项目纪律); config.json
   不提交 Git、不发给他人。
8. **OpenClaw 网关**: 不绑定 0.0.0.0 (安全要求)。

---

## 8. 当前运行状态 (2026-08-07)

- guard_center :8705, **action 模式**, 30fps, **dry-run** (安全)
- guard_control 统一执行器已挂, 跟随模式切换 (已验证: posture→action 秒切)
- server :8000 全部端点 200

### 待办 / 建议
- [ ] dry-run 下逐模式实测 (摆姿势验证识别) → 确认后 `--live` 真发
- [ ] 实机飞行测试 (无人机在门控环境)
- [ ] (可选) 若真发确认稳定, 可将记忆文件 drone-navigation-project.md 的
      守护中心条目同步为本总结的最终形态

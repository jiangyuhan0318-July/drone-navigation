---
name: drone-copilot
description: 通过 copilot API 控制 Crazyflie 无人机（状态查询/起飞/降落/悬停/移动），AI 飞行副驾驶与无人机之间的命令桥。用户要求控制无人机、查询无人机状态、执行飞行任务时使用本技能。
---

# Drone Copilot（无人机副驾驶）

本技能让 agent 通过 FastAPI copilot API 控制 Crazyflie 无人机，链路：

```
copilot_ctl.py -> POST /api/copilot/command -> WS downlink
  -> telemetry_relay.py -> motion_control_ws.py -> Crazyflie
```

**服务器（drone-navigation 后端）已对命令做白名单校验和数值钳位，并强制检查"飞行许可"闸门——只有人类在副驾驶面板打开许可后，飞行类命令才会被转发。**

## 环境

- 解释器：`~/miniconda3/envs/drone-navigation/bin/python`
- 脚本：`{baseDir}/../copilot_ctl.py`
- 无需真机在线也能查询 `status`（闸门/链路/遥测/直播流）

## 命令

所有命令都会输出 JSON，直接解析使用。

```bash
# 1. 总览：闸门状态 + 桥接链路 + 最新遥测 + 直播流
python {baseDir}/../copilot_ctl.py status

# 2. 起飞并悬停（默认 0.5m，安全范围 0.1-1.5m）
python {baseDir}/../copilot_ctl.py command takeoff --height 0.5

# 3. 降落 / 悬停 / 急停
python {baseDir}/../copilot_ctl.py command land
python {baseDir}/../copilot_ctl.py command stop
python {baseDir}/../copilot_ctl.py command estop   # 紧急电机停转，飞机会坠落，仅紧急时用

# 4. 速度移动（米/秒，范围 ±0.5；yawrate 度/秒 范围 ±120）
python {baseDir}/../copilot_ctl.py command move --vx 0.2 --vy 0.1 --vz 0 --yawrate 30

# 5. 单步移动（距离 0.05-1.0m）
python {baseDir}/../copilot_ctl.py command forward --distance 0.5
python {baseDir}/../copilot_ctl.py command up --distance 0.3
```

## 安全规则（必须遵守）

1. **飞行许可**：任何飞行命令（takeoff/move/up/down/forward/back/left/right）前，先 `status`
   确认 `gate.enabled`。若为 `false`：**停下并明确告诉用户"请先在副驾驶面板打开飞行许可"**，
   不要重试、不要绕过、不要猜测。
2. **电量**：`takeoff` 前检查 `telemetry.battery.voltage`，低于 3.5V 拒绝起飞（脚本也会拦）。
3. **高度与速度**：高度默认 0.5m，不主动超过 1.5m；单步距离默认 0.5m 以内；move 速度 ≤0.3m/s 为宜。
4. **一次一个动作**：等待上一个命令的 JSON 响应后再发下一个，不并行发命令。
5. **诚实报告**：命令响应的 `delivered` 为 `false` 时，把 `reason`（如 `flight_gate_off`、
   `no drone link`）原样告诉用户，不要谎称已执行。
6. **任务收尾**：飞行任务结束必须 `land`；用户喊"停"时先 `stop` 悬停再询问。
7. **estop 仅限紧急**：失控、即将撞人撞物时使用，并立即告知用户。
8. 遥测以 API 返回为准，**不要编造**位置/电量数据。

## 典型对话示例

用户："看看飞机状态" → `status`，把 `gate`/`link`/`telemetry` 转述给用户。
用户："起飞" → `status` 查闸门和电量 → 闸门开则 `takeoff --height 0.5`，汇报 `delivered`。
用户："往前进一点" → `forward --distance 0.5`，汇报结果。
用户："降落" → `land`。

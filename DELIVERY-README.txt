════════════════════════════════════════════════════════
  drone-navigation 交付包 · 必读说明
  打包时间: 2026-08-07
════════════════════════════════════════════════════════

一、这个包是什么
────────────────────────────────────────────────────────
AI 飞行副驾驶链路: OpenClaw agent → copilot API → 桥接 → Crazyflie
+ 本地视觉守护中心 (手势/坐姿/跌倒/身体动作 四合一, 单进程单端口 :8705)

二、本包相对原仓库的新增内容
────────────────────────────────────────────────────────
1. 守护中心四合一 (extension/):
   - guard_center.py  四选一检测 + HTML 仪表盘 (实时视频/模式按钮/状态面板)
   - guard_control.py 统一执行器 (切模式=检测+控制一起换, 视频不断)
   - start_guard.sh   一键启动/停止
   - 四个独立服务保留: 手势(:8700) 坐姿(:8703) 跌倒(:8704) 动作(:8706)
2. 模式 → 无人机动作 (可在仪表盘网页切换, 或用副驾驶自然语言):
   手势  👍起飞 ✌️降落 🖐急停 ✊悬停 ☝️前 👎后 🤟左 👌右
   坐姿  坐姿不端正 → 起飞 0.5m
   跌倒  摔倒确认 → 起飞 0.5m
   动作  🙌双手举起→急停  🙅双臂交叉→降落  ⭐T字→姿态状态机
   起飞类受飞行门控+电量(≥3.5V)护栏; 急停/降落/悬停不受限。
3. OpenClaw skills (放 ~/.openclaw/skills/ 下):
   guard-center / body-action-control / gesture-control /
   posture-guardian / fall-guardian

三、运行前必须做的
────────────────────────────────────────────────────────
1. 配置文件: 本项目不包含任何已填写的 config.json。
   请复制示例后自行填写:
     cp server/config.example.json server/config.json
     cp client/config.example.json client/config.json
   (填写内容: 服务器地址、token 等 — 不要使用他人配置!)
2. 客户端依赖:
     cd client && npm install
3. 模型文件: extension/models/ 已包含
   (gesture_recognizer.task / pose_landmarker_lite.task / face_landmarker.task)
   + extension/yolov8n.pt, 均已含在包内, 无需额外下载。

四、启动步骤 (参考 README-zh.md)
────────────────────────────────────────────────────────
1. 服务端:     cd server && uvicorn app.main:app --port 8000
2. 桥接 (接真机): 按 README 环境变量 + start_bridge.sh
3. 守护中心:  cd extension && bash start_guard.sh --mode=action --live
   仪表盘:    浏览器打开 http://127.0.0.1:8705/
4. 副驾驶:    OpenClaw 网关 + skills (见各 SKILL.md)

五、注意事项
────────────────────────────────────────────────────────
- 摄像头: macOS 上同一时刻只能一个进程占用摄像头; 独立服务与守护中心互斥。
- 坐姿灵敏度: 默认 16°/2s (环境变量 POSTURE_LEAN_DEG / POSTURE_HOLD_MS 可调)。
- 视频流: Safari 用 <img> 显示 MJPEG; Chrome/Edge 均可。
- 本包已排除: 个人 config.json、日志、node_modules、媒体素材、.git。
  不含任何个人密钥/凭据/真实 IP。
════════════════════════════════════════════════════════

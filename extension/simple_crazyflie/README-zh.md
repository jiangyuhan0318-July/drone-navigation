# simple_crazyflie —— 连接、读取遥测、飞行

[English](README.md) | 中文

本目录中的脚本修改自 Bitcraze 官方教程
[《Step-by-Step: Connecting, logging and parameters》](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/user-guides/sbs_connect_log_param/)，
**直接使用 cflib** —— 无需服务器、无需 MediaMTX、无需浏览器。四个现成脚本，按以下顺序运行：

1. `01_connect.py` —— 验证无线链路可用
2. `02_telemetry.py` —— 实时读取无人机的传感器数据
3. `03_propellers.py` —— 验证每个螺旋桨的方向
4. `04_flying.py` —— 解锁、起飞、悬停并降落

当三个脚本都按下文描述正常工作后，即可进阶到
[`../crazyflie_bridge`](../crazyflie_bridge) 的完整网站流水线。

组装 Crazyflie 2.1 请参考官方指南
[《Getting started with the Crazyflie 2.0 or Crazyflie 2.1(+)》](https://www.bitcraze.io/documentation/tutorials/getting-started-with-crazyflie-2-x/)。

---

## 0. 准备工作（只需做一次）

**硬件**

- Crazyflie 2.x，电池已充电，处于开机状态，放置在平整开阔的表面上
- Crazyradio PA 已插入本机的 USB 口

**软件**

- 激活 conda 环境：`conda activate drone-navigation`
  （环境中已包含 cflib；若没有则 `pip install cflib`）
- 在 Linux 上安装 USB 权限规则，以便免 `sudo` 访问 ——
  具体命令见 `deployment/README.md` §5.1（各平台 README 中也有）。
  完成后拔插一次 Crazyradio。

**无线 URI**

- 每个脚本顶部都定义了 `URI` 常量，出厂默认值为
  `radio://0/80/2M/E7E7E7E7E7`。
- 如果无人机的 EEPROM 身份曾用 `provision_drone.py` 修改过，请把三个脚本中的
  该常量改为一致（`radio://0/<信道>/2M/<地址>`）。
- 通过 USB 线读取当前身份：
  `python ../crazyflie_bridge/provision_drone.py --read-only`

---

## 1. 连接 —— `python 01_connect.py`

最小的端到端验证：通过无线电连接、读取电池电压、断开。

**预期输出：**

```
Link open: True
Battery: 3.97 V  (fly only if >= 3.9 V)
Disconnected cleanly.
```

打印出以上内容，说明无线电、权限和 URI 全部正确 —— 后续每一步
（以及生产环境的 bridge）都建立在此基础上。

**故障排查：**

| 现象 | 原因 / 处理 |
|---|---|
| `Cannot find a Crazyradio USB dongle` | 未插无线电，或 udev 规则缺失 / 未重新加载 |
| 连接超时（`Too many packets lost`） | URI 错误、无人机未开机或无线干扰 —— 重新核对 EEPROM 身份 |
| 偶尔打印 `Battery: 0.00 V` | 参数刷新与连接建立发生竞争 —— 重新运行即可 |

---

## 2. 读取遥测 —— `python 02_telemetry.py`

连接后先自报家门，然后把 `stabilizer.estimator` 参数从 2 改回 1
（演示参数读写），接着以 100 Hz 连续打印稳定器的
roll / pitch / yaw，持续 5 秒。

**预期输出：**

```
Yeah, I'm connected! :D
Now I will disconnect :'(
The crazyflie has parameter stabilizer.estimator set at number: 2
The crazyflie has parameter stabilizer.estimator set at number: 1
[1234][Stabilizer]: {'stabilizer.roll': 0.42, 'stabilizer.pitch': -0.15, 'stabilizer.yaw': 3.1}
[1244][Stabilizer]: {'stabilizer.roll': 0.40, ...}
... (100 lines per second, stops by itself after 5 s)
```

**边运行边做健全性检查：** 拿起无人机并倾斜 —— roll、pitch、yaw
应立即随之变化。这证明 无人机 → 无线电 → Python 的双向链路完全畅通。

说明：

- 角度单位为度。
- 脚本 5 秒后自动退出，可随时重复运行。

---

## 3. 检查螺旋桨 —— `python 03_propellers.py`

**每次飞行前都要做** —— 螺旋桨装反或电机转向错误会导致无人机起飞即翻覆。

脚本通过 `motorPowerSet` 参数逐个驱动每个电机约 2.5 秒，由你对照
下图观察每个螺旋桨的转向 —— 目视确认是这里最可靠的方法，因为
单个小螺旋桨的偏航反作用力矩远低于陀螺仪的振动噪声底限
（自动陀螺仪判定在该固件上已被验证不可靠）。

逐个转动之后，脚本会做一次约 20 厘米的短暂悬停。这能捕捉到转动
检查发现不了的故障：螺旋桨上下装反（转向正确但没有升力）。

如果固件未暴露 `motorPowerSet` 参数，脚本会跳过逐个转动，直接
进行悬停检查。

**电机布局（X 型配置，俯视图）：**

```
             前
        M4 (CW)    M1 (CCW)
             \    /
              \  /
              /  \
             /    \
        M3 (CCW)   M2 (CW)
             后
```

同时确认 M2 和 M4 使用的是顺时针（CW）桨叶，M1 和 M3 使用的是逆时针（CCW）桨叶，参考下图：

![Crazyflie 螺旋桨类型](../assets/crazyflie_propellers.png)
![Crazyflie 结构示意图](../assets/crazyflie_diagram.png)

**预期现象：** 每个电机依次单独转动（控制台会打印当前测试哪个
电机及预期转向），随后是一次短暂的低空悬停。

若某电机转向错误，断开电源并更换该螺旋桨（或检查桨叶类型 —— CW 和
CCW 桨叶形状不同）。若某电机完全不转，检查其接线 —— 导线被折断或
被夹住是常见原因。反复运行直到全部正确。

---

## 4. 飞行 —— `python 04_flying.py`

**先做安全检查：**

- 电池 ≥ 3.9 V（第 1 步会告诉你）
- 各方向至少 2 米净空，无人员、宠物
- **用电池飞行** —— 拔掉所有 USB 线（ tether 会把无人机拽下来）
- 手指放在 `Ctrl+C` 附近，并清楚无人机电源开关的位置

**脚本行为：** 解锁无人机；用 3 秒缓坡起飞到 0.3 米；悬停 5 秒；然后降落并上锁。
全程以 20 Hz 发送悬停设定值，走完整的飞控管线 —— 与螺旋桨检查里的
悬停验证使用同一套机制。

> **说明：** 本演示不做横向飞行。悬停设定值只指令零横向速度，但没有
> 位置反馈，所以无人机可能缓慢横向漂移 —— 请保持周围空旷。
> 高度保持本身工作良好：Flow 甲板的测距传感器（`range.zrange`）
> 状态正常，驱动高度控制器。

**预期现象：**

- 控制台：`Arming ...`、`Taking off ...`、`Hovering ...`、`Landing ...`。
- 无人机：平稳爬升到约 30 厘米，稳定悬停 5 秒，然后缓缓降落。

**正常停止：** 随时按 `Ctrl+C` —— 脚本会立即切断电机并上锁。

**紧急停止 —— 立即切断电机（即使在空中）：**

1. **拔掉电脑上的 Crazyradio**。固件的 commander 看门狗检测到链路丢失，
   约 1 秒内切断电机。这是最快的急停方式 —— 但无人机会像石头一样掉下来，
   所以飞行区域下方要铺柔软、空旷的缓冲物。
2. **`Ctrl+C`** —— 较慢（受控降落需要几秒钟），但对硬件温和得多。
   还能控制局面时优先用这个。
3. **拨动无人机电源开关** —— 仅在无人机落地或被缠住后使用；
   切勿伸手触碰旋转的螺旋桨。

在你自己的脚本里，相当于"拔无线电"的软件写法是
`scf.cf.commander.send_stop_setpoint()` —— 立即将推力清零。
任何紧急停止之后，再次飞行前请重启无人机电源（并重新插好无线电）。

**通过无线电完全关机：** cflib 的 `PowerSwitch` 工具可以把整架无人机彻底关掉 ——
`PowerSwitch(URI).platform_power_down()` 会同时关闭*两颗* MCU，
效果与按电源按钮完全一样（该命令由无线电 MCU 处理，因此即使飞行固件
卡死也有效）。在空中触发，无人机会直接坠落到地面。而且一旦关机，
无线电就再也叫不醒它：只能走到无人机跟前按电源按钮才能重新开机 ——
恢复必须有物理接触。如需*可恢复*的急停，改用 `stm_power_down()`
（飞行 MCU 与甲板断电，无线电 MCU 保持在线），之后用 `stm_power_up()`
或 `stm_power_cycle()` 远程唤醒 —— 无需物理接触。注意：一个
Crazyradio 同一时间只能服务一个程序，所以要**先停掉
`04_flying.py`（或 bridge）** —— `Ctrl+C` 会释放无线电 ——
然后在另一个空闲终端里执行关机命令。

如果无人机在空中而来不及走完上述流程，**直接拔无线电**：
看门狗约 1 秒内切断电机，脚本会自行退出。

经验法则：无人机在空中时，永远优先选择*可恢复*的手段 ——
拔无线电、`send_stop_setpoint()`、`stm_power_down()` 都留有回头路
（重新连接、重新解锁、再次飞行）。`platform_power_down()` 是不归路：
只对走得到的无人机使用。

**如果提示无人机处于 LOCKED supervisor 状态：** 说明上一次飞行
出了状况 —— 无人机还在空中时电机被切断，或发生坠机/翻滚。
本固件会锁存一个安全锁（`supervisor.info` 第 6 位），
无线电无法解除：重启无人机电源后重新运行脚本即可。飞行脚本
通过长缓坡降落、并在停机前持续发送 z=0 高度保持设定值，
正是为了避免触发这个锁。任何坠机之后，再次飞行前请检查螺旋桨
（是否装到位、有无裂纹或桨叶弯曲）—— 损坏的桨会让无人机
起飞时翻跟头。

---

## 5. 下一步

- **完整网站流水线** —— [`../crazyflie_bridge`](../crazyflie_bridge)：
  `./start_bridge.sh` 会把同样的遥测数据推送到 Livestream Host HUD，
  把 AI-Deck 视频桥接到 MediaMTX，并接受来自浏览器的飞行指令。
  生产部署指南：`deployment/README.md` §5。
- **更深入的 cflib 教程** —— Bitcraze 的
  [分步指南](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/user-guides/sbs_connect_log_param/)
  更详细地覆盖了同样的 连接 → 日志 → 飞行 路径。

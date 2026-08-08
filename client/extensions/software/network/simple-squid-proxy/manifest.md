# A Simple Squid Proxy

跨平台配置 HTTP_PROXY / HTTPS_PROXY / NO_PROXY 环境变量操作指南

## 文档说明
- 适配系统：Windows 10/11、macOS Ventura及以上、Ubuntu 22.04/24.04、iOS 16+、Android 13+
- 示例代理网关地址：`http://10.0.0.5:3128`
- 示例免代理白名单：`localhost,127.0.0.1,10.*,192.168.*,*.local`
- 重要概念区分：
  1. **操作系统环境变量**：仅命令行工具生效（curl、npm、git、Python、Docker等），和系统图形界面代理相互独立。
  2. **系统图形界面网络代理**：仅浏览器、桌面软件走代理，终端程序不会读取该配置。
- 业务提示：全局持久化代理环境变量会劫持整机所有软件网络流量，企业终端用户场景应尽量避免。

---

## 一、Windows 10 / Windows 11
### 1.1 临时会话变量（关闭终端自动失效）
#### CMD 命令行
```cmd
set HTTP_PROXY=http://10.0.0.5:3128
set HTTPS_PROXY=http://10.0.0.5:3128
set NO_PROXY=localhost,127.0.0.1,10.*,192.168.*,*.local

# 校验变量是否生效
echo %HTTP_PROXY%
echo %NO_PROXY%

# 清空临时代理配置
set HTTP_PROXY=
set HTTPS_PROXY=
set NO_PROXY=
```

#### PowerShell
```powershell
# 设置代理
$env:HTTP_PROXY="http://10.0.0.5:3128"
$env:HTTPS_PROXY="http://10.0.0.5:3128"
$env:NO_PROXY="localhost,127.0.0.1,10.*,192.168.*,*.local"

# 校验
$env:HTTP_PROXY

# 清空代理
Remove-Item Env:HTTP_PROXY
Remove-Item Env:HTTPS_PROXY
Remove-Item Env:NO_PROXY
```

### 1.2 永久环境变量配置
#### 图形界面操作步骤
1. 快捷键 `Win + R`，输入 `sysdm.cpl` 回车
2. 切换到「高级」选项卡 → 点击底部「环境变量」
3. 分为两个配置区域：
   - 用户变量：仅当前登录用户生效（推荐，无需管理员权限）
   - 系统变量：整机所有用户、后台服务全部生效（会污染整机网络，企业用户不推荐）
4. 点击「新建」，依次添加以下3个变量：

| 变量名 | 变量值 |
| ---- | ---- |
| `HTTP_PROXY` | `http://10.0.0.5:3128` |
| `HTTPS_PROXY` | `http://10.0.0.5:3128` |
| `NO_PROXY` | `localhost,127.0.0.1,10.*,192.168.*,*.local` |

5. 全部弹窗保存，重启所有终端窗口配置才能生效。

#### PowerShell 脚本（仅当前用户永久生效）
```powershell
[Environment]::SetEnvironmentVariable("HTTP_PROXY", "http://10.0.0.5:3128", "User")
[Environment]::SetEnvironmentVariable("HTTPS_PROXY", "http://10.0.0.5:3128", "User")
[Environment]::SetEnvironmentVariable("NO_PROXY", "localhost,127.0.0.1,10.*,192.168.*,*.local", "User")
```

### 1.3 Windows 系统图形代理（仅浏览器生效）
1. `Win + I` 打开设置 → 网络和 Internet → 代理
2. 关闭「自动检测设置」
3. 在手动设置代理区域，点击「设置」
4. 开启「使用代理服务器」，填写代理地址和端口
5. 将免代理域名填入「对于以下地址不使用代理」输入框
6. 保存配置

---

## 二、macOS（Ventura 13 / Sonoma 14 / Sequoia 15）
新版macOS默认Shell为Zsh，旧系统使用Bash。

### 2.1 终端临时会话变量
```bash
export HTTP_PROXY=http://10.0.0.5:3128
export HTTPS_PROXY=http://10.0.0.5:3128
export NO_PROXY=localhost,127.0.0.1,10.*,192.168.*,*.local

# 校验
echo $HTTP_PROXY

# 清空代理
unset HTTP_PROXY HTTPS_PROXY NO_PROXY
```

### 2.2 永久Shell环境变量
#### Zsh（新款macOS默认）
1. 打开终端，编辑配置文件
```bash
nano ~/.zshrc
```
2. 在文件末尾追加以下内容
```bash
# 标准大写代理变量
export HTTP_PROXY=http://10.0.0.5:3128
export HTTPS_PROXY=http://10.0.0.5:3128
export NO_PROXY=localhost,127.0.0.1,10.*,192.168.*,*.local
# 小写兼容变量，适配curl/wget工具
export http_proxy=http://10.0.0.5:3128
export https_proxy=http://10.0.0.5:3128
export no_proxy=localhost,127.0.0.1,10.*,192.168.*,*.local
```
3. 保存退出：`Ctrl+O` → 回车 → `Ctrl+X`
4. 立即重载配置
```bash
source ~/.zshrc
```

#### Bash（老旧macOS系统）
编辑 `~/.bash_profile`，粘贴上述相同代理配置内容即可。

### 2.3 macOS 图形界面网络代理（仅浏览器生效）
1. 点击左上角苹果图标 → 系统设置 → 网络
2. 选中当前Wi-Fi/以太网 → 点击「详细信息」
3. 左侧栏选择「代理」
4. 勾选「网页代理(HTTP)」、「安全网页代理(HTTPS)」
5. 填写代理IP与端口，免代理域名填入「对这些主机忽略代理设置」
6. 点击好 → 应用保存

### 2.4 一键开关代理别名（添加至 ~/.zshrc）
```bash
proxy_on() {
  export HTTP_PROXY=http://10.0.0.5:3128
  export HTTPS_PROXY=http://10.0.0.5:3128
  export NO_PROXY=localhost,127.0.0.1,10.*,192.168.*,*.local
  export http_proxy=$HTTP_PROXY
  export https_proxy=$HTTPS_PROXY
  export no_proxy=$NO_PROXY
  echo "代理已开启"
}
proxy_off() {
  unset HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy
  echo "代理已关闭"
}
```
使用方式：输入 `proxy_on` 开启代理，`proxy_off` 关闭代理。

---

## 三、Ubuntu 22.04 / 24.04 Linux 系统
### 3.1 临时会话变量
```bash
# 大写标准变量
export HTTP_PROXY=http://10.0.0.5:3128
export HTTPS_PROXY=http://10.0.0.5:3128
export NO_PROXY=localhost,127.0.0.1,10.*,192.168.*,*.local
# 小写兼容变量
export http_proxy=http://10.0.0.5:3128
export https_proxy=http://10.0.0.5:3128
export no_proxy=localhost,127.0.0.1,10.*,192.168.*,*.local
```

### 3.2 当前用户永久变量（仅登录用户生效）
Ubuntu默认Shell为Bash
1. 编辑用户Shell配置
```bash
nano ~/.bashrc
```
2. 在文件末尾追加全部代理export语句
3. 重载配置立即生效
```bash
source ~/.bashrc
```

### 3.3 整机全局变量（所有用户/后台服务，高风险，不推荐）
会影响系统更新、Docker、全部后台程序，企业业务场景禁止使用。
```bash
sudo nano /etc/environment
```
文件内添加以下内容：
```ini
HTTP_PROXY="http://10.0.0.5:3128"
HTTPS_PROXY="http://10.0.0.5:3128"
NO_PROXY="localhost,127.0.0.1,10.*,192.168.*,*.local"
http_proxy="http://10.0.0.5:3128"
https_proxy="http://10.0.0.5:3128"
no_proxy="localhost,127.0.0.1,10.*,192.168.*,*.local"
```
需要重启服务器全局配置才会完全生效。

### 3.4 GNOME桌面图形代理（仅浏览器生效）
1. 打开设置 → 网络 → 网络代理
2. 模式切换为「手动」
3. 填写HTTP/HTTPS代理地址和端口
4. 免代理域名填入「忽略主机」输入框
5. 点击应用到整机

### 3.5 校验代理状态
```bash
# 打印所有代理环境变量
env | grep -i proxy
# 测试外网连通性
curl -I https://github.com
```

---

## 四、iOS（iPhone / iPad iOS 16及以上）
### 核心限制
iOS**不支持系统全局环境变量 `HTTP_PROXY` / `HTTPS_PROXY`**，仅能给单条Wi-Fi配置手动代理；蜂窝网络无原生代理，企业设备需MDM管理才能开启。

### Wi-Fi代理分步配置
1. 打开设置 → Wi-Fi
2. 点击已连接Wi-Fi右侧蓝色 ⓘ 图标
3. 滑到页面底部「HTTP代理」→ 点击「配置代理」
4. 选择「手动」
5. 服务器：`10.0.0.5`，端口：`3128`
6. 代理需要账号密码时，开启鉴定并填写用户名、密码
7. 点击存储

### 使用限制
- 仅当前Wi-Fi下的Safari、Chrome等网页App生效
- 终端、开发类软件无法读取代理环境变量
- 手机蜂窝流量完全绕过代理规则

---

## 五、Android 13 / 14 安卓系统
### 核心限制
安卓无整机全局代理环境变量，代理绑定单独Wi-Fi网络；蜂窝流量原生不支持代理，需Root或第三方工具。

### 原生Pixel手机操作步骤
1. 设置 → 网络和互联网 → 互联网（Wi-Fi列表）
2. 点击已连接Wi-Fi右侧齿轮图标 → 修改网络
3. 展开高级选项
4. 代理下拉框选择「手动」
5. 代理主机名：`10.0.0.5`，代理端口：`3128`
6. 保存网络配置

### 国产手机通用路径（小米/三星/一加等）
设置 → WLAN → 长按已连接Wi-Fi → 修改网络 → 显示高级选项 → 代理

### 使用限制
- 仅当前Wi-Fi下浏览器生效
- Termux终端无法继承系统Wi-Fi代理，需单独配置Shell变量
- 蜂窝流量完全不使用代理

### Termux终端单独配置代理
Termux内临时会话代理：
```bash
export HTTP_PROXY=http://10.0.0.5:3128
export HTTPS_PROXY=http://10.0.0.5:3128
export NO_PROXY=localhost,127.0.0.1
```
将上述代码写入 `~/.bashrc` 可实现Termux永久代理。

---

## 六、全平台代理校验命令
### Linux / macOS 终端
```bash
env | grep -E "(HTTP_PROXY|HTTPS_PROXY|NO_PROXY)"
curl -v https://github.com
```

### Windows CMD
```cmd
echo %HTTP_PROXY%
curl -I https://github.com
```

### Windows PowerShell
```powershell
$env:HTTP_PROXY
Invoke-WebRequest https://github.com -UseBasicParsing
```

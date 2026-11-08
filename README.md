# 为无头设备添加串流支持（By Deepseek_V4_Pro_Max）
> WARNING:初版方案，可能存在未知bug(画面抖动？），请见谅

让一台没有显示器的 NVIDIA Kepler 老卡（如 GT 730）主机实现：

- 🖥️ **虚拟显示器**：纯 Python 生成 EDID 注入驱动，桌面/应用全部由 GPU 硬件渲染（1080p/1200p/多屏任意分辨率）
- 🖼️ **VNC 远程桌面**：x11vnc 共享 GPU 渲染画面，开机自启、自动适配显示器号与认证
- 🎮 **Moonlight 低延迟串流**：Sunshine + 硬件编码 60fps + 音频同步 + 虚拟键鼠
- 🔧 **全套踩坑修复**：驱动、音频、鼠标、电源管理的最优配置

> 适用环境：NVIDIA (GT 730）/ Debian 13（trixie） / 6.12 kernel / headless
## 目录

```
├── vdisplay/                 # 虚拟显示器软件（Python 包：EDID 生成 / Xorg 配置 / CLI）
├── systemd/                  # 开机自启服务单元
├── tests/                    # EDID 结构单元测试
├── install.sh                # 安装脚本
├── install-all.sh            # 完整部署脚本（Release 附带）
├── configs/                  # 全套配置模板（Sunshine / x11vnc / 输入 / 音频 / 电源）
├── docs/
│   ├── driver-470-on-debian13.md   # Kepler 闭源驱动 470 在 Debian 13 的安装
│   ├── sunshine-moonlight.md       # 串流搭建、配对 API、编码器选型
│   └── troubleshooting.md          # 音频杂音 / 鼠标后端 / 画面波动 修复记录
└── README.md
```

## 快速开始（全新机器从零到可用）

1. **安装 470 驱动**（Kepler 最后支持的闭源驱动）：[docs/driver-470-on-debian13.md](docs/driver-470-on-debian13.md)
2. **创建虚拟显示器**：
   ```bash
   cd nvidia-vdisplay && sudo sh install.sh
   sudo vdisplay apply --restart-display
   sudo vdisplay status        # 应看到虚拟屏 connected
   ```
3. **（可选）VNC 远程桌面**：见 [configs/x11vnc-wrapper.sh](configs/x11vnc-wrapper.sh) 与 [configs/x11vnc.service](configs/x11vnc.service)
4. **Moonlight 串流**：见 [docs/sunshine-moonlight.md](docs/sunshine-moonlight.md)
5. **优化输入/音频/电源**：套用 [configs/](configs/) 下模板，详见 [docs/troubleshooting.md](docs/troubleshooting.md)

## 技术要点速览

| 模块 | 关键决策 | 原因 |
|---|---|---|
| 驱动 | 470.256.02 来自 bookworm-backports + apt 优先级固定 | trixie 仓库已移除 470；bpo 版为 6.12 内核打过补丁 |
| 虚拟显示 | ConnectedMonitor + CustomEDID 注入 | 无物理显示器时让 X 驱动认为"插着屏幕" |
| 编码器 | **Intel iGPU VAAPI**（而非 Kepler NVENC） | Kepler 第一代 NVENC 不支持现代 FFmpeg 所需特性 |
| 音频 | PipeWire 大缓冲 + 48kHz 直通 + 虚拟 sink | 消除重采样毛刺与网络抖动下的欠载 |
| 输入 | 开放 /dev/uinput + libinput InputClass | Sunshine 虚拟键鼠需要 uinput 创建真实设备 |
| 会话 | 强制 X11（非 Wayland） | 虚拟连接器方案仅支持 X11 |
| 电源 | 屏蔽挂起/DPMS/锁屏/变暗 | 无头常开场景 |

## vdisplay 软件用法

安装后提供 `vdisplay` 命令：

```bash
sudo vdisplay status                          # 查看虚拟屏与 GPU 状态
sudo nano /etc/nvidia-vdisplay/config.ini     # 修改分辨率 / 增加多屏
sudo vdisplay apply --restart-display         # 应用并重启显示管理器
sudo vdisplay disable --restart-display       # 回退
vdisplay generate 1920 1080 60 -o edid.bin    # 单独生成一个 EDID 文件
```

多屏配置示例（`/etc/nvidia-vdisplay/config.ini`）：

```ini
[global]
gpu_busid = auto

[display:DFP-0]
width = 1920
height = 1200
rate = 60

[display:DFP-1]
width = 1280
height = 720
rate = 60
```

虚拟屏自动左右拼接。GT 730 像素时钟上限约 400MHz，最高支持 2560x1440@60 或 3840x2160@30（不支持 4K60）。

**原理**：纯 Python 生成合法 EDID（模拟真实显示器）→ 注入 NVIDIA X 驱动的
`ConnectedMonitor` + `CustomEDID` → X 服务器跑在 NVIDIA 卡上 → 桌面/应用全部由 GPU 硬件渲染。

**验证**：

```bash
sudo vdisplay status            # xrandr 显示虚拟屏 connected
glxinfo -B | grep -i renderer   # 渲染器应为 NVIDIA 显卡
nvidia-smi                      # 显存占用 > 0 说明桌面在 GPU 上渲染
```

## 完整原理

### 要解决的核心矛盾

NVIDIA 专有驱动的 X 服务器启动逻辑：**必须存在一个"已连接"的显示器输出，否则拒绝在显卡上创建显示设备**。无头主机陷入死循环：

```
没有显示器 → 驱动认为无输出 → X 无法启动在 NVIDIA 卡上
→ 桌面只能 CPU/核显软件渲染 → GPU 永远闲置
```

整套方案的本质：**用一个"假显示器"骗过驱动**，再在其上叠加两层远程访问协议。

### 第一层：EDID 注入（让 GPU 相信有屏幕）

**什么是 EDID**：真实显示器 EEPROM 里存的 128 字节"身份证"（分辨率、刷新率、时序、色彩空间、厂商名）。显卡启动时经 DDC 通道（I²C）读取它，据此决定支持哪些显示模式。

**欺骗手法**：NVIDIA X 驱动提供两个选项，`nvidia-vdisplay` 就是自动化生成这两样东西：

```
Option "ConnectedMonitor" "DFP-0"                                 ← 告诉驱动：这个输出口"插着屏"
Option "CustomEDID" "DFP-0:/etc/nvidia-vdisplay/edid/DFP-0.bin"   ← 不读硬件，读这个文件
```

驱动信了之后，X 服务器成功在 NVIDIA 卡上创建屏幕，后续所有渲染走 GPU。

**软件如何凭空造出合法 EDID**（纯 Python，零依赖）：

1. 时序计算（modelines.py）：优先调用 Xorg 自带的 `cvt`（CVT-RB 标准公式）；无 `cvt` 时查内置 VESA 标准表；再兜底用自洽公式推算。产物是一组模型线参数：像素时钟、行/场同步起止、前后肩。
2. 二进制编码（edid.py）：按 EDID 1.4 规范逐字节填充 128 字节块——头部魔数 `00 FF FF FF FF FF FF 00`、厂商 3 字母编码、产品号、版本 1.4、sRGB 色度坐标（10bit 量化）、gamma 2.2、DPMS 能力位、标准时序槽（16:9/4:3 比例编码）、**详细时序描述符 DTD**（首选模式完整时序）、显示器名称描述符、校验和（全块和 ≡ 0 mod 256）。
3. Xorg 配置生成（xorg.py）：`ConnectedMonitor` + `CustomEDID` + `MetaModes`（多虚拟屏左右拼接）+ 性能选项（TripleBuffer、Coolbits）。
4. 开机自动应用：systemd 服务排在 `display-manager.service` 之前，先写 EDID 再起桌面。

**渲染链路**（此时）：

```
KDE 应用 → kwin(OpenGL 合成) → GLX → NVIDIA 驱动 → GT 730 渲染 → 显存帧缓冲
                                    ↑
                          X Server 运行在 NVIDIA 卡上
```

验证：`glxinfo` 渲染器显示 GT 730、`nvidia-smi` 显存占用 > 0。

### 第二层：远程访问协议（两种互补）

**x11vnc（桌面控制备份）**：

```
X 帧缓冲 → XDAMAGE 扩展（只抓变化区域）→ x11vnc 编码(tight/zrle + ncache 客户端缓存)
→ RFB 协议(VNC) → TCP 5900 → 客户端
```

优点：任何 VNC 客户端可连；缺点：协议无音频、CPU 编码难上 60fps。
适配难点：sddm 用 `-displayfd` 动态分配显示器号（:0/:1 漂移）+ 认证文件随机名 → 封装脚本动态探测。

**Sunshine + Moonlight（主力，60fps + 音频）**：

```
视频: X11 采集(XCB) → VAAPI 硬件编码(h264, iGPU) → RTP/UDP(47998) → Moonlight 解码
音频: 应用 → PipeWire 重采样48k → Sunshine 虚拟 sink 监视器 → Opus(48kHz) → UDP(48000)
控制: RTSP 会话管理(TCP 47989) + 输入事件反向回传
```

关键选型：
- **不用 Kepler NVENC**：第一代 NVENC 缺多参考帧/两遍编码，新版 FFmpeg 拒绝初始化 → 改用 Intel 核显 VAAPI（QuickSync）；
- **强制 X11**：虚拟连接器方案在 Wayland 下无效（Wayland 只枚举真实物理输出）。

**输入链路**（"鼠标后端"问题的根源）：

```
Moonlight 鼠标事件 → Sunshine(libvirtualhid) → /dev/uinput 创建设备节点
→ 内核 evdev → X libinput → KDE
```

- uinput 权限缺失 → Sunshine 降级 XTest 合成事件（手感差、KDE 无法识别后端）→ 修复 = 开放 uinput（0666 + tmpfiles 持久化）；
- `Step value 0` + KDE 面板灰显 → InputClass 显式声明 pointer + 平直加速；
- 滚轮过快 = 高分辨率滚动事件被放大 → 关闭之。

### 驱动层（为什么 470 + bookworm-backports）

- GT 730 是 Kepler 架构，闭源驱动支持止步于 **470.256.02**；
- Debian 13 仓库已删 470 包；bookworm-backports 的 `470.256.02-5~bpo12+1` 是官方为 6.12 内核打过补丁的版本；
- **apt 优先级固定**（bpo 整体 90、nvidia 系列 510）防止混合源污染系统；
- 模块名带 `-tesla-470` 后缀，靠 `install nvidia modprobe -i nvidia-tesla-470` 别名映射成标准 `nvidia` 名。

### 系统级保障（无头常开）

| 问题 | 机制 | 修复 |
|---|---|---|
| 挂起/休眠 | systemd sleep.target | `systemctl mask` 全部屏蔽 |
| 熄屏 | DPMS | `xset -dpms s off` + powerdevil 超时=-1 |
| 画面突然变黑 | PowerDevil 节能前变暗 | 同上配置禁用 |
| 自动锁屏 | KScreenLocker | Autolock=false |
| 开机顺序 | — | nvidia-vdisplay.service → display-manager → sunshine(用户服务) → x11vnc |

### 画质与网络的关系（"自动变模糊"的机制）

Sunshine 用 **VBR 动态码率 + 单帧 VBV 上限**：画面运动剧烈时单帧预算不足 → 编码器自动降量化参数 → 模糊；静止时恢复清晰。**本质是码率受限于网络链路**，不是软件缺陷——链路质量决定画质天花板。

### 附：NVIDIA X 驱动是什么

NVIDIA 闭源驱动是一套分层组件，"X 驱动"只是其中 X11 专属的一块：

```
┌─ 用户空间库：libGLX(X11)/libEGL(Wayland)/libcuda/libnvidia-encode(NVENC)/Vulkan
├─ X 服务器插件（仅 X11 会话加载）：
│    nvidia_drv.so          ← X11 显示驱动 (DDX)
│    libglxserver_nvidia.so ← X 服务器的 GLX 扩展
└─ 内核模块（所有显示服务器共用）：nvidia/modeset/drm/uvm/peermem
```

X.Org 采用 DDX（Device Dependent X）架构：服务器管协议与窗口树，"怎么往显卡上画"交给可插拔驱动。因此 Wayland 会话**不加载** nvidia_drv.so（它走 EGL/KMS 直连内核模块），只有 X11 会话才经过这一层。

这解释了方案为何锁定 X11：**EDID 的读取发生在 X 驱动的模式校验环节**——它枚举输出口、读 EDID、决定支持的分辨率。`ConnectedMonitor`/`CustomEDID` 正是操纵这一环节的官方接口。Wayland 没有可操纵的这一层，所以虚拟屏只能跑 X11。

开源驱动 nouveau 占据的是同一位置（DDX `nouveau_drv.so` + 内核模块 `nouveau.ko`）；黑名单它就是为了防止其内核模块抢先绑走显卡，导致专有驱动初始化失败。

## 适用范围

### 各组件的适用设备

| 组件 | 适用设备 | 限制条件 |
|---|---|---|
| 虚拟显示器（nvidia-vdisplay） | 所有仍有闭源驱动支持的 NVIDIA 显卡：Kepler（470）/ Maxwell、Pascal（580）/ Turing、Ampere（595+） | 必须为 Linux + X11；必须能安装对应分支的闭源驱动 |
| Sunshine + Moonlight 串流 | 任意设备（支持软件编码，无硬件编码器也可运行） | 无硬件编码的机器需降低码率与分辨率（如 720p30，老四核 CPU 可胜任） |
| 音频 / 输入 / 电源管理配置 | 任意 Linux 主机 | 无 |
| 470 驱动安装方法（跨版本仓库 + apt 优先级固定） | 任何"驱动不在当前发行版仓库"的情形 | 思路通用，具体版本号需替换 |

### 关键限制

1. **老 NVIDIA 显卡**：取决于驱动对新内核的兼容性。Kepler 是最后一个仍能在 6.x 内核上运行的旧架构（470 + backports 补丁）。Fermi（GTX 400/500）及更早：390 驱动无法在新内核上编译，基本不可用。
2. **AMD 老显卡**：`ConnectedMonitor` / `CustomEDID` 是 NVIDIA X 驱动专属选项，AMD 没有对应机制，虚拟显示器方案不适用。
3. **无视频输出的矿卡**（P104 / P106 等）：X 驱动可能枚举不到任何连接器，虚拟屏幕方案很可能失效；纯计算用途不受影响。
4. **通用替代方案**：几元钱的 HDMI 假负载（EDID 模拟器）。插上后任何显卡、任何驱动、任何操作系统（包括 Windows）都会认为已连接显示器。本项目本质上是这套硬件方案的软件替代品。

### 结论

- **NVIDIA 显卡（Kepler 起）+ Linux + X11**：本方案可直接迁移，仅需调整分辨率等参数；
- **其他老显卡或非 Linux 系统**：Sunshine 串流部分通用；虚拟显示部分需改用 HDMI 假负载或其他方案；
- **早于 Kepler 的 NVIDIA 显卡**：受限于驱动无法在新内核编译，不适用。

测试机信息：
<img width="1115" height="628" alt="image" src="https://github.com/user-attachments/assets/44c3b2fd-24da-48df-b178-3bd3e1724914" />

## 许可

MIT

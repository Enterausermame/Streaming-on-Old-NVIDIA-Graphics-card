# 无头 Kepler 显卡：虚拟显示 + 远程桌面 + 低延迟串流

让一台**没有显示器的 NVIDIA Kepler 老卡（如 GT 730）主机**实现：

- 🖥️ **虚拟显示器**：纯 Python 生成 EDID 注入驱动，桌面/应用全部由 GPU 硬件渲染（1080p/1200p/多屏任意分辨率）
- 🖼️ **VNC 远程桌面**：x11vnc 共享 GPU 渲染画面，开机自启、自动适配显示器号与认证
- 🎮 **Moonlight 低延迟串流**：Sunshine + 硬件编码 60fps + 音频同步 + 虚拟键鼠
- 🔧 **踩坑记录**：驱动、音频、鼠标、电源管理的最优配置

> 适用环境：NVIDIA Kepler 架构（GT 730 等）/ Debian 13 trixie / 内核 6.12 / 无头运行。
> 文中所有网络地址、账号、密码、主机名均以 `<占位符>` 表示，请替换为你自己的值。

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

## 完整原理

### 卡在哪一步

NVIDIA 闭源驱动的 X 服务器有个死规矩：**必须检测到"插着显示器"，才肯在显卡上建屏幕**。没插显示器的话：

```
没显示器 → 驱动认为没有输出 → X 不肯在 NVIDIA 卡上启动
→ 桌面只能软件渲染 → GPU 白放着
```

所以整套东西的第一步就是：**造一个假显示器骗过驱动**，之后才是远程访问的事。

### 第一步：EDID 注入（让驱动以为插了屏）

**EDID 是啥**：显示器里一块 EEPROM 存着 128 字节的"身份证"——分辨率、刷新率、时序、色域、厂商名。显卡启动时通过 DDC（I²C 总线）去读它，照着它决定能出哪些模式。

**怎么骗**：NVIDIA X 驱动有俩现成选项，nvidia-vdisplay 就是帮你把这两行写进 Xorg 配置：

```
Option "ConnectedMonitor" "DFP-0"                               ← 说这个口"插着屏"
Option "CustomEDID" "DFP-0:/etc/nvidia-vdisplay/edid/DFP-0.bin" ← 别读硬件，读这个文件
```

驱动认了，X 就能在 NVIDIA 卡上建屏幕，后面渲染全走 GPU。

**软件怎么凭空造 EDID**（纯 Python，不带第三方依赖）：

1. 先算时序（modelines.py）：优先用 Xorg 自带的 `cvt`（CVT-RB 标准公式）；没有 cvt 就查内置的 VESA 标准表；实在不行按自洽公式推一个。产物是一组模型线参数：像素时钟、行/场同步起止、前后肩。
2. 再拼二进制（edid.py）：照 EDID 1.4 规范一个字节一个字节填满 128 字节——头部魔数 `00 FF FF FF FF FF FF 00`、厂商码、产品号、版本 1.4、sRGB 色度坐标（10bit 量化）、gamma 2.2、DPMS 位、标准时序槽、详细时序描述符 DTD（首选模式的完整时序）、显示器名、校验和（整块加起来 mod 256 必须为 0）。
3. 生成 Xorg 配置（xorg.py）：ConnectedMonitor + CustomEDID + MetaModes（多块虚拟屏左右拼）+ 性能项（TripleBuffer、Coolbits）。
4. 开机自己跑：systemd 服务排在显示管理器前面，先写 EDID 再起桌面。

**到这步的渲染链路**：

```
KDE 应用 → kwin(OpenGL 合成) → GLX → NVIDIA 驱动 → GT 730 渲染 → 显存
                                  ↑
                        X Server 跑在 NVIDIA 卡上
```

验证办法：`glxinfo` 看渲染器是不是 GT 730、`nvidia-smi` 显存占用不是 0。

### 第二步：远程访问（两条路，互补）

**x11vnc（备胎，纯控制用）**：

```
X 帧缓冲 → XDAMAGE（只抓变化区域）→ x11vnc 编码(tight/zrle + ncache 客户端缓存)
→ RFB 协议(VNC) → TCP 5900 → 客户端
```

好处是啥 VNC 客户端都能连；坏处是 VNC 协议本身没音频，CPU 编码也难上 60fps。
麻烦点：sddm 用 `-displayfd` 动态分显示器号（:0/:1 会漂），认证文件名也是随机的，所以外面套了层脚本去探测。

**Sunshine + Moonlight（主力，60fps + 带声音）**：

```
视频: X11 抓屏(XCB) → VAAPI 硬件编码(h264, 核显) → RTP/UDP(47998) → Moonlight 解码
音频: 应用 → PipeWire 重采样到48k → Sunshine 虚拟 sink 的监视端 → Opus(48kHz) → UDP(48000)
控制: RTSP 管会话(TCP 47989)，输入事件反向传回来
```

两个关键选型：
- **不用 Kepler 的 NVENC**：第一代 NVENC 缺多参考帧和两遍编码，新版 FFmpeg 直接拒绝初始化 → 换成 Intel 核显的 VAAPI（QuickSync）；
- **必须 X11**：虚拟连接器这招在 Wayland 下没用（Wayland 只认内核报上来的真实输出）。

**输入链路**（"鼠标后端"那事儿的根源）：

```
Moonlight 鼠标事件 → Sunshine(libvirtualhid) → /dev/uinput 造设备节点
→ 内核 evdev → X libinput → KDE
```

- uinput 没权限 → Sunshine 降级到 XTest 合成事件（手感差、KDE 认不出后端）→ 解决办法就是放开 uinput（0666 + tmpfiles 固化）；
- `Step value 0` 报错 + KDE 面板灰着 → 写 InputClass 显式声明成 pointer + 平直加速；
- 滚轮太快 = 高分辨率滚动事件被放大 → 关掉。

### 驱动层（为啥是 470 + bookworm-backports）

- GT 730 是 Kepler 架构，闭源驱动到 **470.256.02** 为止；
- Debian 13 仓库里已经没有 470 包了；bookworm-backports 的 `470.256.02-5~bpo12+1` 是官方为 6.12 内核打过补丁的；
- **apt 优先级固定**（bpo 整体 90、nvidia 系列 510），防止混源把系统依赖搞乱；
- 模块名带 `-tesla-470` 后缀是正常的，有 install 别名映射成标准的 `nvidia` 名。

### 系统层面（无头常开的保障）

| 问题 | 机制 | 处理 |
|---|---|---|
| 挂起/休眠 | systemd sleep.target | `systemctl mask` 全屏蔽 |
| 熄屏 | DPMS | `xset -dpms s off` + powerdevil 超时=-1 |
| 画面突然黑 | PowerDevil 的节能前变暗 | 同上，关掉 |
| 自动锁屏 | KScreenLocker | Autolock=false |
| 开机顺序 | — | nvidia-vdisplay.service → 显示管理器 → sunshine(用户服务) → x11vnc |

### 画质和网络的关系（"自动变模糊"是咋回事）

Sunshine 用 **VBR 动态码率 + 单帧 VBV 上限**：画面动得厉害时单帧预算不够 → 编码器自己降量化参数 → 糊；画面静下来又变清楚。**根子是码率被网络掐着**，不是软件毛病——链路有多强，画质就有多高。

### 顺带说下：NVIDIA X 驱动是个啥

NVIDIA 闭源驱动是分层的，"X 驱动"只是其中 X11 专属的一块：

```
┌─ 用户空间库：libGLX(X11)/libEGL(Wayland)/libcuda/libnvidia-encode(NVENC)/Vulkan
├─ X 服务器插件（只有 X11 会话会加载）：
│    nvidia_drv.so          ← X11 显示驱动 (DDX)
│    libglxserver_nvidia.so ← X 服务器的 GLX 扩展
└─ 内核模块（谁都能用）：nvidia/modeset/drm/uvm/peermem
```

X.Org 是 DDX 架构：服务器只管协议和窗口树，"往显卡上画"这活儿交给可插拔驱动。所以 Wayland 会话压根不加载 nvidia_drv.so（它直接走 EGL/KMS 和内核模块对话），只有 X11 才过这一层。

这也就解释了为啥整套东西锁死在 X11：**读 EDID 发生在 X 驱动的模式校验环节**——它枚举输出、读 EDID、决定支持哪些模式。ConnectedMonitor/CustomEDID 就是官方留来操纵这一步的口子。Wayland 没有这一层可动，所以虚拟屏只能跑 X11。

开源驱动 nouveau 占的就是同一个位置（DDX `nouveau_drv.so` + 内核模块 `nouveau.ko`）；黑名单它就是怕它的内核模块先一步把卡绑走，专有驱动就没法初始化了。

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

## 许可

MIT License — 自由使用、修改、分发。

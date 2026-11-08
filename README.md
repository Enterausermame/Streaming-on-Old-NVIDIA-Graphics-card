# 无头 Kepler 显卡：虚拟显示 + 远程桌面 + 低延迟串流 全套方案

让一台**没有显示器的 NVIDIA Kepler 老卡（如 GT 730）主机**实现：

- 🖥️ **虚拟显示器**：纯 Python 生成 EDID 注入驱动，桌面/应用全部由 GPU 硬件渲染（1080p/1200p/多屏任意分辨率）
- 🖼️ **VNC 远程桌面**：x11vnc 共享 GPU 渲染画面，开机自启、自动适配显示器号与认证
- 🎮 **Moonlight 低延迟串流**：Sunshine + 硬件编码 60fps + 音频同步 + 虚拟键鼠
- 🔧 **全套踩坑修复**：驱动、音频、鼠标、电源管理的最优配置

> 适用环境：NVIDIA Kepler 架构（GT 730 等）/ Debian 13 trixie / 内核 6.12 / 无头运行。
> 文中所有网络地址、账号、密码、主机名均以 `<占位符>` 表示，请替换为你自己的值。

## 目录

```
├── vdisplay/                 # 虚拟显示器软件（Python 包：EDID 生成 / Xorg 配置 / CLI）
├── systemd/                  # 开机自启服务单元
├── tests/                    # EDID 结构单元测试
├── install.sh                # 一键安装脚本
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
sudo vdisplay disable --restart-display       # 一键回退
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

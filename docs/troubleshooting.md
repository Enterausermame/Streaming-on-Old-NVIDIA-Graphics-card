# 故障排查与调优记录

> 无头 Kepler 主机远程桌面/串流方案中实际遇到并解决的所有问题，按症状归类。

## 音频

### 症状：播放部分视频时音频断断续续

排查链：网络丢包 → 重采样 → 量化周期 → 编码器饥饿。

**修复（按优先级）**：

1. **播放器直接输出 48kHz**，避免 44.1kHz 内容在管线内重采样（mpv：`--audio-samplerate=48000`）；
2. **增大 PipeWire 量化缓冲**（configs/pipewire-pulse-10-sunshine.conf）：
   ```
   pulse.min.quantum = 1024/48000
   pulse.min.req = 1024/48000
   ```
   防网络抖动下的音频欠载；
3. Sunshine 会自动创建虚拟 sink（日志：`Found default monitor by name: sink-sunshine-stereo.monitor`），
   这是预期行为，勿删；
4. 若仍有断续，先测网络（大包 ping 连续 20 次），丢包 > 1% 时优先解决链路而非音频。

## 鼠标 / 输入

### 症状：KDE 鼠标设置面板显示「无法选择适合的后端程序」且灰显

根因：Sunshine 的虚拟鼠标设备注册到 X 后，libinput 报
`Step value 0 was provided, libinput Fallback acceleration function is used`，
KDE 无法为该设备确定后端。

**修复**：

1. 开放 `/dev/uinput` 权限（见 configs/），确保 Sunshine 走 libvirtualhid 而非 XTest 降级：
   ```bash
   # 判断标准：/proc/bus/input/devices 中出现 libvirtualhid Mouse/Keyboard
   ```
2. 显式 InputClass 声明设备为 pointer（configs/30-virtualhid-input.conf）；
3. KDE 侧重置输入配置（删掉手工配置的畸形条目，让 KDE 重新探测）。

### 症状：滚轮速度过快/过慢

- 过快：Sunshine 默认 `high_resolution_scrolling = enabled`（高分辨率滚轮事件被放大）→ 设 `disabled`；
- 之后由 KDE「系统设置 → 鼠标 → 滚动」按个人喜好微调。

### 症状：鼠标灵敏度诡异 / 手感漂

- 串流分辨率与客户端屏幕不一致时存在缩放映射 → 让虚拟显示器分辨率 = 客户端屏幕分辨率（vdisplay 支持任意分辨率），1:1 映射；
- 虚拟鼠标建议平直加速（configs/kcminputrc）。

## 画面

### 症状：画面一阵模糊一阵清晰（自动调节清晰度）

机制：VBR 动态码率 + 单帧 VBV 限制。视频场景复杂（大运动量）时单帧预算不足 → 编码器降质 → 场景静止又恢复。

**处理**：
- 提高码率（客户端 `--bitrate`）→ 受网络上限约束；
- 视频播放场景降帧率（30fps）比降分辨率更划算：每帧码率翻倍；
- 弱 WiFi 场景按「降码率 → 720p → 30fps」顺序退让。

### 症状：画面整体变黑但鼠标能动 / 一段时间后黑屏

- 根因：KDE PowerDevil 的「节能前变暗」与 DPMS 熄屏（虚拟屏也会被"熄灭"）；
- 修复：configs/powerdevilrc（关闭显示器超时 = -1、变暗 = -1）+ `xset -dpms s off`
  + configs/kscreenlockerrc（禁自动锁屏）。

### 症状：Moonlight 闪「slow connection」

- 双无线跳（客户端 + 主机都走 WiFi）时最易出现；
- 处理：降码率/分辨率/帧率；改善主机信号（挪位置/换 5GHz）；
- 终极方案：有线（网线或电力线适配器）。

## 显示会话

### 症状：重启后 KDE 会话变成 Wayland，虚拟屏失效

- Debian 13 上 sddm 的 `Session=plasma` 默认指向 Wayland 会话；
- 修复：sddm 配置强制 X11，自动登录会话改为 X11 会话文件（trixie 上叫 `plasmax11`）：
  ```ini
  [General]
  DisplayServer=x11

  [Autologin]
  Session=plasmax11
  ```

### 症状：X 服务器显示器号在 :0/:1 间漂移

- sddm 用 `-displayfd` 动态分配；所有脚本（x11vnc/Sunshine 封装）都必须动态探测：
  ```sh
  for d in :0 :1 :2; do [ -S "/tmp/.X11-unix/X${d#:}" ] && { DISPLAY=$d; break; }; done
  XAUTHORITY=$(ls -t /run/sddm/xauth_* 2>/dev/null | head -1)
  # 用户会话环境更可靠：systemctl --user show-environment
  ```

## 驱动

### 症状：`nvidia-smi` 无法与驱动通信 / GPU 被 nouveau 抢占

- 检查：`lsmod | grep nouveau`（必须为空）+ `/etc/modprobe.d` 黑名单 + `update-initramfs -u` 后重启；
- 470 驱动模块名带 `-tesla-470` 后缀是正常的（install 别名已映射到 `nvidia`）。

### 症状：`nvidia-installer --uninstall` 后仍有残留

- 官方卸载器会清理 `/usr/bin/nvidia-*` 与 `/usr/src/nvidia-*`；
- 卸载后无需 rm，确认 `dpkg -l | grep -i nvidia` 为空即可。

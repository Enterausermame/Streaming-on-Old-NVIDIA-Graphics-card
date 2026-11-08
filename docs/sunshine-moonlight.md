# Sunshine + Moonlight 无头串流搭建（含配对 API 与编码器选型）

> 目标：无头主机 60fps 低延迟串流 + 音频同步 + 虚拟键鼠。
> 客户端使用 Moonlight（Windows/macOS/Linux/Android 均有）。

## 1. 安装 Sunshine（LizardByte 官方源）

```bash
# 添加源（或用 apt 安装脚本）
curl -fsSL https://apt.lizardbyte.dev/install.sh | bash
sudo apt install sunshine
```

## 2. 核心配置

`~/.config/sunshine/sunshine.conf`（模板见 [configs/sunshine.conf.template](../../configs/sunshine.conf.template)）：

```ini
sunshine_name = <你的主机显示名>
display_name = x11          # 虚拟显示器方案必须 X11
fps = 60
encoder = vaapi             # 见下方"编码器选型"
upnp = disabled             # 局域网使用无需端口映射
high_resolution_scrolling = disabled   # 滚轮回退传统粒度，远程桌面手感正常
```

## 3. 以用户会话服务运行（关键）

Sunshine 必须能访问 X 显示、音频服务与输入设备 → 用 **systemd 用户服务**（随图形会话启动，自动继承 DISPLAY/XDG_RUNTIME_DIR）：

```bash
systemctl --user enable --now app-dev.lizardbyte.app.Sunshine.service
```

## 4. 编码器选型：为什么用 Intel iGPU VAAPI 而不是 NVENC

- Kepler（GT 730）的第一代 NVENC **缺少多参考帧、两遍编码（multipass）等特性**，新版 FFmpeg 的 `h264_nvenc` 直接拒绝初始化（`Provided device doesn't support required NVENC features`）。
- 若主机有 Intel 核显（Haswell 及以后），`h264_vaapi` 可完整支持 1080p60 H.264 硬件编码，CPU 零负担。
- 启动日志中 `Found H.264 encoder: h264_vaapi [vaapi]` 即成功；`encoder = vaapi` 可跳过其他编码器的探测。

## 5. 凭据与 Web UI（2026 版变化）

- 新版 Sunshine 的 Web UI 凭据存放在 **`~/.config/sunshine/sunshine_state.json`**（不再是 sunshine.conf）。
- 首次运行（无凭据状态）可直接调用 API 设置：
  ```bash
  curl -k -H "Content-Type: application/json" \
    -d '{"newUsername":"<用户名>","newPassword":"<密码>","confirmNewPassword":"<密码>"}' \
    https://localhost:47990/api/password
  ```
- 设置后 **API 支持 HTTP Basic Auth**（`curl -u 用户:密码`），无需 cookie 会话。

## 6. 配对（Pairing）API 全流程

Moonlight 客户端发起配对 → 显示 4 位 PIN → 在服务端提交。把流程串起来的完整步骤：

```bash
# ① 客户端: moonlight pair <主机IP>（窗口显示 PIN）
# ② 查询待配对请求（拿到 pairing_id 与客户端名）
curl -sk -u <用户>:<密码> https://localhost:47990/api/pin
# → {"pairings":[{"id":"<32位hex>","name":"<客户端名>","address":"<客户端IP>"}]}

# ③ 提交 PIN（注意：pin + pairing_id + name 三个字段缺一不可）
curl -sk -u <用户>:<密码> -H "Content-Type: application/json" \
  -d '{"pin":"<PIN>","pairing_id":"<32位hex>","name":"<客户端名>"}' \
  https://localhost:47990/api/pin
# → {"status":true}

# ④ 验证已配对
curl -sk -u <用户>:<密码> https://localhost:47990/api/clients/list
```

**踩坑提示**：
- PIN 有效期很短（约 1 分钟），整套流程要"读 PIN → 立即提交"一气呵成；
- 客户端每次配对生成新的 pairing_id，不能复用旧的；
- 若返回 `409 pairing session already exists`：重启 sunshine 服务清空内存中的待配对状态；
- JSON 必须严格合法（引号转义错误会得到 `json.exception.parse_error`）。

## 7. 启动串流

```bash
# Moonlight CLI（分辨率/帧率/码率按网络条件调整）
moonlight stream <主机IP> "Desktop" --resolution 1920x1200 --fps 60 --bitrate 8000
```

- 码率经验值：有线 1080p60≈20Mbps；WiFi 视信号强度，弱信号建议 8Mbps 以内；
- 卡顿时优先降码率 → 降分辨率（720p）→ 降帧率（30fps）；
- 视频播放场景 30fps + 高码率的每帧画质显著优于 60fps + 低码率。

## 8. 音频链路

```
应用(44.1kHz/48kHz) → PipeWire 重采样 → Sunshine 虚拟 sink 监视器 → Opus → Moonlight
```

- 播放器尽量直接输出 48kHz（mpv：`--audio-samplerate=48000`），避免管线内重采样毛刺；
- PipeWire 大缓冲配置见 [configs/pipewire-pulse-10-sunshine.conf](../../configs/pipewire-pulse-10-sunshine.conf)。

## 9. 虚拟键鼠（uinput）

Sunshine 通过 libvirtualhid 创建虚拟输入设备，需要 `/dev/uinput` 访问权限：

- udev 规则 + tmpfiles 持久化见 [configs/90-uinput-sunshine.rules](../../configs/90-uinput-sunshine.rules) 与 [configs/uinput.conf](../../configs/uinput.conf)；
- 配置生效后会话日志中不再出现 `XTest fallback` 警告，`/proc/bus/input/devices` 中可见 `libvirtualhid Mouse/Keyboard`。

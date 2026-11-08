# Kepler 闭源驱动 470 在 Debian 13 (trixie) 的安装

> GT 730（GK208 开普勒架构）能用的最后一代闭源驱动是 **470.256.02**。
> Debian 13 仓库已移除 470 包，本方案从 bookworm-backports 安装（该版本已为 6.12 内核打好补丁，dkms 可正常编译）。
> 参考 Debian Wiki「NvidiaGraphicsDrivers → Kepler GPUs on Trixie & Bookworm」章节。

## 0. 前置条件

- 已启用 non-free / non-free-firmware 组件
- 内核头文件已安装：`apt install linux-headers-amd64`
- Secure Boot 已关闭（`mokutil --sb-state` 确认），否则 dkms 模块需签名

## 1. 清理旧的 NVIDIA 驱动

```bash
# 若曾用 .run 安装过：用官方卸载器（不要手动删文件）
sudo nvidia-installer --uninstall --silent

# 若装过发行版包：
sudo apt purge --auto-remove '*nvidia*' '*cuda*'
```

## 2. 添加 bookworm-backports 源（用你所在地区的镜像）

`/etc/apt/sources.list.d/bookworm-backports.list`：

```
deb http://<你的镜像>/debian/ bookworm-backports main contrib non-free non-free-firmware
deb-src http://<你的镜像>/debian/ bookworm-backports main contrib non-free non-free-firmware
```

## 3. apt 优先级固定（防止污染 trixie 依赖）

`/etc/apt/preferences.d/nvidia-kepler.pref`：

```
Package: *
Pin: release n=bookworm-backports
Pin-Priority: 90

Package: *nvidia-tesla-470*
Pin: release n=bookworm-backports
Pin-Priority: 510
```

> 关键：普通包优先级 90（低于 trixie 默认 500，不会被拉进来），
> 只有 `nvidia-tesla-470*` 系列的包优先级 510（确保来自 bpo 并跟随升级）。

## 4. 安装

```bash
sudo apt update
sudo apt install nvidia-tesla-470-driver
```

dkms 会自动为当前内核编译模块。验证：

```bash
/usr/sbin/dkms status
# nvidia-tesla-470/470.256.02, <内核版本>, x86_64: installed
```

## 5. 黑名单 nouveau + 重建 initramfs

```bash
cat <<'EOF' | sudo tee /etc/modprobe.d/blacklist-nouveau.conf
blacklist nouveau
options nouveau modeset=0
EOF
sudo update-initramfs -u
```

（Debian 的 `nvidia-blacklists-nouveau.conf` 也会做同样的事，重复无害。）

## 6. 重启并验证

```bash
sudo systemctl reboot
nvidia-smi   # 应显示 Driver Version: 470.256.02
```

## 7. 安装后清理（Debian Wiki 建议）

```bash
# 470 不支持新版的 persistenced 服务（会启动失败），禁用它；
# 传统持久化模式仍可用：nvidia-smi -pm 1
sudo systemctl disable nvidia-persistenced.service

# Kepler 实际只支持 Vulkan 1.2.175，修正 ICD 声明（否则 Vulkan 应用可能误判）
sudo sed -i 's@"api_version" : "1.3...."@"api_version" : "1.2.175"@' \
  /usr/share/vulkan/icd.d/nvidia_icd.json \
  /usr/share/vulkan/implicit_layer.d/nvidia_layers.json
```

## 常见问题

- **`apt-cache policy nvidia-tesla-470-driver` 为空**：470 确实不在 trixie；检查第 2/3 步源与 pin 文件。
- **dkms 编译失败**：确认用的是 bookworm-backports 版本（`-5~bpo12+1` 后缀），trixie 内核 6.12 需要它自带的补丁。
- **GT 730 不支持 580 驱动**：580 起只支持 Maxwell+，Kepler 必须 470。

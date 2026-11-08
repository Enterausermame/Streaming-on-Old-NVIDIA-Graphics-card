#!/bin/sh
# Streaming on Old NVIDIA Graphics Card — 部署脚本（合并版）
# 在目标机器（Debian 13 + Kepler 显卡）上运行：
#   sudo sh install-all.sh
# 覆盖："470 驱动 + 虚拟显示器" 两部分；VNC / Sunshine 串流见仓库 docs/。
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "请用 sudo 运行：sudo sh install-all.sh"
    exit 1
fi

command -v python3 > /dev/null 2>&1 || { echo "需要 python3：apt install python3"; exit 1; }

# 国内网络可改镜像，例如：MIRROR=http://mirrors.ustc.edu.cn/debian
MIRROR="${MIRROR:-http://deb.debian.org/debian}"
REPO_URL="${REPO_URL:-https://github.com/Enterausermame/Streaming-on-Old-NVIDIA-Graphics-card}"
DEST=/opt/nvidia-vdisplay

echo "==> 1/6 添加 bookworm-backports 源（470 驱动只在这里有）"
if [ ! -f /etc/apt/sources.list.d/bookworm-backports.list ]; then
    cat > /etc/apt/sources.list.d/bookworm-backports.list <<EOF
deb $MIRROR bookworm-backports main contrib non-free non-free-firmware
deb-src $MIRROR bookworm-backports main contrib non-free non-free-firmware
EOF
fi
cat > /etc/apt/preferences.d/nvidia-kepler.pref <<EOF
Package: *
Pin: release n=bookworm-backports
Pin-Priority: 90

Package: *nvidia-tesla-470*
Pin: release n=bookworm-backports
Pin-Priority: 510
EOF
apt update

echo "==> 2/6 安装 470 驱动（dkms 编译需要几分钟）"
DEBIAN_FRONTEND=noninteractive apt install -y nvidia-tesla-470-driver

echo "==> 3/6 下载仓库"
if command -v git > /dev/null 2>&1; then
    git clone --depth=1 "$REPO_URL" /tmp/nvidia-vdisplay-repo
else
    echo "需要 git：apt install git"
    exit 1
fi
SRC=/tmp/nvidia-vdisplay-repo

echo "==> 4/6 安装 nvidia-vdisplay 到 $DEST"
mkdir -p "$DEST"
cp -r "$SRC/vdisplay" "$DEST/"
mkdir -p "$DEST/systemd"
cp "$SRC/systemd/nvidia-vdisplay.service" "$DEST/systemd/"
cat > /usr/local/bin/vdisplay <<'EOF'
#!/bin/sh
cd /opt/nvidia-vdisplay && exec python3 -m vdisplay.cli "$@"
EOF
chmod +x /usr/local/bin/vdisplay
(cd "$DEST" && python3 -m vdisplay.cli init)
cp "$DEST/systemd/nvidia-vdisplay.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable nvidia-vdisplay.service
(cd "$DEST" && python3 -m vdisplay.cli apply)

echo "==> 5/6 黑名单 nouveau 并重建 initramfs"
cat > /etc/modprobe.d/blacklist-nouveau.conf <<EOF
blacklist nouveau
options nouveau modeset=0
EOF
update-initramfs -u

echo "==> 6/6 持久化模式（无头场景 GPU 保持就绪）"
if command -v nvidia-smi > /dev/null 2>&1; then
    nvidia-smi -pm 1 || true
fi

echo ""
echo "完成。接下来："
echo "  1) sudo systemctl reboot"
echo "  2) sudo vdisplay apply --restart-display   # 让虚拟屏生效"
echo "  3) sudo vdisplay status                    # 检查状态"
echo "VNC / Sunshine 串流配置见仓库 docs/ 目录。"

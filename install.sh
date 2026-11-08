#!/bin/sh
# nvidia-vdisplay 安装脚本（在目标 Linux 设备上运行）
# 用法: sudo sh install.sh
set -e

DEST=/opt/nvidia-vdisplay
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "[1/5] 安装文件到 $DEST"
mkdir -p "$DEST"
cp -r "$SRC/vdisplay" "$DEST/"
mkdir -p "$DEST/systemd"
cp "$SRC/systemd/nvidia-vdisplay.service" "$DEST/systemd/"

echo "[2/5] 安装 vdisplay 命令"
cat > /usr/local/bin/vdisplay <<'EOF'
#!/bin/sh
cd /opt/nvidia-vdisplay && exec python3 -m vdisplay.cli "$@"
EOF
chmod +x /usr/local/bin/vdisplay

echo "[3/5] 生成默认配置"
(cd "$DEST" && python3 -m vdisplay.cli init)

echo "[4/5] 安装 systemd 服务"
cp "$DEST/systemd/nvidia-vdisplay.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable nvidia-vdisplay.service

echo "[5/5] 应用虚拟显示器配置"
(cd "$DEST" && python3 -m vdisplay.cli apply)

echo ""
echo "完成。执行以下命令让虚拟屏幕生效："
echo "    sudo systemctl restart sddm   # 或 sudo vdisplay apply --restart-display"
echo "    sudo vdisplay status          # 查看状态"

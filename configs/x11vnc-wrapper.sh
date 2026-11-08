#!/bin/sh
# x11vnc 封装脚本：自动探测显示器号与认证文件（适配 sddm 动态 display）
# 配合 configs/x11vnc.service 使用
# 密码文件生成：sudo x11vnc -storepasswd <密码> /etc/nvidia-vdisplay/vncpasswd

DISP=""
for d in :0 :1 :2; do
    if [ -S "/tmp/.X11-unix/X${d#:}" ]; then
        DISP=$d
        break
    fi
done
if [ -z "$DISP" ]; then
    echo "x11vnc: no active X display, exiting" >&2
    exit 1
fi

# 优先取用户会话环境中的认证文件（sddm 下 /run/sddm/xauth_* 或 /tmp/xauth_*）
XAUTH=""
for f in /tmp/xauth_* /run/sddm/xauth_*; do
    [ -f "$f" ] && XAUTH="$f"
done
if [ -z "$XAUTH" ]; then
    exec /usr/bin/x11vnc -display "$DISP" -findauth \
        -rfbauth /etc/nvidia-vdisplay/vncpasswd \
        -listen <本机局域网IP> -rfbport 5900 \
        -forever -shared -repeat -ncache 10 \
        -o /var/log/x11vnc.log
fi

exec /usr/bin/x11vnc -display "$DISP" -auth "$XAUTH" \
    -rfbauth /etc/nvidia-vdisplay/vncpasswd \
    -listen <本机局域网IP> -rfbport 5900 \
    -forever -shared -repeat -ncache 10 \
    -o /var/log/x11vnc.log

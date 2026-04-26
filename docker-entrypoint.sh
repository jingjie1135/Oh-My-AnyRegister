#!/bin/bash
set -e

# 清理遗留的状态（锁文件和临时进程目录），防止重启后依然锁死
rm -rf /tmp/.X*-lock /tmp/.X11-unix /tmp/.DrissionPage* /tmp/chrome* /tmp/chromium* 2>/dev/null || true

# 启动虚拟显示。这里的尺寸也是 x11vnc 捕获区域和 headed 浏览器窗口尺寸的基准。
export DISPLAY=${DISPLAY:-:99}
export VNC_WIDTH=${VNC_WIDTH:-1280}
export VNC_HEIGHT=${VNC_HEIGHT:-720}
export VNC_DEPTH=${VNC_DEPTH:-24}

case "$VNC_WIDTH" in
    ''|*[!0-9]*) VNC_WIDTH=1280 ;;
esac
case "$VNC_HEIGHT" in
    ''|*[!0-9]*) VNC_HEIGHT=720 ;;
esac
case "$VNC_DEPTH" in
    8|16|24|32) ;;
    *) VNC_DEPTH=24 ;;
esac

if [ "$VNC_WIDTH" -lt 640 ] || [ "$VNC_WIDTH" -gt 3840 ]; then
    VNC_WIDTH=1280
fi
if [ "$VNC_HEIGHT" -lt 480 ] || [ "$VNC_HEIGHT" -gt 2160 ]; then
    VNC_HEIGHT=720
fi

export VNC_WIDTH VNC_HEIGHT VNC_DEPTH
Xvfb "$DISPLAY" -screen 0 "${VNC_WIDTH}x${VNC_HEIGHT}x${VNC_DEPTH}" -nolisten tcp +extension RANDR &

# 等待 Xvfb 就绪
sleep 1

# 启动轻量窗口管理器，避免 Chromium 在无 WM 环境下忽略窗口边界或最大化尺寸。
openbox >/tmp/openbox.log 2>&1 &

# 启动 x11vnc（无密码，仅本地 VNC）。显式限制捕获区域，避免 VNC 帧缓冲与 Xvfb 画布不一致。
if [ -n "$VNC_PASSWORD" ]; then
    x11vnc -storepasswd "$VNC_PASSWORD" /tmp/vncpass >/dev/null
    chmod 600 /tmp/vncpass
    x11vnc -display "$DISPLAY" -rfbauth /tmp/vncpass -forever -shared -noncache -noxdamage -clip "${VNC_WIDTH}x${VNC_HEIGHT}+0+0" &
else
    x11vnc -display "$DISPLAY" -nopw -forever -shared -noncache -noxdamage -clip "${VNC_WIDTH}x${VNC_HEIGHT}+0+0" &
fi

# 启动 noVNC（端口 6080 -> VNC 5900）
websockify --web=/usr/share/novnc 6080 localhost:5900 &

# 启动 FastAPI 后端
exec uvicorn main:app --host 0.0.0.0 --port 8000

#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

PYTHON="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "正在准备 Find APK 运行环境…"
  sh "$SCRIPT_DIR/tools/setup_macos.sh"
fi

if ! "$PYTHON" -c "import fastapi, jinja2, uvicorn" >/dev/null 2>&1; then
  echo "首次启动，正在安装网页服务组件…"
  "$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt"
fi

PORT="${FIND_APK_PORT:-8765}"
DEFAULT_INTERFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
LAN_IP=""
if [[ -n "$DEFAULT_INTERFACE" ]]; then
  LAN_IP="$(ipconfig getifaddr "$DEFAULT_INTERFACE" 2>/dev/null || true)"
fi
if [[ -z "$LAN_IP" ]]; then
  for INTERFACE in en0 en1 en2 en3; do
    LAN_IP="$(ipconfig getifaddr "$INTERFACE" 2>/dev/null || true)"
    [[ -n "$LAN_IP" ]] && break
  done
fi
[[ -z "$LAN_IP" ]] && LAN_IP="127.0.0.1"

echo ""
echo "Find APK 已准备启动"
echo "本机访问：http://127.0.0.1:$PORT"
echo "其他电脑：http://$LAN_IP:$PORT"
echo "关键词队列：可从网页批量加入，由 Codex 每 30 分钟自动处理"
echo "服务会在后台常驻，登录后自动启动，窗口可以直接关闭。"
echo ""

exec "$PYTHON" "$SCRIPT_DIR/tools/lan_service.py" install --port "$PORT"

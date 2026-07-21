#!/bin/sh
set -eu

setup_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
setup_agent_root=$(dirname "$setup_script_dir")
setup_venv="$setup_agent_root/.venv"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This setup script is for macOS." >&2
    exit 1
fi

if [ -x "$setup_venv/bin/python" ] &&
    "$setup_venv/bin/python" -c 'from PIL import features; raise SystemExit(not features.check("webp"))' >/dev/null 2>&1; then
    echo "Existing environment is ready: $($setup_venv/bin/python --version 2>&1)"
    "$setup_venv/bin/python" -c 'from PIL import Image; print(f"Pillow {Image.__version__} with WEBP support is ready")'
    exit 0
fi

setup_python=""
for setup_candidate in \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    "$HOME"/.local/share/uv/python/cpython-3.14*/bin/python3.14 \
    "$HOME"/.local/share/uv/python/cpython-3.13*/bin/python3.13 \
    "$HOME"/.local/share/uv/python/cpython-3.12*/bin/python3.12 \
    "$HOME/.local/bin/python3.14" \
    "$HOME/.local/bin/python3.13" \
    "$HOME/.local/bin/python3.12" \
    "$(command -v python3 2>/dev/null || true)"; do
    if [ -n "$setup_candidate" ] && [ -x "$setup_candidate" ]; then
        if "$setup_candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))'; then
            setup_python="$setup_candidate"
            break
        fi
    fi
done

if [ -z "$setup_python" ]; then
    echo "Python 3.9 or newer is required. Install Python 3 with Homebrew or python.org." >&2
    exit 1
fi

echo "Using $setup_python ($($setup_python --version 2>&1))"
"$setup_python" -m venv "$setup_venv"

setup_venv_python="$setup_venv/bin/python"
PIP_DISABLE_PIP_VERSION_CHECK=1 "$setup_venv_python" -m pip install -r "$setup_agent_root/requirements.txt"

"$setup_venv_python" -c '
from PIL import Image, features
assert features.check("webp"), "Installed Pillow does not support WEBP"
print(f"Pillow {Image.__version__} with WEBP support is ready")
'

echo "Ready. Agent Python: $setup_venv_python"

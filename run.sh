#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python 3.11 or newer is required."

"$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    || fail "Python 3.11 or newer is required."

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    if [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
        fail "No WSL GUI display was detected. Update WSL for WSLg, run 'wsl --update' in Windows, then restart WSL."
    fi
    fail "No Linux display server was detected. Start a desktop/Wayland/X11 session."
fi

if [[ ! -d "$PROJECT_DIR/vendor/yt-dlp/.git" ]]; then
    fail "vendor/yt-dlp is missing. Run: git clone https://github.com/yt-dlp/yt-dlp.git vendor/yt-dlp"
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    printf 'Creating virtual environment in %s\n' "$VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -c 'import PySide6' >/dev/null 2>&1; then
    printf 'Installing application dependencies...\n'
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    "$VENV_DIR/bin/python" -m pip install -r "$PROJECT_DIR/requirements.txt"
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    printf 'Warning: FFmpeg is not installed. Merging and post-processing will fail.\n' >&2
    printf 'On Ubuntu/WSL install it with: sudo apt update && sudo apt install ffmpeg\n' >&2
fi

cd "$PROJECT_DIR"
exec "$VENV_DIR/bin/python" -m app.main "$@"

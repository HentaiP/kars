#!/usr/bin/env bash
# Kars EV Ultimate — macOS
# Powered by HentaiP feat. ClawMoew.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${KARS_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    # The virtual environment from the README, if it was created here.
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
    [ -x "$PYTHON" ] || PYTHON=python3
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.10+ is required. Install it and the requirements before running Kars." >&2
    exit 1
fi
exec "$PYTHON" "$SCRIPT_DIR/kars.py" "$@"

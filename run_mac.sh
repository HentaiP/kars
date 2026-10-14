#!/usr/bin/env bash
# Kars EV Ultimate — macOS
# Powered by HentaiP feat. ClawMoew.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${KARS_PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python 3.10+ is required. Install it and the requirements before running Kars." >&2
    exit 1
fi
exec "$PYTHON" "$SCRIPT_DIR/kars.py" "$@"

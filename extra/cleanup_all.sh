#!/usr/bin/env bash
# Powered by HentaiP feat. ClawMoew
# Stop only the projects in this deployment manifest; no global prune.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${KARS_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    PYTHON="$SCRIPT_DIR/../.venv/bin/python"
    [ -x "$PYTHON" ] || PYTHON=python3
fi
exec "$PYTHON" "$SCRIPT_DIR/../kars.py" cleanup "$@"

#!/usr/bin/env bash
# Powered by HentaiP feat. ClawMoew
# Stop only the projects in this deployment manifest; no global prune.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${KARS_PYTHON:-python3}" "$SCRIPT_DIR/../kars.py" cleanup "$@"

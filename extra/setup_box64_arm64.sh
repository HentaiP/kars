#!/usr/bin/env bash
# Powered by HentaiP feat. ClawMoew
# Read-only architecture check. Box64 installation alone does not make Docker
# run amd64 containers, so do not register conflicting global binfmt handlers.
set -euo pipefail
case "$(uname -m)" in
    aarch64|arm64) ;;
    *) echo "This helper is for ARM64 hosts only." >&2; exit 1 ;;
esac
command -v docker >/dev/null 2>&1 || { echo "Install Docker first." >&2; exit 1; }
docker info --format 'Docker server architecture: {{.Architecture}}'
echo "ARM64 remains experimental. Configure supported Docker linux/amd64 emulation separately."
echo "No packages, global binfmt handlers or services were changed."

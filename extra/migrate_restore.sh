#!/usr/bin/env bash
# Powered by HentaiP feat. ClawMoew
# Read-only restore plan by default. Never overwrite hardened appsettings/nginx.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_PATH="${1:-}"
[ -n "$BACKUP_PATH" ] && [ -d "$BACKUP_PATH" ] || {
    echo "Usage: migrate_restore.sh BACKUP_DIR [--restore-mongo --yes]" >&2; exit 1;
}
shift
DO_MONGO=false
CONFIRMED=false
for arg in "$@"; do
    case "$arg" in
        --restore-mongo) DO_MONGO=true ;;
        --yes) CONFIRMED=true ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done
[ -f "$BACKUP_PATH/backup.complete" ] || { echo "Backup lacks its completion marker; review/recover it manually." >&2; exit 1; }
echo "Legacy appsettings and nginx files will NOT replace hardened configuration."
if [ -f "$BACKUP_PATH/v0_mysql_dump.sql" ]; then
    echo "MySQL dump requires a separately reviewed manual import; this tool does not import it."
fi
if [ "$DO_MONGO" != true ]; then
    echo "Plan only: no data changed. Use --restore-mongo --yes for the managed MongoDB container."
    exit 0
fi
[ "$CONFIRMED" = true ] || { echo "MongoDB restore changes database contents; --yes is required." >&2; exit 1; }
[ -s "$BACKUP_PATH/v0_mongo_dump.archive" ] || { echo "No nonempty MongoDB archive." >&2; exit 1; }
DATA_ROOT="${KARS_DATA_ROOT:-$HOME/.kars}"
MONGO_CONTAINER="${KARS_MONGO_CONTAINER:-kars-mongodb}"
PROJECT=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$MONGO_CONTAINER")
"${KARS_PYTHON:-python3}" - "$SCRIPT_DIR/.." "$DATA_ROOT" "$PROJECT" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from kars import load_manifest
manifest = load_manifest(Path(sys.argv[2]))
if sys.argv[3] not in {p['project'] for p in manifest['projects']}:
    raise SystemExit('Selected MongoDB container does not belong to this managed deployment')
PY
docker exec -i "$MONGO_CONTAINER" mongorestore --archive < "$BACKUP_PATH/v0_mongo_dump.archive"
echo "MongoDB restore completed. MySQL and legacy configuration were not imported."

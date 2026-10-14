#!/usr/bin/env bash
# Kars legacy backup. Credentials never appear in mysqldump's command line.
# Powered by HentaiP feat. ClawMoew.
set -euo pipefail
umask 077
BACKUP_DIR=$(mktemp -d "${1:-./legacy_backup_$(date +%Y%m%d_%H%M%S)}.XXXXXX")
MYSQL_CONFIG=""
COUNT=0
finish() {
    status=$?
    if [ -n "$MYSQL_CONFIG" ]; then rm -f -- "$MYSQL_CONFIG"; fi
    if [ "$status" -ne 0 ]; then
        echo "ERROR: Backup incomplete; partial files retained privately in $BACKUP_DIR" >&2
    fi
}
trap finish EXIT
PRIMARY="${LEGACY_DB_PRIMARY:-KARS_INTERNAL_SQL}"
SECONDARY="${LEGACY_DB_SECONDARY:-legacy_charger_db}"
for database in "$PRIMARY" "$SECONDARY"; do
    [[ "$database" =~ ^[A-Za-z0-9_]+$ ]] || { echo "Invalid database name" >&2; exit 1; }
done
if command -v mysqldump >/dev/null 2>&1; then
    read -r -s -p "MySQL root password (local terminal only): " DB_PASS
    printf '\n'
    MYSQL_CONFIG=$(mktemp "$BACKUP_DIR/.mysql.XXXXXX")
    ESCAPED="${DB_PASS//\\/\\\\}"
    ESCAPED="${ESCAPED//\"/\\\"}"
    printf '[client]\nuser=root\npassword="%s"\n' "$ESCAPED" > "$MYSQL_CONFIG"
    unset DB_PASS ESCAPED
    mysqldump --defaults-extra-file="$MYSQL_CONFIG" --single-transaction --databases "$PRIMARY" "$SECONDARY" > "$BACKUP_DIR/v0_mysql_dump.sql.partial"
    mv -- "$BACKUP_DIR/v0_mysql_dump.sql.partial" "$BACKUP_DIR/v0_mysql_dump.sql"
    rm -f -- "$MYSQL_CONFIG"; MYSQL_CONFIG=""
    COUNT=$((COUNT + 1))
else
    echo "MySQL skipped: mysqldump is not installed."
fi
MONGO_CONTAINER="${LEGACY_MONGO_CONTAINER:-kars-mongodb}"
if command -v docker >/dev/null 2>&1 && [ "$(docker inspect --format '{{.State.Running}}' "$MONGO_CONTAINER" 2>/dev/null || true)" = true ]; then
    docker exec "$MONGO_CONTAINER" mongodump --archive > "$BACKUP_DIR/v0_mongo_dump.archive.partial"
    mv -- "$BACKUP_DIR/v0_mongo_dump.archive.partial" "$BACKUP_DIR/v0_mongo_dump.archive"
    COUNT=$((COUNT + 1))
else
    echo "MongoDB skipped: selected legacy container is not running/reachable."
fi
LEGACY_ROOT="${LEGACY_ROOT:-/opt/kars}"
if [ -f "$LEGACY_ROOT/kars/data/nginx/conf.d/default.conf" ]; then
    cp -- "$LEGACY_ROOT/kars/data/nginx/conf.d/default.conf" "$BACKUP_DIR/v0_nginx_default.conf"
    COUNT=$((COUNT + 1))
fi
if [ -f "$LEGACY_ROOT/kars-core/appsettings.json" ]; then
    cp -- "$LEGACY_ROOT/kars-core/appsettings.json" "$BACKUP_DIR/v0_appsettings.json"
    COUNT=$((COUNT + 1))
fi
[ "$COUNT" -gt 0 ] || { echo "No backup sources found; no successful backup claimed." >&2; exit 1; }
printf 'Completed selected available sources: %s\nReview skipped sources in the terminal output.\n' "$COUNT" > "$BACKUP_DIR/backup.complete"
echo "Backup complete for $COUNT available source(s): $BACKUP_DIR"
echo "Skipped sources are not backed up. Keep this folder private; it may contain credentials."

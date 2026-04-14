#!/usr/bin/env bash
# =============================================================================
# backup.sh — Full platform backup with checksums, manifest, and rotation
# Usage: bash scripts/backup.sh [--label "my label"]
# =============================================================================
set -euo pipefail

DOCKER="${DOCKER_BIN:-/usr/local/bin/docker}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PLATFORM_DIR/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"
CONTAINER="${PG_CONTAINER:-platform-postgres-1}"
DB_NAME="${POSTGRES_DB:-jobplatform}"
DB_USER="${POSTGRES_USER:-postgres}"
KEEP_LAST="${KEEP_LAST:-14}"   # rotate: keep last N backups
LABEL="${2:-}"                 # optional --label "text"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()    { echo -e "${GREEN}[$(date +%H:%M:%S)] ✔  $*${NC}"; }
warn()   { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠  $*${NC}"; }
error()  { echo -e "${RED}[$(date +%H:%M:%S)] ✘  $*${NC}" >&2; exit 1; }
header() { echo -e "\n${BOLD}$*${NC}"; }

# ── pre-flight ────────────────────────────────────────────────────────────────
command -v "$DOCKER" &>/dev/null      || error "Docker not found at $DOCKER"
"$DOCKER" inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null \
  | grep -q running                   || error "Container $CONTAINER is not running"

mkdir -p "$BACKUP_PATH"
header "Platform Backup — $TIMESTAMP"

# ── 1. pre-backup row counts ──────────────────────────────────────────────────
log "Recording pre-backup row counts..."
ROW_COUNTS=$("$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT json_agg(row_to_json(t)) FROM (
    SELECT relname AS \"table\", n_live_tup::int AS rows
    FROM pg_stat_user_tables ORDER BY relname
  ) t;" 2>/dev/null | tr -d '\n')
TOTAL_ROWS=$(echo "$ROW_COUNTS" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(sum(r['rows'] for r in (d or [])))" 2>/dev/null || echo 0)
ALEMBIC_REV=$("$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '[:space:]')

# ── 2. pg_dump custom format (fast restore, size-efficient) ───────────────────
log "Dumping database (custom format)..."
DUMP_FILE="$BACKUP_PATH/jobplatform.pgdump"
"$DOCKER" exec "$CONTAINER" pg_dump \
  -U "$DB_USER" -d "$DB_NAME" \
  --format=custom --compress=9 --no-password \
  > "$DUMP_FILE"
DUMP_SIZE=$(wc -c < "$DUMP_FILE")
log "Custom dump complete — $(du -sh "$DUMP_FILE" | cut -f1)"

# ── 3. plain SQL gzip (human-readable emergency copy) ────────────────────────
log "Dumping database (plain SQL gzip)..."
SQL_FILE="$BACKUP_PATH/jobplatform.sql.gz"
"$DOCKER" exec "$CONTAINER" pg_dump \
  -U "$DB_USER" -d "$DB_NAME" \
  --format=plain --no-password \
  | gzip -9 > "$SQL_FILE"
SQL_SIZE=$(wc -c < "$SQL_FILE")
log "SQL dump complete — $(du -sh "$SQL_FILE" | cut -f1)"

# ── 4. checksums ──────────────────────────────────────────────────────────────
log "Generating SHA-256 checksums..."
CHECKSUM_FILE="$BACKUP_PATH/checksums.sha256"
(cd "$BACKUP_PATH" && shasum -a 256 jobplatform.pgdump jobplatform.sql.gz > checksums.sha256)
log "Checksums saved"

# ── 5. manifest ───────────────────────────────────────────────────────────────
log "Writing manifest..."
cat > "$BACKUP_PATH/manifest.json" <<MANIFEST
{
  "timestamp": "$TIMESTAMP",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "label": "$LABEL",
  "database": "$DB_NAME",
  "alembic_revision": "$ALEMBIC_REV",
  "total_rows": $TOTAL_ROWS,
  "dump_size_bytes": $DUMP_SIZE,
  "sql_gz_size_bytes": $SQL_SIZE,
  "table_row_counts": $ROW_COUNTS
}
MANIFEST
log "Manifest written"

# ── 6. rotation ───────────────────────────────────────────────────────────────
log "Rotating old backups (keeping last $KEEP_LAST)..."
REMOVED=0
while IFS= read -r old; do
  warn "Removing old backup: $(basename "$old")"
  rm -rf "$old"
  ((REMOVED++))
done < <(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | tail -n +$((KEEP_LAST + 1)))
[[ $REMOVED -gt 0 ]] || log "No old backups to remove"

# ── 7. summary ────────────────────────────────────────────────────────────────
TOTAL_BACKUPS=$(ls -d "$BACKUP_DIR"/[0-9]* 2>/dev/null | wc -l | tr -d ' ')
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✅ Backup complete!${NC}"
echo    "  Path:       $BACKUP_PATH"
echo    "  Dump:       $(du -sh "$DUMP_FILE" | cut -f1)  (.pgdump)"
echo    "  SQL:        $(du -sh "$SQL_FILE"  | cut -f1)  (.sql.gz)"
echo    "  Total rows: $TOTAL_ROWS"
echo    "  Migration:  $ALEMBIC_REV"
echo    "  Backups:    $TOTAL_BACKUPS stored (max $KEEP_LAST)"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo    "  Restore:    bash scripts/restore.sh $TIMESTAMP"
echo    "  Validate:   bash scripts/validate_backup.sh $TIMESTAMP"
echo

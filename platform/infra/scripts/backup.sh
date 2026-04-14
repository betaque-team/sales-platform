#!/usr/bin/env bash
# =============================================================================
# infra/scripts/backup.sh — Database backup with checksums + manifest
# Called by: make backup, make backup-pre, cron, deploy pipeline
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
TS=$(date +"%Y%m%d_%H%M%S")
DEST="$BACKUP_DIR/$TS"
KEEP_LAST="${BACKUP_KEEP_LAST:-14}"
LABEL=""
LIST_ONLY=false

# Parse args
for arg in "$@"; do
  case "$arg" in
    --label)   shift; LABEL="${1:-}"; shift || true ;;
    --label=*) LABEL="${arg#--label=}" ;;
    --list)    LIST_ONLY=true ;;
  esac
done

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[backup] $*${NC}"; }
warn() { echo -e "${YELLOW}[backup] $*${NC}"; }

# ── List mode ─────────────────────────────────────────────────────────────────
if $LIST_ONLY; then
  echo -e "${BOLD}Available backups:${NC}"
  for d in $(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null); do
    if [[ -f "$d/manifest.json" ]]; then
      INFO=$(python3 -c "
import json; m=json.load(open('$d/manifest.json'))
print(f\"  {m.get('timestamp','?'):20s}  rows={m.get('total_rows','?'):>8,}  {m.get('dump_size_bytes',0)/1024/1024:.1f}MB  label={m.get('label','')}\")
" 2>/dev/null || echo "  $(basename "$d")  (manifest parse error)")
      echo "$INFO"
    else
      echo "  $(basename "$d")  (no manifest)"
    fi
  done
  exit 0
fi

# ── Create backup ─────────────────────────────────────────────────────────────
mkdir -p "$DEST"
log "Backup $TS → $DEST"

# Row counts
ROW_JSON=$($COMPOSE exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" -t -A -c "
  SELECT json_agg(row_to_json(t)) FROM (
    SELECT relname AS \"table\", n_live_tup::int AS rows
    FROM pg_stat_user_tables ORDER BY relname
  ) t;" 2>/dev/null | tr -d '\n')
TOTAL_ROWS=$(echo "$ROW_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(sum(r['rows'] for r in (d or [])))" 2>/dev/null || echo 0)

# pg_dump custom
log "Dumping database (custom format)..."
$COMPOSE exec -T postgres pg_dump -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" \
  --format=custom --compress=9 --no-password > "$DEST/jobplatform.pgdump"
DUMP_SIZE=$(wc -c < "$DEST/jobplatform.pgdump")

# pg_dump sql.gz
log "Dumping database (SQL gzip)..."
$COMPOSE exec -T postgres pg_dump -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" \
  --format=plain --no-password | gzip -9 > "$DEST/jobplatform.sql.gz"

# Checksums
shasum -a 256 "$DEST"/jobplatform.* | sed "s|$DEST/||" > "$DEST/checksums.sha256"

# Alembic revision
ALEMBIC=$($COMPOSE exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" \
  -t -A -c "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '[:space:]')

# Manifest
cat > "$DEST/manifest.json" <<EOF
{
  "timestamp": "$TS",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "label": "$LABEL",
  "database": "${POSTGRES_DB:-jobplatform}",
  "alembic_revision": "$ALEMBIC",
  "total_rows": $TOTAL_ROWS,
  "dump_size_bytes": $DUMP_SIZE,
  "table_row_counts": $ROW_JSON
}
EOF

# Rotate
ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | tail -n +$((KEEP_LAST + 1)) | xargs rm -rf 2>/dev/null || true

log "Backup complete — $TOTAL_ROWS rows, $(du -sh "$DEST/jobplatform.pgdump" | cut -f1)"
echo "$TS"

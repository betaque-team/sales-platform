#!/usr/bin/env bash
# =============================================================================
# infra/scripts/restore.sh — Restore database from backup
# Called by: make restore, make rollback-full
# Usage: bash infra/scripts/restore.sh [TIMESTAMP]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-jobplatform}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'
log()   { echo -e "${GREEN}[restore] $*${NC}"; }
warn()  { echo -e "${YELLOW}[restore] $*${NC}"; }
error() { echo -e "${RED}[restore] ERROR: $*${NC}" >&2; exit 1; }

# ── Pick backup ──────────────────────────────────────────────────────────────
BACKUP_ID="${1:-}"
if [[ -z "$BACKUP_ID" ]]; then
  echo -e "${BOLD}Available backups:${NC}"
  bash "$SCRIPT_DIR/backup.sh" --list
  echo
  echo "Usage: make restore  OR  bash infra/scripts/restore.sh <TIMESTAMP>"
  exit 0
fi

DEST="$BACKUP_DIR/$BACKUP_ID"
[[ -d "$DEST" ]]                   || error "Backup not found: $DEST"
[[ -f "$DEST/jobplatform.pgdump" ]] || error "Dump file missing"
[[ -f "$DEST/checksums.sha256" ]]   || error "Checksum file missing"
[[ -f "$DEST/manifest.json" ]]      || error "Manifest missing"

# ── Show info ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}Restoring from: $BACKUP_ID${NC}"
python3 -c "
import json
m=json.load(open('$DEST/manifest.json'))
print(f\"  Created:   {m['created_at']}\")
print(f\"  Rows:      {m['total_rows']:,}\")
print(f\"  Migration: {m['alembic_revision']}\")
print(f\"  Label:     {m.get('label','')}\")
"

# ── Verify checksums ─────────────────────────────────────────────────────────
log "Verifying checksums..."
(cd "$DEST" && shasum -a 256 -c checksums.sha256 --quiet) || error "Checksum FAILED — backup may be corrupt"
log "Checksums OK"

# ── Confirm ───────────────────────────────────────────────────────────────────
echo
warn "This will DROP the '$DB_NAME' database and restore from backup."
warn "All current data will be REPLACED."
read -r -p "  Type 'yes, restore' to proceed: " CONFIRM
[[ "$CONFIRM" == "yes, restore" ]] || { warn "Aborted."; exit 0; }

# ── Stop app ──────────────────────────────────────────────────────────────────
log "Stopping application services..."
$COMPOSE stop backend celery-worker celery-beat 2>/dev/null || true

# ── Drop + recreate DB ────────────────────────────────────────────────────────
log "Dropping and recreating database..."
$COMPOSE exec -T postgres psql -U "$DB_USER" postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid<>pg_backend_pid();" 2>/dev/null || true
$COMPOSE exec -T postgres psql -U "$DB_USER" postgres -c "DROP DATABASE IF EXISTS $DB_NAME;"
$COMPOSE exec -T postgres psql -U "$DB_USER" postgres -c "CREATE DATABASE $DB_NAME;"

# ── Restore ───────────────────────────────────────────────────────────────────
log "Restoring database (this may take a moment)..."
$COMPOSE exec -T postgres pg_restore -U "$DB_USER" -d "$DB_NAME" --no-password --exit-on-error \
  < "$DEST/jobplatform.pgdump"

# ── Restart app ───────────────────────────────────────────────────────────────
log "Restarting application services..."
$COMPOSE start backend celery-worker celery-beat

# ── Validate ──────────────────────────────────────────────────────────────────
sleep 5
log "Validating restoration..."
RESTORED=$($COMPOSE exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT json_agg(row_to_json(t)) FROM (
    SELECT relname AS \"table\", n_live_tup::int AS rows
    FROM pg_stat_user_tables ORDER BY relname
  ) t;" | tr -d '\n')

python3 - "$DEST/manifest.json" "$RESTORED" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
expected = {t['table']: t['rows'] for t in (m.get('table_row_counts') or [])}
restored = {t['table']: t['rows'] for t in (json.loads(sys.argv[2]) or [])}
key = ['jobs','companies','company_contacts','users','resumes','company_ats_boards']
ok = True
for t in key:
    e, g = expected.get(t, 0), restored.get(t, 0)
    s = "OK" if (g >= e * 0.95 or e == 0) else "MISMATCH"
    if s != "OK": ok = False
    print(f"  {s:8s} {t:30s} expected={e:>9,}  restored={g:>9,}")
print(f"\n  {'PASSED' if ok else 'FAILED'}")
PY

echo -e "${GREEN}Restore complete — $BACKUP_ID${NC}"

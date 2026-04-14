#!/usr/bin/env bash
# =============================================================================
# restore.sh — Restore a backup with checksum verification and row-count
#              validation. Safe: stops app before restore, restarts after.
# Usage: bash scripts/restore.sh <TIMESTAMP>
#        bash scripts/restore.sh          ← lists available backups
# =============================================================================
set -euo pipefail

DOCKER="${DOCKER_BIN:-/usr/local/bin/docker}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PLATFORM_DIR/backups"
CONTAINER="${PG_CONTAINER:-platform-postgres-1}"
DB_NAME="${POSTGRES_DB:-jobplatform}"
DB_USER="${POSTGRES_USER:-postgres}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()    { echo -e "${GREEN}[$(date +%H:%M:%S)] ✔  $*${NC}"; }
warn()   { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠  $*${NC}"; }
error()  { echo -e "${RED}[$(date +%H:%M:%S)] ✘  ERROR: $*${NC}" >&2; exit 1; }
header() { echo -e "\n${BOLD}$*${NC}"; }

# ── list backups if no arg ────────────────────────────────────────────────────
BACKUP_ID="${1:-}"
if [[ -z "$BACKUP_ID" ]]; then
  header "Available backups:"
  COUNT=0
  while IFS= read -r b; do
    MANIFEST="$b/manifest.json"
    if [[ -f "$MANIFEST" ]]; then
      python3 - "$MANIFEST" "$(basename "$b")" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
ts   = sys.argv[2]
cat  = m.get('created_at', '?')
rows = m.get('total_rows', '?')
rev  = m.get('alembic_revision', '?')
lbl  = f"  [{m['label']}]" if m.get('label') else ''
sz   = m.get('dump_size_bytes', 0) / 1024 / 1024
print(f"  {ts}   {cat}   rows={rows:,}   rev={rev}   {sz:.1f}MB{lbl}")
PYEOF
    else
      echo "  $(basename "$b")   (no manifest)"
    fi
    COUNT=$((COUNT+1))
  done < <(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null)
  [[ $COUNT -gt 0 ]] || warn "No backups found in $BACKUP_DIR"
  echo
  echo    "  Usage: bash scripts/restore.sh <TIMESTAMP>"
  echo    "  Example: bash scripts/restore.sh $(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo 20240101_120000)"
  exit 0
fi

BACKUP_PATH="$BACKUP_DIR/$BACKUP_ID"
[[ -d "$BACKUP_PATH" ]]                   || error "Backup not found: $BACKUP_PATH"
[[ -f "$BACKUP_PATH/jobplatform.pgdump" ]] || error "Dump file missing: $BACKUP_PATH/jobplatform.pgdump"
[[ -f "$BACKUP_PATH/checksums.sha256" ]]   || error "checksums.sha256 missing"
[[ -f "$BACKUP_PATH/manifest.json" ]]      || error "manifest.json missing"

# ── show backup details ───────────────────────────────────────────────────────
header "Backup to restore: $BACKUP_ID"
python3 - "$BACKUP_PATH/manifest.json" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))
print(f"  Created:      {m.get('created_at','?')}")
print(f"  Label:        {m.get('label') or '(none)'}")
print(f"  Database:     {m.get('database','?')}")
print(f"  Migration:    {m.get('alembic_revision','?')}")
print(f"  Total rows:   {m.get('total_rows',0):,}")
tables = m.get('table_row_counts') or []
top = sorted(tables, key=lambda x: x['rows'], reverse=True)[:8]
print(f"\n  Key tables:")
for t in top:
    print(f"    {t['table']:35s} {t['rows']:>10,}")
PYEOF

# ── step 1: checksum verification ────────────────────────────────────────────
header "Step 1 / 5 — Checksum verification"
(cd "$BACKUP_PATH" && shasum -a 256 -c checksums.sha256) \
  || error "Checksum verification FAILED — backup may be corrupt. Aborting."
log "All checksums verified ✓"

# ── step 2: dump probe ───────────────────────────────────────────────────────
header "Step 2 / 5 — Dump structure probe"
TABLE_COUNT=$("$DOCKER" exec -i "$CONTAINER" pg_restore --list \
  < "$BACKUP_PATH/jobplatform.pgdump" 2>/dev/null \
  | grep -c "TABLE DATA" || true)
log "pg_restore --list: $TABLE_COUNT TABLE DATA sections"
[[ "$TABLE_COUNT" -ge 10 ]] || error "Dump appears incomplete ($TABLE_COUNT tables). Aborting."

# ── step 3: user confirmation ────────────────────────────────────────────────
header "Step 3 / 5 — Confirmation"
warn "⚠️  This will DROP the '$DB_NAME' database and restore from backup $BACKUP_ID."
warn "   All current data will be PERMANENTLY REPLACED."
warn "   The backend will be stopped during restore and restarted after."
echo
read -r -p "  Type 'yes, restore' to proceed: " CONFIRM
[[ "$CONFIRM" == "yes, restore" ]] || { warn "Aborted — no changes made."; exit 0; }

# ── step 4: stop app → drop/recreate → restore ────────────────────────────────
header "Step 4 / 5 — Database restoration"

log "Stopping application containers..."
"$DOCKER" stop platform-backend-1 platform-celery-worker-1 platform-celery-beat-1 2>/dev/null || warn "Some app containers were not running"

log "Terminating active DB connections..."
"$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" postgres -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid();" 2>/dev/null || true

log "Dropping database '$DB_NAME'..."
"$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" postgres \
  -c "DROP DATABASE IF EXISTS $DB_NAME;"

log "Creating database '$DB_NAME'..."
"$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" postgres \
  -c "CREATE DATABASE $DB_NAME;"

log "Restoring from $BACKUP_ID (this may take a moment)..."
"$DOCKER" exec -i "$CONTAINER" pg_restore \
  -U "$DB_USER" -d "$DB_NAME" \
  --no-password --exit-on-error \
  < "$BACKUP_PATH/jobplatform.pgdump"
log "pg_restore finished"

log "Restarting application containers..."
"$DOCKER" start platform-backend-1 platform-celery-worker-1 platform-celery-beat-1
sleep 5

# ── step 5: row-count validation ──────────────────────────────────────────────
header "Step 5 / 5 — Validation"

RESTORED_JSON=$("$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT json_agg(row_to_json(t)) FROM (
    SELECT relname AS \"table\", n_live_tup::int AS rows
    FROM pg_stat_user_tables ORDER BY relname
  ) t;" 2>/dev/null | tr -d '\n')

VALIDATION_RESULT=$(python3 - "$BACKUP_PATH/manifest.json" "$RESTORED_JSON" <<'PYEOF'
import json, sys

manifest   = json.load(open(sys.argv[1]))
raw        = sys.argv[2]
expected   = {t['table']: t['rows'] for t in (manifest.get('table_row_counts') or [])}
try:
    restored = {t['table']: t['rows'] for t in (json.loads(raw) or [])}
except Exception as e:
    print(f"WARN: Could not parse restored counts: {e}")
    sys.exit(0)

key_tables = ['jobs','companies','company_contacts','users','resumes',
              'scan_logs','company_ats_boards','role_cluster_configs']

failures = 0
print("\n  Table validation (key tables):")
for tbl in key_tables:
    exp = expected.get(tbl, 0)
    got = restored.get(tbl, 0)
    pct = (got / exp * 100) if exp > 0 else 100
    ok  = pct >= 99.0
    sym = "✓" if ok else "✗"
    print(f"  {sym} {tbl:35s} expected={exp:>9,}  restored={got:>9,}  ({pct:.1f}%)")
    if not ok:
        failures += 1

exp_total = manifest.get('total_rows', 0)
got_total = sum(restored.values())
print(f"\n  Total rows: expected={exp_total:,}  restored={got_total:,}")
if failures:
    print(f"\n  ❌ VALIDATION FAILED: {failures} table(s) below 99% threshold")
    sys.exit(1)
else:
    print(f"\n  ✅ VALIDATION PASSED")
PYEOF
)
echo "$VALIDATION_RESULT"

ALEMBIC_CURRENT=$("$DOCKER" exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c \
  "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '[:space:]')
ALEMBIC_EXPECTED=$(python3 -c "import json; print(json.load(open('$BACKUP_PATH/manifest.json')).get('alembic_revision','?'))")
if [[ "$ALEMBIC_CURRENT" == "$ALEMBIC_EXPECTED" ]]; then
  log "Migration revision matches: $ALEMBIC_CURRENT ✓"
else
  warn "Migration mismatch — backup=$ALEMBIC_EXPECTED  current=$ALEMBIC_CURRENT"
  warn "You may need to run: docker exec platform-backend-1 alembic upgrade head"
fi

# ── summary ───────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  🎉 Restore complete!${NC}"
echo    "  Backup:   $BACKUP_ID"
echo    "  Database: $DB_NAME"
echo    "  Platform: http://localhost:3000"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

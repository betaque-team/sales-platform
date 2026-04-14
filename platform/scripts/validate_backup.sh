#!/usr/bin/env bash
# =============================================================================
# validate_backup.sh — Verify checksums and inspect a backup without restoring
# Usage: bash scripts/validate_backup.sh [TIMESTAMP]
#        If TIMESTAMP omitted, validates the latest backup.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="$(dirname "$SCRIPT_DIR")/backups"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()   { echo -e "${GREEN}[$(date +%H:%M:%S)] ✔  $*${NC}"; }
warn()  { echo -e "${YELLOW}[$(date +%H:%M:%S)] ⚠  $*${NC}"; }
fail()  { echo -e "${RED}[$(date +%H:%M:%S)] ✘  $*${NC}" >&2; ERRORS=$((ERRORS+1)); }

ERRORS=0

# ── pick backup ───────────────────────────────────────────────────────────────
BACKUP_ID="${1:-}"
if [[ -z "$BACKUP_ID" ]]; then
  BACKUP_ID=$(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | head -1 | xargs basename 2>/dev/null || true)
  [[ -n "$BACKUP_ID" ]] || { echo "No backups found in $BACKUP_DIR"; exit 1; }
  warn "No timestamp given — validating latest: $BACKUP_ID"
fi

BACKUP_PATH="$BACKUP_DIR/$BACKUP_ID"
[[ -d "$BACKUP_PATH" ]] || { echo -e "${RED}Backup not found: $BACKUP_PATH${NC}"; exit 1; }

echo -e "\n${BOLD}Validating backup: $BACKUP_ID${NC}"
echo    "  Path: $BACKUP_PATH"

# ── 1. required files present ────────────────────────────────────────────────
echo
echo -e "${BOLD}[1/4] File presence check${NC}"
for f in jobplatform.pgdump jobplatform.sql.gz checksums.sha256 manifest.json; do
  if [[ -f "$BACKUP_PATH/$f" ]]; then
    SIZE=$(du -sh "$BACKUP_PATH/$f" | cut -f1)
    log "$f  ($SIZE)"
  else
    fail "MISSING: $f"
  fi
done

# ── 2. checksums ──────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}[2/4] SHA-256 checksum verification${NC}"
if [[ -f "$BACKUP_PATH/checksums.sha256" ]]; then
  if (cd "$BACKUP_PATH" && shasum -a 256 -c checksums.sha256 --quiet 2>&1); then
    log "All checksums match"
  else
    fail "Checksum mismatch — backup may be corrupt"
  fi
else
  fail "checksums.sha256 missing — cannot verify integrity"
fi

# ── 3. manifest inspection ────────────────────────────────────────────────────
echo
echo -e "${BOLD}[3/4] Manifest inspection${NC}"
if [[ -f "$BACKUP_PATH/manifest.json" ]]; then
  python3 - "$BACKUP_PATH/manifest.json" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
    m = json.load(f)
print(f"  created_at:    {m.get('created_at', '?')}")
print(f"  label:         {m.get('label') or '(none)'}")
print(f"  database:      {m.get('database', '?')}")
print(f"  migration rev: {m.get('alembic_revision', '?')}")
print(f"  total_rows:    {m.get('total_rows', '?'):,}" if isinstance(m.get('total_rows'), int) else f"  total_rows:    {m.get('total_rows', '?')}")
dump_mb  = m.get('dump_size_bytes', 0) / 1024 / 1024
sql_mb   = m.get('sql_gz_size_bytes', 0) / 1024 / 1024
print(f"  dump size:     {dump_mb:.2f} MB (.pgdump)")
print(f"  sql.gz size:   {sql_mb:.2f} MB (.sql.gz)")
tables = m.get('table_row_counts') or []
if tables:
    print(f"\n  Top tables by row count:")
    for t in sorted(tables, key=lambda x: x['rows'], reverse=True)[:10]:
        print(f"    {t['table']:35s} {t['rows']:>10,}")
PYEOF
  log "Manifest parsed successfully"
else
  fail "manifest.json missing"
fi

# ── 4. dump structure probe (non-destructive) ─────────────────────────────────
echo
echo -e "${BOLD}[4/4] Dump structure probe (pg_restore --list)${NC}"
DOCKER="${DOCKER_BIN:-/usr/local/bin/docker}"
CONTAINER="${PG_CONTAINER:-platform-postgres-1}"
if "$DOCKER" inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -q running; then
  TABLE_COUNT=$("$DOCKER" exec -i "$CONTAINER" pg_restore --list \
    < "$BACKUP_PATH/jobplatform.pgdump" 2>/dev/null \
    | grep -c "TABLE DATA" || true)
  log "pg_restore --list: $TABLE_COUNT TABLE DATA entries found"
  if [[ "$TABLE_COUNT" -lt 10 ]]; then
    fail "Fewer than 10 tables in dump — may be incomplete"
  fi
else
  warn "Postgres container not running — skipping dump probe"
fi

# ── result ────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [[ $ERRORS -eq 0 ]]; then
  echo -e "${GREEN}  ✅ Backup $BACKUP_ID is VALID${NC}"
else
  echo -e "${RED}  ❌ Backup $BACKUP_ID has $ERRORS issue(s) — DO NOT USE for restore${NC}"
  exit 1
fi
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

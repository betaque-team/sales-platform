#!/usr/bin/env bash
# =============================================================================
# infra/scripts/validate-backup.sh — Verify backup integrity
# Usage: bash infra/scripts/validate-backup.sh [TIMESTAMP]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"

GREEN='\033[0;32m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ERRORS=0

BACKUP_ID="${1:-}"
if [[ -z "$BACKUP_ID" ]]; then
  BACKUP_ID=$(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | head -1 | xargs basename 2>/dev/null || true)
  [[ -n "$BACKUP_ID" ]] || { echo "No backups found"; exit 1; }
fi

DEST="$BACKUP_DIR/$BACKUP_ID"
[[ -d "$DEST" ]] || { echo "Backup not found: $DEST"; exit 1; }

echo -e "${BOLD}Validating: $BACKUP_ID${NC}\n"

# Files present
for f in jobplatform.pgdump jobplatform.sql.gz checksums.sha256 manifest.json; do
  if [[ -f "$DEST/$f" ]]; then
    echo -e "  ${GREEN}OK${NC}  $f ($(du -sh "$DEST/$f" | cut -f1))"
  else
    echo -e "  ${RED}MISSING${NC}  $f"; ERRORS=$((ERRORS+1))
  fi
done

# Checksums
echo
if (cd "$DEST" && shasum -a 256 -c checksums.sha256 --quiet 2>&1); then
  echo -e "  ${GREEN}OK${NC}  SHA-256 checksums match"
else
  echo -e "  ${RED}FAIL${NC}  Checksum mismatch"; ERRORS=$((ERRORS+1))
fi

# Manifest
echo
if [[ -f "$DEST/manifest.json" ]]; then
  python3 -c "
import json
m=json.load(open('$DEST/manifest.json'))
print(f\"  Rows:      {m.get('total_rows','?'):,}\")
print(f\"  Migration: {m.get('alembic_revision','?')}\")
print(f\"  Created:   {m.get('created_at','?')}\")
print(f\"  Label:     {m.get('label','')}\")
"
fi

# Dump probe
TABLE_COUNT=$($COMPOSE exec -T postgres pg_restore --list < "$DEST/jobplatform.pgdump" 2>/dev/null | grep -c "TABLE DATA" || true)
echo -e "  Tables:    $TABLE_COUNT"
[[ "$TABLE_COUNT" -ge 10 ]] || { echo -e "  ${RED}FAIL${NC}  Fewer than 10 tables"; ERRORS=$((ERRORS+1)); }

echo
if [[ $ERRORS -eq 0 ]]; then
  echo -e "${GREEN}VALID — backup $BACKUP_ID is OK${NC}"
else
  echo -e "${RED}INVALID — $ERRORS issue(s) found${NC}"; exit 1
fi

#!/usr/bin/env bash
# =============================================================================
# rollback.sh — Quick rollback wrapper
#
# Usage:
#   bash scripts/rollback.sh                          # rollback to previous
#   bash scripts/rollback.sh 20260406_120000           # specific release
#   bash scripts/rollback.sh --with-db                 # rollback + restore DB
#   bash scripts/rollback.sh 20260406_120000 --with-db # specific + DB restore
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(dirname "$SCRIPT_DIR")/ansible"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'

cd "$ANSIBLE_DIR"

TARGET=""
RESTORE_DB="false"
EXTRA_VARS=""

for arg in "$@"; do
  case "$arg" in
    --with-db)  RESTORE_DB="true" ;;
    *)          TARGET="$arg" ;;
  esac
done

if [[ -n "$TARGET" ]]; then
  EXTRA_VARS="$EXTRA_VARS -e target=$TARGET"
fi
EXTRA_VARS="$EXTRA_VARS -e restore_db=$RESTORE_DB"

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${RED}  ⏪ Rolling Back Sales Platform${NC}"
echo    "  Target:      ${TARGET:-previous release}"
echo    "  Restore DB:  ${RESTORE_DB}"
echo    "  Time:        $(date)"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

echo -e "${YELLOW}This will:${NC}"
echo    "  1. Take a safety backup of current database"
echo    "  2. Rebuild images from ${TARGET:-the previous} release"
if [[ "$RESTORE_DB" == "true" ]]; then
  echo -e "  3. ${RED}RESTORE DATABASE${NC} from the pre-deploy backup of that release"
fi
echo    "  4. Swap to the target release"
echo    "  5. Restart all services"
echo    "  6. Verify health"
echo
read -r -p "  Continue? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
echo

ansible-playbook playbooks/rollback.yml $EXTRA_VARS -v

echo
echo -e "${GREEN}✅ Rollback finished.${NC}"
echo -e "   Status: ${BOLD}ansible-playbook playbooks/status.yml${NC}"

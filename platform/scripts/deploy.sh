#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Quick deploy wrapper
#
# Usage:
#   bash scripts/deploy.sh                # deploy main branch
#   bash scripts/deploy.sh feature/xyz    # deploy specific branch
#   bash scripts/deploy.sh --dry-run      # preview changes without applying
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANSIBLE_DIR="$(dirname "$SCRIPT_DIR")/ansible"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'

cd "$ANSIBLE_DIR"

BRANCH="${1:-}"
DRY_RUN=""
EXTRA_VARS=""

if [[ "$BRANCH" == "--dry-run" ]]; then
  DRY_RUN="--check --diff"
  BRANCH=""
elif [[ "$BRANCH" == *"--dry-run"* ]]; then
  DRY_RUN="--check --diff"
  BRANCH="${BRANCH//--dry-run/}"
  BRANCH="${BRANCH// /}"
fi

if [[ -n "$BRANCH" ]]; then
  EXTRA_VARS="-e deploy_branch=$BRANCH"
fi

echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  🚀 Deploying Sales Platform${NC}"
echo    "  Branch:    ${BRANCH:-main}"
echo    "  Mode:      ${DRY_RUN:-LIVE}"
echo    "  Time:      $(date)"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo

if [[ -z "$DRY_RUN" ]]; then
  echo -e "${YELLOW}This will:${NC}"
  echo    "  1. Take a pre-deploy database backup"
  echo    "  2. Pull latest code from ${BRANCH:-main}"
  echo    "  3. Build new Docker images on the server"
  echo    "  4. Run database migrations"
  echo    "  5. Rolling-restart all services"
  echo    "  6. Verify health"
  echo
  read -r -p "  Continue? [y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
  echo
fi

ansible-playbook playbooks/deploy.yml $EXTRA_VARS $DRY_RUN -v

echo
echo -e "${GREEN}✅ Deploy finished.${NC}"
echo -e "   Status:   ${BOLD}ansible-playbook playbooks/status.yml${NC}"
echo -e "   Rollback: ${BOLD}bash scripts/rollback.sh${NC}"

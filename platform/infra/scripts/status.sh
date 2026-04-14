#!/usr/bin/env bash
# =============================================================================
# infra/scripts/status.sh — Platform health and status report
# Called by: make status
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'

echo -e "${BOLD}═══════════════════════════════════════════════${NC}"
echo -e "${BOLD}       SALES PLATFORM STATUS REPORT${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════${NC}"

# ── Containers ────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Containers:${NC}"
$COMPOSE ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  (compose not running)"

# ── Health ────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Health:${NC}"
BACKEND_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/monitoring 2>/dev/null || echo "000")
FRONTEND_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000 2>/dev/null || echo "000")

if [[ "$BACKEND_CODE" == "200" || "$BACKEND_CODE" == "401" ]]; then
  echo -e "  Backend:  ${GREEN}HEALTHY${NC} ($BACKEND_CODE)"
else
  echo -e "  Backend:  ${RED}DOWN${NC} ($BACKEND_CODE)"
fi
if [[ "$FRONTEND_CODE" == "200" ]]; then
  echo -e "  Frontend: ${GREEN}HEALTHY${NC} ($FRONTEND_CODE)"
else
  echo -e "  Frontend: ${RED}DOWN${NC} ($FRONTEND_CODE)"
fi

# ── Database ──────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Database:${NC}"
$COMPOSE exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" -c "
  SELECT relname AS table, n_live_tup AS rows
  FROM pg_stat_user_tables WHERE n_live_tup > 0
  ORDER BY n_live_tup DESC LIMIT 8;" 2>/dev/null || echo "  (unavailable)"

ALEMBIC=$($COMPOSE exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-jobplatform}" \
  -t -A -c "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '[:space:]')
echo "  Migration: ${ALEMBIC:-unknown}"

# ── Current release ──────────────────────────────────────────────────────────
echo -e "\n${BOLD}Release:${NC}"
if [[ -f "$PROJECT_DIR/.last-deploy.json" ]]; then
  python3 -c "
import json
d=json.load(open('$PROJECT_DIR/.last-deploy.json'))
print(f\"  Tag:         {d.get('release','?')}\")
print(f\"  Deployed at: {d.get('deployed_at','?')}\")
print(f\"  Branch:      {d.get('branch','?')}\")
action=d.get('action','')
if action: print(f\"  Action:      {action}\")
" 2>/dev/null
else
  echo "  No deploy metadata found"
fi

# ── Docker images ─────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Images:${NC}"
docker images platform-backend --format "  backend:   {{.Tag}}  {{.Size}}  {{.CreatedSince}}" | head -3
docker images platform-frontend --format "  frontend:  {{.Tag}}  {{.Size}}  {{.CreatedSince}}" | head -3

# ── Backups ───────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Backups:${NC}"
BACKUP_COUNT=$(ls -d "$BACKUP_DIR"/[0-9]* 2>/dev/null | wc -l | tr -d ' ')
LATEST=$(ls -dt "$BACKUP_DIR"/[0-9]* 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo "none")
echo "  Count:  $BACKUP_COUNT"
echo "  Latest: $LATEST"

# ── Disk ──────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}Disk:${NC}"
df -h / | awk 'NR==2{printf "  Total: %s  Used: %s  Free: %s  Usage: %s\n", $2, $3, $4, $5}'
echo "  Docker volumes: $(docker system df --format '{{.Size}}' 2>/dev/null | head -1 || echo 'N/A')"

echo -e "\n${BOLD}═══════════════════════════════════════════════${NC}"

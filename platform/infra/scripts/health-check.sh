#!/usr/bin/env bash
# =============================================================================
# infra/scripts/health-check.sh — Wait for all services to be healthy
# Called by: make deploy, rollback.sh
# =============================================================================
set -euo pipefail

MAX_WAIT=90
INTERVAL=5
ELAPSED=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

check_backend() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/monitoring 2>/dev/null || echo "000")
  [[ "$code" == "200" || "$code" == "401" ]]
}

check_frontend() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000 2>/dev/null || echo "000")
  [[ "$code" == "200" ]]
}

echo -n "  Waiting for services"
while [[ $ELAPSED -lt $MAX_WAIT ]]; do
  BACKEND_OK=false
  FRONTEND_OK=false
  check_backend  && BACKEND_OK=true
  check_frontend && FRONTEND_OK=true

  if $BACKEND_OK && $FRONTEND_OK; then
    echo
    echo -e "  ${GREEN}Backend:  HEALTHY${NC}"
    echo -e "  ${GREEN}Frontend: HEALTHY${NC}"
    exit 0
  fi

  echo -n "."
  sleep $INTERVAL
  ELAPSED=$((ELAPSED + INTERVAL))
done

echo
echo -e "  ${RED}Health check FAILED after ${MAX_WAIT}s${NC}"
if ! $BACKEND_OK;  then echo -e "  ${RED}Backend:  DOWN${NC}"; fi
if ! $FRONTEND_OK; then echo -e "  ${RED}Frontend: DOWN${NC}"; fi
echo -e "  ${YELLOW}Check logs: make logs${NC}"
exit 1

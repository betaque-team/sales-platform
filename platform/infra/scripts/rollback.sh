#!/usr/bin/env bash
# =============================================================================
# infra/scripts/rollback.sh — Rollback to previous Docker image tag
# Called by: make rollback, make rollback-full
#
# How it works:
#   - Reads .last-deploy.json to find current release
#   - Lists locally tagged images to find the previous tag
#   - Swaps RELEASE_TAG and restarts containers
#   - If --with-db: also restores the pre-deploy backup of current release
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'
log()   { echo -e "${GREEN}[rollback] $*${NC}"; }
warn()  { echo -e "${YELLOW}[rollback] $*${NC}"; }
error() { echo -e "${RED}[rollback] ERROR: $*${NC}" >&2; exit 1; }

RESTORE_DB=false
for arg in "$@"; do
  [[ "$arg" == "--with-db" ]] && RESTORE_DB=true
done

# ── Find current and previous tags ───────────────────────────────────────────
CURRENT_TAG="latest"
if [[ -f "$PROJECT_DIR/.last-deploy.json" ]]; then
  CURRENT_TAG=$(python3 -c "import json; print(json.load(open('$PROJECT_DIR/.last-deploy.json')).get('release','latest'))" 2>/dev/null || echo "latest")
fi

# List available image tags (sorted desc, skip 'latest')
BACKEND_TAGS=$(docker images platform-backend --format "{{.Tag}}" | grep -v latest | sort -r)
PREV_TAG=""
FOUND_CURRENT=false
for tag in $BACKEND_TAGS; do
  if $FOUND_CURRENT; then
    PREV_TAG="$tag"
    break
  fi
  [[ "$tag" == "$CURRENT_TAG" ]] && FOUND_CURRENT=true
done

# Fallback: if we can't find previous, use the second newest tag
if [[ -z "$PREV_TAG" ]]; then
  PREV_TAG=$(echo "$BACKEND_TAGS" | head -2 | tail -1)
fi

if [[ -z "$PREV_TAG" ]]; then
  error "No previous release found. Available tags: $BACKEND_TAGS"
fi

echo -e "${BOLD}━━━ Rollback Plan ━━━${NC}"
echo "  Current:    $CURRENT_TAG"
echo "  Target:     $PREV_TAG"
echo "  Restore DB: $RESTORE_DB"
echo

warn "This will rollback the platform to release $PREV_TAG"
if $RESTORE_DB; then
  warn "AND restore the database from pre-deploy backup"
fi
read -r -p "  Continue? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Aborted."; exit 0; }

# ── Safety backup ─────────────────────────────────────────────────────────────
log "Safety backup of current state..."
bash "$SCRIPT_DIR/backup.sh" --label "pre-rollback-from-$CURRENT_TAG" >/dev/null

# ── DB restore (if --with-db) ────────────────────────────────────────────────
if $RESTORE_DB; then
  # Find the pre-deploy backup that matches the CURRENT deploy
  BACKUP_FILE=$(ls -t "$BACKUP_DIR"/*/manifest.json 2>/dev/null | while read m; do
    LBL=$(python3 -c "import json; print(json.load(open('$m')).get('label',''))" 2>/dev/null)
    if [[ "$LBL" == *"pre-deploy-$CURRENT_TAG"* ]]; then
      dirname "$m" | xargs basename
      break
    fi
  done)

  if [[ -n "$BACKUP_FILE" ]]; then
    log "Restoring database from backup: $BACKUP_FILE"
    echo "yes, restore" | bash "$SCRIPT_DIR/restore.sh" "$BACKUP_FILE"
  else
    warn "No pre-deploy backup found for $CURRENT_TAG — skipping DB restore"
  fi
fi

# ── Swap to previous image tag ───────────────────────────────────────────────
log "Restarting with image tag: $PREV_TAG"
export RELEASE_TAG="$PREV_TAG"
$COMPOSE up -d --no-deps backend celery-worker celery-beat frontend

# ── Health check ──────────────────────────────────────────────────────────────
log "Waiting for health..."
bash "$SCRIPT_DIR/health-check.sh"

# ── Record rollback ──────────────────────────────────────────────────────────
echo "{\"release\":\"$PREV_TAG\",\"deployed_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"action\":\"rollback\",\"from\":\"$CURRENT_TAG\"}" > "$PROJECT_DIR/.last-deploy.json"

echo -e "${GREEN}✅ Rollback to $PREV_TAG complete${NC}"

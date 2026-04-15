#!/usr/bin/env bash
# =============================================================================
# ci-deploy.sh — VM-side deploy orchestrator, invoked over SSH by CI
#
# Installed at: /opt/sales-platform/scripts/ci-deploy.sh (mode 0755, owner deploy)
# Called via forced-command SSH (authorized_keys command="...") — so any
# command string the client sends arrives in $SSH_ORIGINAL_COMMAND. We parse
# that ourselves and only allow a strict subset of actions.
#
# Supported actions:
#   deploy <TAG>        -- pull new GHCR images, run migrations, rolling restart,
#                          health-check, auto-rollback on failure
#   rollback <TAG>      -- swap RELEASE_TAG to a prior tag (images must already
#                          be pulled/cached locally), restart
#   status              -- print compose ps + last-deploy.json
#
# Design rules:
#   - Tag must match ^[a-zA-Z0-9_.-]+$ (defeats shell injection)
#   - All state written to /opt/sales-platform: .env (RELEASE_TAG=...),
#     .last-deploy.json, .prev-release
#   - Logs to /opt/sales-platform/logs/ci-deploy.log
# =============================================================================
set -euo pipefail

APP_DIR="/opt/sales-platform"
COMPOSE="docker compose -f docker-compose.prod.yml"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/ci-deploy.log"
GHCR_IMAGE_BACKEND="${GHCR_IMAGE_BACKEND:-ghcr.io/betaque-team/sales-platform/backend}"
GHCR_IMAGE_FRONTEND="${GHCR_IMAGE_FRONTEND:-ghcr.io/betaque-team/sales-platform/frontend}"

mkdir -p "$LOG_DIR"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

validate_tag() {
  [[ "${1:-}" =~ ^[a-zA-Z0-9_.-]+$ ]] || die "Invalid tag format: '${1:-}' (allowed: alphanumeric, dot, dash, underscore)"
  [[ "${#1}" -le 64 ]] || die "Tag too long (>64 chars)"
}

# -----------------------------------------------------------------------------
# Set RELEASE_TAG in .env (persisted for future compose commands) and export
# -----------------------------------------------------------------------------
set_release_tag() {
  local tag="$1"
  cd "$APP_DIR"
  if grep -q "^RELEASE_TAG=" .env 2>/dev/null; then
    sed -i.bak "s|^RELEASE_TAG=.*|RELEASE_TAG=${tag}|" .env && rm -f .env.bak
  else
    echo "RELEASE_TAG=${tag}" >> .env
  fi
  export RELEASE_TAG="$tag"
}

# -----------------------------------------------------------------------------
# Read currently-deployed tag from .env (falls back to "latest")
# -----------------------------------------------------------------------------
current_tag() {
  grep -E "^RELEASE_TAG=" "$APP_DIR/.env" 2>/dev/null | cut -d= -f2 | head -1 || echo "latest"
}

# -----------------------------------------------------------------------------
# Backup DB + app state before a deploy. Non-fatal if backup script missing.
# -----------------------------------------------------------------------------
pre_deploy_backup() {
  local label="$1"
  cd "$APP_DIR"
  local out="$APP_DIR/backups/pre-deploy-${label}.sql.gz"
  mkdir -p "$APP_DIR/backups"
  log "Taking pre-deploy DB backup -> $out"
  if $COMPOSE exec -T postgres pg_dump -U postgres jobplatform 2>/dev/null | gzip > "$out"; then
    log "Backup OK ($(du -h "$out" | cut -f1))"
  else
    log "WARN: pg_dump failed; continuing anyway"
    rm -f "$out"
  fi
}

# -----------------------------------------------------------------------------
# Wait up to N seconds for backend to report healthy
# -----------------------------------------------------------------------------
wait_for_healthy() {
  local service="$1" timeout="${2:-60}"
  local waited=0
  cd "$APP_DIR"
  while (( waited < timeout )); do
    local status
    status="$($COMPOSE ps "$service" --format '{{.Status}}' 2>/dev/null || true)"
    if echo "$status" | grep -q "healthy"; then
      log "$service is healthy after ${waited}s"
      return 0
    fi
    # Accept "Up" for services without healthcheck
    if [[ "$service" != "backend" ]] && echo "$status" | grep -q "^Up"; then
      log "$service is up after ${waited}s"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 1
}

# -----------------------------------------------------------------------------
# Verify backend responds on its internal port (401 on monitoring is OK — means
# auth is enforced and the app is serving)
# -----------------------------------------------------------------------------
backend_http_check() {
  local code
  code="$(curl -o /dev/null -s -w "%{http_code}" --max-time 10 http://localhost:8000/api/v1/monitoring || echo "000")"
  [[ "$code" == "200" || "$code" == "401" ]]
}

# -----------------------------------------------------------------------------
# deploy <TAG>
# -----------------------------------------------------------------------------
action_deploy() {
  local tag="$1"
  validate_tag "$tag"
  cd "$APP_DIR"

  local prev
  prev="$(current_tag)"
  log "Deploy start: new=$tag, previous=$prev"
  echo "$prev" > "$APP_DIR/.prev-release"

  pre_deploy_backup "$tag"

  log "Pulling images tagged $tag"
  if ! docker pull "${GHCR_IMAGE_BACKEND}:${tag}"; then
    die "Failed to pull ${GHCR_IMAGE_BACKEND}:${tag}"
  fi
  if ! docker pull "${GHCR_IMAGE_FRONTEND}:${tag}"; then
    die "Failed to pull ${GHCR_IMAGE_FRONTEND}:${tag}"
  fi

  # Retag locally so existing compose image names (platform-backend:$RELEASE_TAG) match
  docker tag "${GHCR_IMAGE_BACKEND}:${tag}" "platform-backend:${tag}"
  docker tag "${GHCR_IMAGE_FRONTEND}:${tag}" "platform-frontend:${tag}"
  docker tag "${GHCR_IMAGE_BACKEND}:${tag}" "platform-backend:latest"
  docker tag "${GHCR_IMAGE_FRONTEND}:${tag}" "platform-frontend:latest"

  set_release_tag "$tag"

  log "Running alembic migrations"
  if ! $COMPOSE run --rm --no-deps backend alembic upgrade head; then
    log "Migration failed -- rolling back to $prev"
    set_release_tag "$prev"
    die "Migration failure"
  fi

  log "Rolling restart: backend"
  $COMPOSE up -d --no-deps backend

  if ! wait_for_healthy backend 90; then
    log "Backend failed to report healthy -- rolling back"
    set_release_tag "$prev"
    $COMPOSE up -d --no-deps backend
    die "Backend healthcheck timeout"
  fi

  if ! backend_http_check; then
    log "Backend HTTP probe failed -- rolling back"
    set_release_tag "$prev"
    $COMPOSE up -d --no-deps backend
    die "Backend HTTP probe failure"
  fi

  log "Rolling restart: celery-worker, celery-beat, frontend, nginx"
  $COMPOSE up -d --no-deps celery-worker celery-beat frontend nginx

  # Record success
  printf '{"release":"%s","previous":"%s","deployed_at":"%s"}\n' \
    "$tag" "$prev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$APP_DIR/.last-deploy.json"

  log "Cleanup: prune dangling images (keep last 3 tags)"
  docker image prune -f >/dev/null 2>&1 || true

  log "Deploy OK: $tag"
}

# -----------------------------------------------------------------------------
# rollback <TAG>
# -----------------------------------------------------------------------------
action_rollback() {
  local tag="$1"
  validate_tag "$tag"
  cd "$APP_DIR"

  # Check the image tag exists locally
  if ! docker image inspect "platform-backend:${tag}" >/dev/null 2>&1; then
    log "Image platform-backend:${tag} not local; pulling from GHCR"
    docker pull "${GHCR_IMAGE_BACKEND}:${tag}" || die "Cannot pull backend:${tag}"
    docker tag "${GHCR_IMAGE_BACKEND}:${tag}" "platform-backend:${tag}"
  fi
  if ! docker image inspect "platform-frontend:${tag}" >/dev/null 2>&1; then
    docker pull "${GHCR_IMAGE_FRONTEND}:${tag}" || die "Cannot pull frontend:${tag}"
    docker tag "${GHCR_IMAGE_FRONTEND}:${tag}" "platform-frontend:${tag}"
  fi

  local prev
  prev="$(current_tag)"
  log "Rollback: $prev -> $tag"
  set_release_tag "$tag"

  $COMPOSE up -d --no-deps backend
  wait_for_healthy backend 60 || log "WARN: backend not yet healthy post-rollback"
  $COMPOSE up -d --no-deps celery-worker celery-beat frontend nginx

  printf '{"release":"%s","previous":"%s","deployed_at":"%s","kind":"rollback"}\n' \
    "$tag" "$prev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$APP_DIR/.last-deploy.json"

  log "Rollback OK: $tag"
}

# -----------------------------------------------------------------------------
# status
# -----------------------------------------------------------------------------
action_status() {
  cd "$APP_DIR"
  echo "=== Current release ==="
  current_tag
  echo ""
  echo "=== Last deploy ==="
  cat "$APP_DIR/.last-deploy.json" 2>/dev/null || echo "(none)"
  echo ""
  echo "=== Containers ==="
  $COMPOSE ps --format "table {{.Name}}\t{{.Status}}"
}

# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------
# SSH_ORIGINAL_COMMAND contains whatever the client sent. If the script is run
# directly (not via forced-command SSH), fall back to $@.
CMD="${SSH_ORIGINAL_COMMAND:-$*}"
# shellcheck disable=SC2206
ARGS=($CMD)
ACTION="${ARGS[0]:-}"
ARG1="${ARGS[1]:-}"

case "$ACTION" in
  deploy)   action_deploy "$ARG1" ;;
  rollback) action_rollback "$ARG1" ;;
  status)   action_status ;;
  *)
    echo "Usage: deploy <TAG> | rollback <TAG> | status" >&2
    echo "Got: '$CMD'" >&2
    exit 1
    ;;
esac

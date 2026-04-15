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
#   deploy <TAG> [GHCR_USER]   -- pull new GHCR images, run migrations, rolling
#                                 restart, health-check, auto-rollback on fail.
#                                 If GHCR_USER is passed, the script reads one
#                                 line from stdin as a GHCR pull token and
#                                 `docker login`s before pulling (so private
#                                 packages work with no long-lived creds).
#   rollback <TAG> [GHCR_USER] -- swap RELEASE_TAG to a prior tag, restart.
#                                 Same optional GHCR_USER + stdin-token.
#   status                     -- print compose ps + last-deploy.json
#   install-script <NAME>      -- read a script body from stdin and install it
#                                 atomically at /opt/sales-platform/scripts/
#                                 <NAME>.sh (mode 0755). Used by the vm-ops
#                                 workflow to self-sync vm-ops.sh on each run.
#                                 NAME is whitelisted (vm-ops only).
#   ops <ACTION>               -- exec /opt/sales-platform/scripts/vm-ops.sh
#                                 with <ACTION>. vm-ops.sh enforces its own
#                                 action whitelist.
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

validate_ghcr_user() {
  # GitHub usernames: alphanumeric + hyphen, 1-39 chars
  [[ "${1:-}" =~ ^[a-zA-Z0-9-]{1,39}$ ]] || die "Invalid GHCR user: '${1:-}'"
}

# -----------------------------------------------------------------------------
# If a GHCR user is supplied, read a single-line token from stdin and log in
# to ghcr.io. The token lives only in the docker config (600, deploy-owned)
# for the duration of the deploy, then we `docker logout` at the end.
# -----------------------------------------------------------------------------
ghcr_login_from_stdin() {
  local user="$1"
  validate_ghcr_user "$user"
  local token
  # Read exactly one line; fail fast if nothing arrives within 10 s
  if ! IFS= read -rs -t 10 token; then
    die "Expected GHCR token on stdin (within 10s) but got none"
  fi
  [[ -n "$token" ]] || die "Empty GHCR token on stdin"
  # Feed the token via stdin to docker login (no process-listing exposure)
  if echo "$token" | docker login ghcr.io -u "$user" --password-stdin >/dev/null 2>&1; then
    log "ghcr login OK (user=$user)"
  else
    die "ghcr login failed"
  fi
  unset token
}

ghcr_logout() {
  docker logout ghcr.io >/dev/null 2>&1 || true
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
  local ghcr_user="${2:-}"
  validate_tag "$tag"
  cd "$APP_DIR"

  local prev
  prev="$(current_tag)"
  log "Deploy start: new=$tag, previous=$prev"
  echo "$prev" > "$APP_DIR/.prev-release"

  # Optional stdin-token login (needed for private GHCR packages)
  if [[ -n "$ghcr_user" ]]; then
    ghcr_login_from_stdin "$ghcr_user"
    # Ensure we log out even on failure
    trap 'ghcr_logout' EXIT
  fi

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

  log "Rolling restart: celery-worker, celery-beat, frontend"
  $COMPOSE up -d --no-deps celery-worker celery-beat frontend

  # Force-recreate nginx AFTER frontend is up. Without --force-recreate,
  # docker skips the restart (nginx image hash unchanged) and nginx keeps
  # its cached DNS pointing at the prior frontend container's IP, causing
  # 502 Bad Gateway for ~60s until docker's DNS ages out. Recreate fixes it
  # in <3s.
  log "Recreate nginx (force) to refresh upstream DNS"
  $COMPOSE up -d --no-deps --force-recreate nginx

  # Record success
  printf '{"release":"%s","previous":"%s","deployed_at":"%s"}\n' \
    "$tag" "$prev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$APP_DIR/.last-deploy.json"

  log "Cleanup: prune dangling + keep only last 3 tagged images"
  docker image prune -f >/dev/null 2>&1 || true
  # Drop all but the 3 most recent platform-backend / platform-frontend tags.
  # CreatedAt sort, skip first 3, rm the rest. -f in case a transient "is being
  # used by another container" error slips through.
  for repo in platform-backend platform-frontend; do
    docker images "$repo" --format '{{.CreatedAt}}\t{{.Tag}}' \
      | sort -r \
      | awk 'NR>3 && $NF != "latest" {print $NF}' \
      | while read -r stale_tag; do
          [[ -n "$stale_tag" ]] && docker rmi -f "${repo}:${stale_tag}" >/dev/null 2>&1 || true
        done
  done

  # Clean up any GHCR login we established
  [[ -n "$ghcr_user" ]] && ghcr_logout && trap - EXIT

  log "Deploy OK: $tag"
}

# -----------------------------------------------------------------------------
# rollback <TAG>
# -----------------------------------------------------------------------------
action_rollback() {
  local tag="$1"
  local ghcr_user="${2:-}"
  validate_tag "$tag"
  cd "$APP_DIR"

  # Optional stdin-token login in case the target tag isn't cached locally
  if [[ -n "$ghcr_user" ]]; then
    ghcr_login_from_stdin "$ghcr_user"
    trap 'ghcr_logout' EXIT
  fi

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
  $COMPOSE up -d --no-deps celery-worker celery-beat frontend
  # See comment in action_deploy — nginx must be recreated to drop stale DNS
  $COMPOSE up -d --no-deps --force-recreate nginx

  printf '{"release":"%s","previous":"%s","deployed_at":"%s","kind":"rollback"}\n' \
    "$tag" "$prev" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$APP_DIR/.last-deploy.json"

  [[ -n "$ghcr_user" ]] && ghcr_logout && trap - EXIT

  log "Rollback OK: $tag"
}

# -----------------------------------------------------------------------------
# install-script <NAME> — read a script body from stdin, install atomically at
# /opt/sales-platform/scripts/<NAME>.sh (mode 0755, owner $USER).
#
# Hard whitelist of allowed names, so a compromised deploy key can't drop
# arbitrary binaries in the scripts dir. The workflow pipes vm-ops.sh on
# stdin and then issues `ops <action>`; this keeps the VM script in lockstep
# with main without needing a separate secret / rsync / git checkout.
# -----------------------------------------------------------------------------
_INSTALL_SCRIPT_ALLOWLIST=("vm-ops")

action_install_script() {
  local name="$1"
  [[ -n "$name" ]] || die "install-script: missing <NAME>"
  [[ "$name" =~ ^[a-z][a-z0-9-]{0,30}$ ]] || die "install-script: invalid name '$name'"

  local allowed=0
  local a
  for a in "${_INSTALL_SCRIPT_ALLOWLIST[@]}"; do
    [[ "$a" == "$name" ]] && allowed=1 && break
  done
  (( allowed )) || die "install-script: '$name' not in allowlist (${_INSTALL_SCRIPT_ALLOWLIST[*]})"

  local target="$APP_DIR/scripts/$name.sh"
  mkdir -p "$APP_DIR/scripts"

  # Read the entire stdin into a tempfile in the same dir, then atomically
  # rename. No arbitrary-length cap here beyond what ssh/stdin will deliver,
  # but if it's huge something is wrong -- 256 KB is plenty for a bash script.
  local tmp
  tmp="$(mktemp "$APP_DIR/scripts/.${name}.XXXXXX")"
  # shellcheck disable=SC2064
  trap "rm -f '$tmp'" RETURN

  if ! head -c 262144 > "$tmp"; then
    die "install-script: failed to read stdin"
  fi
  [[ -s "$tmp" ]] || die "install-script: empty stdin"

  # Sanity: must start with a shebang so we never install a binary / junk
  local first_line
  IFS= read -r first_line < "$tmp" || true
  [[ "$first_line" =~ ^#!/ ]] || die "install-script: body must begin with a shebang"

  chmod 0755 "$tmp"
  mv "$tmp" "$target"
  trap - RETURN

  local bytes
  bytes="$(wc -c < "$target" | tr -d ' ')"
  log "install-script: wrote $target (${bytes} bytes)"
  echo "OK $target"
}

# -----------------------------------------------------------------------------
# ops <ACTION> — hand off to vm-ops.sh for sysadmin-y one-shots (audit,
# install-monitoring, docker-log-cap, etc). vm-ops.sh enforces its own
# whitelist of actions; we just make sure it's present and executable.
# -----------------------------------------------------------------------------
action_ops() {
  local op_action="$1"
  [[ -n "$op_action" ]] || die "ops: missing <ACTION>"
  local script="$APP_DIR/scripts/vm-ops.sh"
  [[ -x "$script" ]] || die "ops: $script not installed — run 'install-script vm-ops' first"
  log "ops: dispatching action='$op_action'"
  exec "$script" "$op_action"
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
ARG2="${ARGS[2]:-}"

case "$ACTION" in
  deploy)         action_deploy "$ARG1" "$ARG2" ;;
  rollback)       action_rollback "$ARG1" "$ARG2" ;;
  status)         action_status ;;
  install-script) action_install_script "$ARG1" ;;
  ops)            action_ops "$ARG1" ;;
  *)
    echo "Usage: deploy <TAG> [GHCR_USER] | rollback <TAG> [GHCR_USER] | status" >&2
    echo "       install-script <NAME>  | ops <ACTION>" >&2
    echo "Got: '$CMD'" >&2
    exit 1
    ;;
esac

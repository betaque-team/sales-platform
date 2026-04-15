#!/usr/bin/env bash
# =============================================================================
# vm-ops.sh — VM-side ad-hoc ops dispatcher
#
# Installed at: /opt/sales-platform/scripts/vm-ops.sh (mode 0755, owner deploy)
# Kept in lockstep with main by the vm-ops.yml workflow: each run pipes this
# file on stdin via ci-deploy.sh `install-script vm-ops`, then invokes
# `ops <ACTION>`.
#
# Because the forced-command SSH model restricts what the deploy key can do,
# every action here must be achievable by the `deploy` user (docker group,
# no sudo). Anything needing root stays manual and lives in docs/VM_OPS.md.
#
# Supported actions (whitelist):
#   audit             Full read-only VM state dump (disk, containers, cron,
#                     monitoring snapshot, cloudflared, last deploy, logs).
#   health            Compact green/red summary — is anything on fire?
#   restart-backend   Force-recreate backend (picks up compose-override changes).
#   restart-all       Rolling restart of all app services (not postgres/redis).
#   docker-prune      Prune dangling images + stopped containers.
#   tail-deploy-log   Last 200 lines of /opt/sales-platform/logs/ci-deploy.log.
#   show-crontab      Show deploy user's crontab.
# =============================================================================
set -euo pipefail

APP_DIR="/opt/sales-platform"
LOG_DIR="$APP_DIR/logs"
LOG_FILE="$LOG_DIR/vm-ops.log"
HOST_METRICS_DIR="$APP_DIR/host-metrics"

# Compose invocation:
#   - Pass BOTH files explicitly. Passing `-f docker-compose.prod.yml` alone
#     SUPPRESSES automatic override loading (docker compose quirk), so the
#     bind-mount added in override.yml would silently drop out.
COMPOSE_FILES=(-f docker-compose.prod.yml)
if [[ -f "$APP_DIR/docker-compose.override.yml" ]]; then
  COMPOSE_FILES+=(-f docker-compose.override.yml)
fi
compose() { ( cd "$APP_DIR" && docker compose "${COMPOSE_FILES[@]}" "$@" ); }

mkdir -p "$LOG_DIR"
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

hr() { printf '%s\n' "────────────────────────────────────────────────────────────"; }
h1() { printf '\n== %s ==\n' "$1"; }

# -----------------------------------------------------------------------------
# health — one-screen summary. Exit 0 if everything green, 1 if anything red.
# -----------------------------------------------------------------------------
do_health() {
  local rc=0

  printf 'host=%s  uptime=%s  date=%s\n' \
    "$(hostname)" "$(uptime -p 2>/dev/null || echo '?')" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  hr

  # Containers: every compose service must be "running"
  local cstate
  cstate="$(compose ps --format '{{.Name}}\t{{.State}}' 2>/dev/null || true)"
  if [[ -z "$cstate" ]]; then
    echo "containers    : RED   (compose ps returned nothing)"
    rc=1
  else
    local bad
    bad="$(awk -F'\t' '$2 != "running" {print $1"="$2}' <<< "$cstate")"
    if [[ -n "$bad" ]]; then
      echo "containers    : RED   non-running: $bad"
      rc=1
    else
      echo "containers    : green ($(wc -l <<< "$cstate" | tr -d ' ') running)"
    fi
  fi

  # Host-metrics snapshot freshness (should refresh every ~2 min)
  local snap="$HOST_METRICS_DIR/metrics.json"
  if [[ -f "$snap" ]]; then
    local age
    age=$(( $(date +%s) - $(stat -c %Y "$snap" 2>/dev/null || echo 0) ))
    if (( age < 300 )); then
      echo "host-metrics  : green (snapshot ${age}s old)"
    elif (( age < 900 )); then
      echo "host-metrics  : warn  (snapshot ${age}s old — collector may be lagging)"
    else
      echo "host-metrics  : RED   (snapshot ${age}s old — collector cron likely broken)"
      rc=1
    fi
  else
    echo "host-metrics  : RED   (snapshot missing at $snap)"
    rc=1
  fi

  # Keepalive: when did cron last log a burst?
  if command -v journalctl >/dev/null 2>&1; then
    local ka_line
    ka_line="$(journalctl --since '36 hours ago' -t keepalive 2>/dev/null | grep -F 'keepalive: burst completed' | tail -1 || true)"
    if [[ -n "$ka_line" ]]; then
      echo "keepalive     : green (last burst logged — see 'tail-keepalive' for detail)"
    else
      echo "keepalive     : warn  (no burst logged in last 36h; journal may be restricted to deploy user)"
    fi
  fi

  # Cloudflared tunnel (systemd unit name is cloudflared-tunnel.service on this VM)
  local tunnel_unit=""
  if systemctl list-unit-files cloudflared-tunnel.service 2>/dev/null | grep -q cloudflared-tunnel; then
    tunnel_unit=cloudflared-tunnel
  elif systemctl list-unit-files cloudflared.service 2>/dev/null | grep -q cloudflared; then
    tunnel_unit=cloudflared
  fi
  if [[ -n "$tunnel_unit" ]]; then
    local state
    state="$(systemctl is-active "$tunnel_unit" 2>/dev/null || echo unknown)"
    if [[ "$state" == "active" ]]; then
      echo "cloudflared   : green ($tunnel_unit active)"
    else
      echo "cloudflared   : RED   ($tunnel_unit state=$state)"
      rc=1
    fi
  else
    echo "cloudflared   : warn  (no systemd unit found — tunnel may be managed differently)"
  fi

  # Disk: root + any dedicated mounts
  df -h / "$APP_DIR" 2>/dev/null \
    | awk 'NR==1{printf "disk header   : %-20s %6s %6s %6s  %s\n",$1,$2,$3,$5,$6} NR>1{printf "disk          : %-20s %6s %6s %6s  %s\n",$1,$2,$3,$5,$6}'

  # Current release
  if [[ -f "$APP_DIR/.env" ]]; then
    local tag
    tag="$(grep -E '^RELEASE_TAG=' "$APP_DIR/.env" | cut -d= -f2 | head -1)"
    echo "release       : ${tag:-unset}"
  fi

  return $rc
}

# -----------------------------------------------------------------------------
# audit — full state dump. Intended to be read, not parsed.
# -----------------------------------------------------------------------------
do_audit() {
  h1 "host"
  printf 'hostname : %s\n' "$(hostname)"
  printf 'kernel   : %s\n' "$(uname -r)"
  printf 'uptime   : %s\n' "$(uptime -p 2>/dev/null || echo '?')"
  printf 'loadavg  : %s\n' "$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo '?')"
  printf 'date_utc : %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    printf 'os       : %s %s\n' "${NAME:-?}" "${VERSION:-?}"
  fi

  h1 "docker"
  docker version --format '{{.Server.Version}} (client {{.Client.Version}})' 2>/dev/null || echo '(cannot reach docker)'
  printf 'compose  : '
  docker compose version --short 2>/dev/null || echo '?'
  printf 'daemon log driver (cat /etc/docker/daemon.json if present):\n'
  if [[ -r /etc/docker/daemon.json ]]; then
    cat /etc/docker/daemon.json
  else
    echo '(no /etc/docker/daemon.json — using defaults, json-file WITHOUT size cap)'
  fi

  h1 "disk — df -h"
  df -h 2>/dev/null | grep -vE 'tmpfs|devtmpfs|overlay' || df -h

  h1 "disk — top-level dirs under $APP_DIR"
  ( cd "$APP_DIR" 2>/dev/null && du -sh -- */ 2>/dev/null | sort -hr | head -20 ) || echo '(cannot read $APP_DIR)'

  h1 "containers — compose ps"
  compose ps 2>&1 || true

  h1 "containers — docker stats (single sample)"
  # --no-stream = one pass, not live. Works without sudo since deploy is in docker group.
  docker stats --no-stream \
    --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}' \
    2>/dev/null || echo '(docker stats failed)'

  h1 "monitoring — host-metrics snapshot"
  local snap="$HOST_METRICS_DIR/metrics.json"
  if [[ -f "$snap" ]]; then
    local age
    age=$(( $(date +%s) - $(stat -c %Y "$snap" 2>/dev/null || echo 0) ))
    printf 'path=%s  age=%ds  size=%s\n' \
      "$snap" "$age" "$(stat -c %s "$snap" 2>/dev/null || echo '?')"
    if command -v jq >/dev/null 2>&1; then
      jq '{timestamp, host_uptime_seconds, cpu: .cpu.utilization_pct, mem: .memory.used_percent, disk_root: .disk.used_percent, oom_kills_1h, keepalive: .keepalive}' "$snap" 2>/dev/null || head -80 "$snap"
    else
      head -80 "$snap"
    fi
  else
    echo "(no snapshot at $snap — collector cron not running?)"
  fi

  h1 "keepalive — last 5 journal entries (if readable)"
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --since '7 days ago' -t keepalive --no-pager 2>/dev/null | tail -5 \
      || echo '(journalctl empty or not accessible to this user)'
  fi

  h1 "cloudflared — systemd state"
  for u in cloudflared-tunnel cloudflared; do
    if systemctl list-unit-files "${u}.service" 2>/dev/null | grep -q "$u"; then
      systemctl status --no-pager --lines=3 "$u" 2>/dev/null | head -8 || true
      break
    fi
  done

  h1 "crontab — deploy user"
  crontab -l 2>/dev/null || echo '(no crontab for this user)'

  h1 "last deploy"
  if [[ -f "$APP_DIR/.last-deploy.json" ]]; then
    cat "$APP_DIR/.last-deploy.json"
  else
    echo '(no .last-deploy.json)'
  fi
  if [[ -f "$APP_DIR/.env" ]]; then
    grep -E '^RELEASE_TAG=' "$APP_DIR/.env" || echo '(no RELEASE_TAG in .env)'
  fi

  h1 "backups"
  if [[ -d "$APP_DIR/backups" ]]; then
    du -sh "$APP_DIR/backups" 2>/dev/null || true
    ls -lht "$APP_DIR/backups" 2>/dev/null | head -6 || true
  else
    echo '(no backups dir)'
  fi

  h1 "recent deploy log tail (last 30 lines)"
  tail -30 "$LOG_DIR/ci-deploy.log" 2>/dev/null || echo '(no ci-deploy.log)'

  h1 "container log sizes (raw json-file, growth risk if no log-driver cap)"
  for cid in $(docker ps -q 2>/dev/null); do
    local name path size
    name="$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's|^/||')"
    path="$(docker inspect --format '{{.LogPath}}' "$cid" 2>/dev/null)"
    if [[ -n "$path" && -r "$path" ]]; then
      size="$(stat -c %s "$path" 2>/dev/null || echo 0)"
      printf '%-30s %10s bytes  %s\n' "$name" "$size" "$path"
    fi
  done | sort -k2 -nr
}

# -----------------------------------------------------------------------------
# restart-backend — pick up env/compose changes without touching postgres/redis
# -----------------------------------------------------------------------------
do_restart_backend() {
  log "restart-backend: force-recreating backend"
  compose up -d --force-recreate --no-deps backend
  log "restart-backend: waiting up to 60s for healthy"
  local waited=0
  while (( waited < 60 )); do
    local status
    status="$(compose ps backend --format '{{.Status}}' 2>/dev/null || true)"
    if echo "$status" | grep -q healthy; then
      log "restart-backend: healthy ($status)"
      return 0
    fi
    sleep 2
    waited=$((waited+2))
  done
  log "restart-backend: did not report healthy in 60s (status=$status)"
  return 1
}

# -----------------------------------------------------------------------------
# restart-all — rolling restart of app services, NOT postgres/redis (data)
# -----------------------------------------------------------------------------
do_restart_all() {
  log "restart-all: force-recreating app services"
  compose up -d --force-recreate --no-deps backend
  compose up -d --force-recreate --no-deps celery-worker celery-beat frontend
  compose up -d --force-recreate --no-deps nginx || true
  log "restart-all: done"
  compose ps
}

# -----------------------------------------------------------------------------
# docker-prune — safe prune (no -a; never removes tagged images still in use)
# -----------------------------------------------------------------------------
do_docker_prune() {
  log "docker-prune: dangling images + stopped containers"
  docker container prune -f 2>&1 | tail -5
  docker image prune -f 2>&1 | tail -5
  # Volumes intentionally NOT pruned — postgres-data lives there.
  log "docker-prune: done"
  docker system df
}

# -----------------------------------------------------------------------------
# tail-deploy-log
# -----------------------------------------------------------------------------
do_tail_deploy_log() {
  local f="$LOG_DIR/ci-deploy.log"
  if [[ -f "$f" ]]; then
    tail -200 "$f"
  else
    echo "(no log at $f)"
  fi
}

# -----------------------------------------------------------------------------
# show-crontab — deploy user's crontab only (root's requires sudo)
# -----------------------------------------------------------------------------
do_show_crontab() {
  echo "== crontab -l (user: $(id -un)) =="
  crontab -l 2>&1 || true
}

# -----------------------------------------------------------------------------
# dispatch
# -----------------------------------------------------------------------------
ACTION="${1:-}"
case "$ACTION" in
  audit)            do_audit ;;
  health)           do_health ;;
  restart-backend)  do_restart_backend ;;
  restart-all)      do_restart_all ;;
  docker-prune)     do_docker_prune ;;
  tail-deploy-log)  do_tail_deploy_log ;;
  show-crontab)     do_show_crontab ;;
  ""|--help|-h|help)
    echo "usage: vm-ops.sh <action>" >&2
    echo "actions: audit | health | restart-backend | restart-all | docker-prune | tail-deploy-log | show-crontab" >&2
    exit 1
    ;;
  *)
    echo "vm-ops.sh: unknown action '$ACTION'" >&2
    echo "actions: audit | health | restart-backend | restart-all | docker-prune | tail-deploy-log | show-crontab" >&2
    exit 1
    ;;
esac

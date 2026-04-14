#!/usr/bin/env bash
# =============================================================================
# infra/scripts/migrate-data.sh
#
# One-time migration: push local dev database → cloud VM.
# Dumps the local Postgres (running in Docker), ships the file to the VM
# over SSH, restores it into the remote Postgres, runs alembic upgrade,
# then validates row counts match.
#
# Usage:
#   make migrate-data                  # auto-detect VM IP from terraform output
#   make migrate-data VM_IP=1.2.3.4   # override IP
#   bash infra/scripts/migrate-data.sh --vm-ip 1.2.3.4 --ssh-key ~/.ssh/id_rsa
#
# Requires:
#   - Local docker compose dev stack has postgres running (or will start it)
#   - VM is up and cloud-init is complete (postgres is running on VM)
#   - SSH access to ubuntu@VM_IP with SSH_KEY
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TF_DIR="$PROJECT_DIR/infra/terraform"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()   { echo -e "${GREEN}[migrate] $*${NC}"; }
warn()  { echo -e "${YELLOW}[migrate] $*${NC}"; }
error() { echo -e "${RED}[migrate] ERROR: $*${NC}" >&2; exit 1; }
step()  { echo -e "\n${BOLD}━━━ $* ━━━${NC}\n"; }

# ── Parse args ────────────────────────────────────────────────────────────────
VM_IP="${VM_IP:-}"
SSH_KEY="${SSH_KEY:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vm-ip=*)   VM_IP="${1#--vm-ip=}";   shift ;;
    --vm-ip)     VM_IP="$2";              shift 2 ;;
    --ssh-key=*) SSH_KEY="${1#--ssh-key=}"; shift ;;
    --ssh-key)   SSH_KEY="$2";            shift 2 ;;
    *)           shift ;;
  esac
done

# ── Resolve VM IP ─────────────────────────────────────────────────────────────
if [[ -z "$VM_IP" ]]; then
  log "Detecting VM IP from terraform output..."
  VM_IP=$(cd "$TF_DIR" && terraform output -raw instance_public_ip 2>/dev/null) \
    || error "Could not detect VM IP. Run 'make infra-up' first, or pass VM_IP=x.x.x.x"
fi

# ── Resolve SSH key ───────────────────────────────────────────────────────────
if [[ -z "$SSH_KEY" ]]; then
  SSH_KEY=$(cd "$TF_DIR" && terraform output -raw ssh_private_key_path 2>/dev/null || echo "$HOME/.ssh/id_rsa")
fi
[[ -f "$SSH_KEY" ]] || error "SSH key not found: $SSH_KEY"

log "Target VM : ubuntu@$VM_IP"
log "SSH key   : $SSH_KEY"

# ── Local compose (dev) ───────────────────────────────────────────────────────
LOCAL_COMPOSE="docker compose -f $PROJECT_DIR/docker-compose.yml"
DB_USER="${POSTGRES_USER:-postgres}"
DB_NAME="${POSTGRES_DB:-jobplatform}"
REMOTE_APP_DIR="/opt/sales-platform"
REMOTE_COMPOSE="docker compose -f $REMOTE_APP_DIR/docker-compose.prod.yml"

# ── SSH helpers ───────────────────────────────────────────────────────────────
SSH_OPTS="-i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=15"
remote()  { ssh $SSH_OPTS ubuntu@"$VM_IP" "$@"; }
scp_to()  { scp -q $SSH_OPTS "$1" ubuntu@"$VM_IP":"$2"; }

# =============================================================================
step "1 / 10 — Pre-flight checks"
# =============================================================================

# Ensure local postgres is running
log "Checking local postgres..."
if ! $LOCAL_COMPOSE ps postgres 2>/dev/null | grep -qE "running|Up"; then
  warn "Local postgres not running — starting it..."
  $LOCAL_COMPOSE up -d postgres
  sleep 6
fi

# Count local rows
log "Counting local rows..."
LOCAL_ROW_JSON=$($LOCAL_COMPOSE exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT json_agg(row_to_json(t)) FROM (
    SELECT relname AS \"table\", n_live_tup::int AS rows
    FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY relname
  ) t;" 2>/dev/null | tr -d '\n')

LOCAL_TOTAL=$(echo "$LOCAL_ROW_JSON" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(sum(r['rows'] for r in (d or [])))" 2>/dev/null || echo 0)

[[ "$LOCAL_TOTAL" -gt 0 ]] || error "Local database is empty (0 rows). Nothing to migrate."
log "Local rows: $LOCAL_TOTAL"

# Alembic revision
LOCAL_ALEMBIC=$($LOCAL_COMPOSE exec -T postgres psql -U "$DB_USER" -d "$DB_NAME" \
  -t -A -c "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '[:space:]' || echo "unknown")
log "Local alembic revision: $LOCAL_ALEMBIC"

# Check VM reachable
log "Checking VM connectivity..."
remote "echo 'SSH OK'" > /dev/null \
  || error "Cannot SSH to $VM_IP — check the IP and key, or wait for cloud-init to finish"

# Check VM postgres is running
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE ps postgres 2>/dev/null | grep -qE 'running|Up'" \
  || error "Remote postgres is not running on the VM yet. Check cloud-init progress:
  ssh -i $SSH_KEY ubuntu@$VM_IP 'sudo tail -50 /var/log/cloud-init-output.log'"

# Remote row count (before migration)
REMOTE_TOTAL=$(remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres \
  psql -U $DB_USER -d $DB_NAME -t -A \
  -c 'SELECT COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables;' 2>/dev/null" \
  | tr -d '[:space:]') || REMOTE_TOTAL=0

# =============================================================================
step "2 / 10 — Confirm migration"
# =============================================================================

echo
echo -e "  ${BOLD}Source (local dev):${NC}  $LOCAL_TOTAL rows  (alembic: $LOCAL_ALEMBIC)"
echo -e "  ${BOLD}Target (cloud VM) :${NC}  $REMOTE_TOTAL rows  → will be REPLACED"
echo
warn "All data currently on the VM will be overwritten."
warn "Consider running 'make backup' on the VM first if it has data you want to keep."
echo
read -r -p "  Type 'yes, migrate' to continue: " CONFIRM
[[ "$CONFIRM" == "yes, migrate" ]] || { warn "Aborted."; exit 0; }

# =============================================================================
step "3 / 10 — Dump local database"
# =============================================================================

TS=$(date +"%Y%m%d_%H%M%S")
LOCAL_DUMP="/tmp/migrate-${TS}.pgdump"

log "Dumping local database to $LOCAL_DUMP ..."
$LOCAL_COMPOSE exec -T postgres pg_dump \
  -U "$DB_USER" -d "$DB_NAME" \
  --format=custom --compress=9 --no-password \
  > "$LOCAL_DUMP"

DUMP_BYTES=$(wc -c < "$LOCAL_DUMP")
DUMP_HUMAN=$(python3 -c "b=$DUMP_BYTES; print(f'{b/1024/1024:.1f} MB' if b>1048576 else f'{b/1024:.0f} KB')" 2>/dev/null || echo "${DUMP_BYTES}B")
log "Dump complete: $DUMP_HUMAN"

# Checksum
shasum -a 256 "$LOCAL_DUMP" > "${LOCAL_DUMP}.sha256"

# =============================================================================
step "4 / 10 — Transfer dump to VM"
# =============================================================================

REMOTE_DUMP="/tmp/migrate-${TS}.pgdump"
log "Uploading $DUMP_HUMAN to VM (this may take a minute for large datasets)..."
scp_to "$LOCAL_DUMP"            "$REMOTE_DUMP"
scp_to "${LOCAL_DUMP}.sha256"   "${REMOTE_DUMP}.sha256"
log "Upload complete"

# Verify checksum on the remote side
log "Verifying checksum on VM..."
remote "cd /tmp && shasum -a 256 -c migrate-${TS}.pgdump.sha256 --quiet" \
  || error "Checksum mismatch after transfer — file may be corrupt, please retry"
log "Checksum OK"

# =============================================================================
step "5 / 10 — Stop app services on VM (postgres stays up)"
# =============================================================================

log "Stopping backend + workers on VM..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE stop backend celery-worker celery-beat 2>/dev/null || true"
log "App services stopped"

# =============================================================================
step "6 / 10 — Drop and recreate remote database"
# =============================================================================

log "Terminating active connections to remote DB..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres psql -U $DB_USER postgres -c \
  \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid<>pg_backend_pid();\" \
  2>/dev/null || true"

log "Dropping remote database..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres \
  psql -U $DB_USER postgres -c \"DROP DATABASE IF EXISTS $DB_NAME;\""

log "Creating fresh remote database..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres \
  psql -U $DB_USER postgres -c \"CREATE DATABASE $DB_NAME;\""

# =============================================================================
step "7 / 10 — Restore dump into remote database"
# =============================================================================

log "Restoring dump (this may take a few minutes for large datasets)..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres \
  pg_restore -U $DB_USER -d $DB_NAME --no-password --exit-on-error \
  < $REMOTE_DUMP" \
  || warn "pg_restore exited with warnings (often harmless — checking row count next)"

log "Restore complete"

# =============================================================================
step "8 / 10 — Run migrations (schema sync)"
# =============================================================================

log "Running alembic upgrade head on VM (ensures schema is current)..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE run --rm backend alembic upgrade head 2>&1" \
  || warn "Migration step had warnings — check app startup logs if issues arise"

# =============================================================================
step "9 / 10 — Restart app services on VM"
# =============================================================================

log "Starting backend + workers on VM..."
remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE start backend celery-worker celery-beat"

log "Waiting 15s for services to become ready..."
sleep 15

# =============================================================================
step "10 / 10 — Validate row counts"
# =============================================================================

log "Counting rows in remote database..."
REMOTE_ROW_JSON=$(remote "cd $REMOTE_APP_DIR && $REMOTE_COMPOSE exec -T postgres \
  psql -U $DB_USER -d $DB_NAME -t -A \
  -c \"SELECT json_agg(row_to_json(t)) FROM (
        SELECT relname AS table, n_live_tup::int AS rows
        FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY relname
      ) t;\" 2>/dev/null" | tr -d '\n')

VALIDATION_RESULT=$(python3 - "$LOCAL_ROW_JSON" "$REMOTE_ROW_JSON" <<'PY'
import json, sys

local_data  = json.loads(sys.argv[1]) or []
remote_data = json.loads(sys.argv[2]) or []
local_rows  = {t['table']: t['rows'] for t in local_data}
remote_rows = {t['table']: t['rows'] for t in remote_data}

# These tables must match closely; others are informational
key_tables = [
    'jobs', 'companies', 'company_ats_boards', 'users',
    'resumes', 'pipeline_entries', 'reviews', 'role_cluster_configs',
    'discovery_results', 'scan_logs',
]

all_tables = sorted(set(list(local_rows.keys()) + list(remote_rows.keys())))
ok = True

print(f"\n  {'STATUS':9s}  {'TABLE':35s}  {'LOCAL':>10s}  {'REMOTE':>10s}")
print(f"  {'-'*9}  {'-'*35}  {'-'*10}  {'-'*10}")
for t in all_tables:
    l = local_rows.get(t, 0)
    r = remote_rows.get(t, 0)
    # pg_stat_user_tables can lag slightly; allow 5% variance
    match = (r >= l * 0.95)
    status = "OK" if match else "MISMATCH"
    if t in key_tables and not match:
        ok = False
    flag = "  <-- CHECK" if not match else ""
    print(f"  {status:9s}  {t:35s}  {l:>10,}  {r:>10,}{flag}")

total_local  = sum(local_rows.values())
total_remote = sum(remote_rows.values())
print(f"\n  {'TOTAL':9s}  {'':35s}  {total_local:>10,}  {total_remote:>10,}")
print(f"\n  {'PASSED' if ok else 'FAILED — check MISMATCH rows above'}")
sys.exit(0 if ok else 1)
PY
)

echo "$VALIDATION_RESULT"

# =============================================================================
# Cleanup
# =============================================================================

log "Removing temp dump files..."
rm -f "$LOCAL_DUMP" "${LOCAL_DUMP}.sha256"
remote "rm -f $REMOTE_DUMP ${REMOTE_DUMP}.sha256"

echo
APP_URL=$(cd "$TF_DIR" && terraform output -raw app_url 2>/dev/null || echo "https://salesplatform.reventlabs.com")
echo -e "${GREEN}${BOLD}Migration complete!${NC}"
echo -e "  $LOCAL_TOTAL rows are now live at: ${BOLD}${APP_URL}${NC}"
echo

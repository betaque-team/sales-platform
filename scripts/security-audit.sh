#!/usr/bin/env bash
# =============================================================================
# security-audit.sh — verify prod VM deploy posture matches expected invariants
#
# Run from Mac:  bash scripts/security-audit.sh
# Run on VM:     sudo bash /opt/sales-platform/scripts/security-audit.sh --local
#
# Exits non-zero if any check FAILs. PASS/WARN/FAIL are printed per check.
# Extend this as the threat model evolves — cheaper to codify checks than to
# rediscover them during an incident.
# =============================================================================
set -uo pipefail

# Host is read from the environment — do NOT hardcode prod IPs in the repo.
# Usage:  PROD_HOST=1.2.3.4 bash scripts/security-audit.sh
#         PROD_HOST=1.2.3.4 PROD_ADMIN_USER=ubuntu bash scripts/security-audit.sh
# Or --local on the VM itself (no SSH, no host needed).
USER_ADMIN="${PROD_ADMIN_USER:-ubuntu}"
LOCAL=0
[[ "${1:-}" == "--local" ]] && LOCAL=1

if (( LOCAL == 0 )) && [[ -z "${PROD_HOST:-}" ]]; then
  echo "ERROR: set PROD_HOST=<vm-ip> (or run with --local on the VM)" >&2
  exit 2
fi
HOST="${PROD_HOST:-localhost}"

pass=0; warn=0; fail=0
say() {
  local kind="$1"; local msg="$2"
  case "$kind" in
    PASS) echo "  [PASS] $msg"; pass=$((pass+1)) ;;
    WARN) echo "  [WARN] $msg"; warn=$((warn+1)) ;;
    FAIL) echo "  [FAIL] $msg"; fail=$((fail+1)) ;;
  esac
}

run() {
  if (( LOCAL )); then bash -c "$1"
  else ssh -o ConnectTimeout=10 -o BatchMode=yes "${USER_ADMIN}@${HOST}" "$1"
  fi
}

section() { echo; echo "── $1 ──"; }

# -----------------------------------------------------------------------------
section "1. deploy user hardening"

if run 'groups deploy' 2>/dev/null | grep -q '\bsudo\b'; then
  say FAIL "deploy user is in sudo group"
else
  say PASS "deploy user has no sudo"
fi

if run 'groups deploy' 2>/dev/null | grep -q '\bdocker\b'; then
  say PASS "deploy user is in docker group"
else
  say FAIL "deploy user is NOT in docker group"
fi

if run 'sudo grep -h "deploy" /etc/sudoers /etc/sudoers.d/* 2>/dev/null | grep -v "^#"' | grep -q deploy; then
  say FAIL "deploy has a sudoers entry"
else
  say PASS "no sudoers entry for deploy"
fi

# -----------------------------------------------------------------------------
section "2. authorized_keys enforcement"

ak=$(run 'sudo cat /home/deploy/.ssh/authorized_keys 2>/dev/null')
if echo "$ak" | grep -q '^restrict,command="/opt/sales-platform/scripts/ci-deploy.sh"'; then
  say PASS "authorized_keys has restrict + forced-command"
else
  say FAIL "authorized_keys missing restrict or forced-command"
fi

if run 'sudo stat -c "%a %U:%G" /home/deploy/.ssh/authorized_keys' 2>/dev/null | grep -q '^600 deploy:deploy'; then
  say PASS "authorized_keys is 600 deploy:deploy"
else
  say FAIL "authorized_keys wrong perms/owner"
fi

# -----------------------------------------------------------------------------
section "3. secret file perms"

check_perm() {
  local expected="$1"; local path="$2"
  local got
  got=$(run "sudo stat -c '%a %U:%G' $path 2>/dev/null" | tr -d '\r')
  if [[ "$got" == "$expected" ]]; then
    say PASS "$path is $expected"
  else
    say FAIL "$path is '$got', expected '$expected'"
  fi
}

check_perm "640 deploy:deploy" /opt/sales-platform/.env
check_perm "600 deploy:deploy" /opt/sales-platform/cloudflared/credentials.json
check_perm "755 deploy:deploy" /opt/sales-platform/scripts/ci-deploy.sh

# -----------------------------------------------------------------------------
section "4. network surface"

if run 'sudo ufw status | head -2' 2>/dev/null | grep -q 'Status: active'; then
  say PASS "ufw is active"
else
  say FAIL "ufw is inactive"
fi

exposed=$(run "sudo ss -tlnp 2>/dev/null | awk 'NR>1 && \$4 !~ /127\\.0\\.0\\.1|::1|127\\.0\\.0\\.53/ {print \$4}'")
if [[ "$(echo "$exposed" | wc -l | tr -d ' ')" == "2" ]] && echo "$exposed" | grep -qE ':22$'; then
  say PASS "only port 22 exposed publicly"
else
  say FAIL "unexpected public listeners:"
  echo "$exposed" | sed 's/^/         /'
fi

# -----------------------------------------------------------------------------
section "5. auth daemons"

if run 'systemctl is-active fail2ban' 2>/dev/null | grep -q '^active$'; then
  say PASS "fail2ban active"
else
  say WARN "fail2ban not active"
fi

sshd=$(run 'sudo sshd -T 2>/dev/null')
if echo "$sshd" | grep -q '^passwordauthentication no'; then
  say PASS "password auth disabled"
else
  say FAIL "password auth enabled"
fi

if echo "$sshd" | grep -q '^permitrootlogin no'; then
  say PASS "root login disabled"
elif echo "$sshd" | grep -q '^permitrootlogin without-password'; then
  say WARN "root login allowed via key (prefer 'no')"
else
  say FAIL "root login permitted with password"
fi

# -----------------------------------------------------------------------------
section "6. no credential leaks"

if run 'sudo test -s /home/deploy/.docker/config.json' 2>/dev/null; then
  size=$(run 'sudo stat -c %s /home/deploy/.docker/config.json' | tr -d '\r')
  if [[ "$size" -le 20 ]]; then
    say PASS "/home/deploy/.docker/config.json empty ($size bytes)"
  else
    say WARN "/home/deploy/.docker/config.json non-empty ($size bytes) — check ghcr_logout ran"
  fi
else
  say PASS "/home/deploy/.docker/config.json absent"
fi

# -----------------------------------------------------------------------------
section "7. deploy script integrity"

if run 'test -x /opt/sales-platform/scripts/ci-deploy.sh' 2>/dev/null; then
  say PASS "ci-deploy.sh executable"
else
  say FAIL "ci-deploy.sh missing or not executable"
fi

# -----------------------------------------------------------------------------
section "8. backup hygiene"

backup_count=$(run 'ls /opt/sales-platform/backups/pre-deploy-*.sql.gz 2>/dev/null | wc -l' | tr -d ' \r')
if [[ "$backup_count" -le 15 ]]; then
  say PASS "backup count = $backup_count (rotation keeping ≤14 + current)"
else
  say WARN "backup count = $backup_count (rotation cron may not be running)"
fi

# -----------------------------------------------------------------------------
echo
echo "================================================================"
echo "Result: ${pass} pass · ${warn} warn · ${fail} fail"
echo "================================================================"
exit $(( fail > 0 ? 1 : 0 ))

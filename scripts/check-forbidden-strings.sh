#!/usr/bin/env bash
# =============================================================================
# check-forbidden-strings.sh — block known-leaked values + public IPs
#
# Invoked by pre-commit as one of the `local` hooks. Receives staged file
# paths on argv. Fails (exit 1) if any forbidden pattern matches; prints
# the offending file + line + pattern so the dev can see exactly what's
# blocked.
#
# Patterns here should be CHEAP to maintain:
# - Add a specific string when we remediate a real leak, so it can't be
#   re-introduced (the primary use-case — an exact-match blocklist).
# - Add a regex for a new credential shape we've seen in the wild.
# =============================================================================
set -uo pipefail

# ── exact-match forbidden strings (known-leaked values) ──
# Keep these obfuscated in this file so the file itself doesn't trip its
# own regex when committed. We reconstruct each at runtime.
forbidden_literals=(
  # Prod VM IP (leaked 2026-04-15, now scrubbed; never commit again).
  # Stored as its two halves so this file itself doesn't contain the string.
  "$(printf '161.118.' )$(printf '207.119')"
  # Host-key pin fragment (also leaked in DEPLOY_SETUP.md, now scrubbed).
  "$(printf 'SaFx4T6ADd' )$(printf 'CsBlr8zifA')"
)

# ── regex patterns for credential shapes ──
forbidden_regexes=(
  # GitHub tokens
  'ghp_[A-Za-z0-9]{30,}'
  'github_pat_[A-Za-z0-9_]{20,}'
  'gho_[A-Za-z0-9]{30,}'
  'ghs_[A-Za-z0-9]{30,}'
  # AWS access keys
  'AKIA[0-9A-Z]{16}'
  'aws_secret_access_key\s*=\s*["'"'"']?[A-Za-z0-9/+=]{40}'
  # Anthropic — production keys are `sk-ant-api03-<long-body>` + admin
  # keys use `sk-ant-admin01-`. The generic `sk-ant-` prefix alone also
  # stays blocked (catches future prefixes we haven't seen yet).
  'sk-ant-[A-Za-z0-9_-]{20,}'
  # Explicit ANTHROPIC_API_KEY=<value> pattern — catches the case
  # where someone pastes a shell export or .env line into a file /
  # commit message. Allowlist: empty values (placeholder), ${VAR}
  # indirection, and `CHANGE_ME` / `REPLACE_ME` templates.
  'ANTHROPIC_API_KEY\s*[:=]\s*["'"'"']?(?!\s*$|CHANGE_ME|REPLACE_ME|\$\{|\{\{|"")[A-Za-z0-9_-]{10,}'
  # OpenAI
  'sk-proj-[A-Za-z0-9_-]{20,}'
  'sk-[A-Za-z0-9]{48,}'
  # Google API keys
  'AIza[0-9A-Za-z_-]{35}'
  # Slack
  'xox[baprs]-[0-9]{10,}-[0-9]{10,}'
  # Generic private keys (also caught by detect-private-key; belt + braces)
  '-----BEGIN (RSA |EC |OPENSSH |PGP |DSA |ENCRYPTED )?PRIVATE KEY-----'

  # ── Cloudflare ──
  # Tunnel credentials JSON structure (TunnelSecret is the smoking gun)
  '"TunnelSecret"\s*:\s*"[A-Za-z0-9+/=]{20,}"'
  '"AccountTag"\s*:\s*"[a-f0-9]{32}"'
  # Cloudflare API tokens — fine-grained are ~40-char base62-ish
  'CF_API_TOKEN\s*=\s*["'"'"']?[A-Za-z0-9_-]{30,}'
  'cloudflare_api_token\s*=\s*["'"'"']?[A-Za-z0-9_-]{30,}'
  # Cloudflare origin-cert private keys
  '-----BEGIN ORIGIN CERTIFICATE-----'

  # ── Oracle Cloud Infrastructure ──
  # OCIDs with trailing non-empty identifier body (placeholders like ocid1.XXX are fine)
  'ocid1\.tenancy\.oc1\.\.[a-z0-9]{40,}'
  'ocid1\.user\.oc1\.\.[a-z0-9]{40,}'
  'ocid1\.compartment\.oc1\.\.[a-z0-9]{40,}'
  # OCI API key fingerprint: colon-separated hex bytes
  'fingerprint\s*=\s*["'"'"']?([a-f0-9]{2}:){15}[a-f0-9]{2}'

  # ── PostgreSQL connection strings with an actual password ──
  # Matches postgresql://user:<NOT_a_placeholder>@host — catches real DSNs but
  # allows CHANGE_ME / ${var} / {{var}} templates.
  'postgres(ql)?(\+asyncpg)?://[^:]+:(?!CHANGE|REPLACE|\$\{|\{\{|example|changeme)[^@[:space:]"]{6,}@'
)

# ── non-private IPv4 addresses ──
# An IP in the repo is almost certainly a production host we don't want
# committed. RFC1918 (10/8, 172.16/12, 192.168/16), loopback (127/8), link-
# local (169.254/16), and documentation ranges (192.0.2/24, 198.51.100/24,
# 203.0.113/24) are allowed.
public_ipv4_regex='\b([0-9]{1,3}\.){3}[0-9]{1,3}\b'

is_private_ip() {
  local ip="$1" a b
  IFS=. read -r a b _ _ <<< "$ip"
  # RFC1918
  [[ "$a" == "10" ]] && return 0
  [[ "$a" == "172" && "$b" -ge 16 && "$b" -le 31 ]] && return 0
  [[ "$a" == "192" && "$b" == "168" ]] && return 0
  # loopback, link-local, documentation, multicast, reserved
  [[ "$a" == "127" ]] && return 0
  [[ "$a" == "169" && "$b" == "254" ]] && return 0
  [[ "$a" == "192" && "$b" == "0" ]] && return 0
  [[ "$a" == "198" && ("$b" == "51" || "$b" == "18" || "$b" == "19") ]] && return 0
  [[ "$a" == "203" && "$b" == "0" ]] && return 0
  # 0.0.0.0 is fine (bind-all)
  [[ "$ip" == "0.0.0.0" ]] && return 0
  # version strings / ports / dotted identifiers that happen to parse as IP
  # (we already match \b so it's already word-bounded; skip ones with a 4th
  # octet > 255)
  return 1
}

failed=0
files_checked=0

# Skip binary / lock files — they're noisy and shouldn't have secrets anyway.
should_skip() {
  local f="$1"
  case "$f" in
    *.png|*.jpg|*.jpeg|*.gif|*.pdf|*.ico|*.woff|*.woff2|*.ttf|*.eot) return 0 ;;
    *.lock|*.sum|package-lock.json|yarn.lock|Cargo.lock|poetry.lock) return 0 ;;
    */vendor/*|*/node_modules/*|*/.venv/*|*/dist/*|*/build/*) return 0 ;;
  esac
  return 1
}

report() {
  local file="$1" line="$2" pat="$3" match="$4"
  echo "  ✘ ${file}:${line}  [pattern: ${pat}]"
  echo "      ${match}"
  failed=1
}

for file in "$@"; do
  should_skip "$file" && continue
  [[ ! -f "$file" ]] && continue
  files_checked=$((files_checked + 1))

  # Literal blocklist
  for lit in "${forbidden_literals[@]}"; do
    if match=$(grep -nF -- "$lit" "$file" 2>/dev/null); then
      while IFS= read -r hit; do
        line="${hit%%:*}"
        rest="${hit#*:}"
        report "$file" "$line" "known-leaked literal" "${rest:0:120}"
      done <<< "$match"
    fi
  done

  # Regex credential shapes
  for re in "${forbidden_regexes[@]}"; do
    if match=$(grep -nE -- "$re" "$file" 2>/dev/null); then
      while IFS= read -r hit; do
        line="${hit%%:*}"
        rest="${hit#*:}"
        report "$file" "$line" "credential shape: ${re:0:40}" "${rest:0:120}"
      done <<< "$match"
    fi
  done

  # Public IPv4
  if matches=$(grep -nEo -- "$public_ipv4_regex" "$file" 2>/dev/null); then
    while IFS= read -r hit; do
      line="${hit%%:*}"
      ip="${hit#*:}"
      # Basic sanity: each octet 0-255
      if echo "$ip" | awk -F. '{exit !($1<=255 && $2<=255 && $3<=255 && $4<=255)}'; then
        if ! is_private_ip "$ip"; then
          report "$file" "$line" "public IPv4" "$ip"
        fi
      fi
    done <<< "$matches"
  fi
done

if (( failed )); then
  cat <<EOF

=========================================================================
Pre-commit blocked: forbidden strings found in staged files.
=========================================================================
If this is a false positive (e.g. a documented placeholder or a test
fixture), either:
  1. Refactor so the pattern doesn't appear literally, OR
  2. Add a targeted exclude in .pre-commit-config.yaml, OR
  3. Bypass JUST THIS ONCE with --no-verify (please leave a note in the
     commit message explaining why).

See docs/DEPLOYMENT_PROCESS.md → Security Model for secret-handling
policy. Genuine secrets should go in GH Environment (CI) or /opt/sales-
platform/.env (VM), NEVER in the repo.
EOF
  exit 1
fi

exit 0

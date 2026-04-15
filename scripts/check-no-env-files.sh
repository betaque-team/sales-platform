#!/usr/bin/env bash
# =============================================================================
# check-no-env-files.sh — block committing .env / creds files that slipped
# past gitignore (e.g. user ran `git add -f` or .gitignore wasn't current).
#
# Allowed:
#   .env.example, .env.template, .env.sample          (placeholders only)
#   *.pub                                              (public keys)
# Blocked:
#   .env, .env.<anything>
#   cloudflared/credentials.json
#   terraform.tfvars (but .tfvars.example is OK)
#   *.pem, *.key, id_rsa, id_ed25519
#   *.oci_api_key*
# =============================================================================
set -uo pipefail

failed=0

is_blocked() {
  local f="$1" basename="${1##*/}"
  case "$basename" in
    .env|.env.*)
      [[ "$basename" == .env.example ]] && return 1
      [[ "$basename" == .env.template ]] && return 1
      [[ "$basename" == .env.sample ]] && return 1
      return 0
      ;;
    credentials.json)
      # Block only when under a cloudflared/ path
      [[ "$f" == *cloudflared* ]] && return 0
      ;;
    *.pem|*.key|*.p12|*.pfx|*.ppk)
      [[ "$f" == *.pub ]] && return 1
      return 0
      ;;
    id_rsa|id_ed25519|id_ecdsa|id_dsa)
      return 0
      ;;
    *oci_api_key*)
      [[ "$f" == *.pub ]] && return 1
      return 0
      ;;
    *.tfvars)
      [[ "$f" == *.tfvars.example ]] && return 1
      return 0
      ;;
    *.tfstate|*.tfstate.backup)
      return 0
      ;;
  esac
  return 1
}

for file in "$@"; do
  if is_blocked "$file"; then
    echo "  ✘ $file — credential/secret file must not be committed"
    failed=1
  fi
done

if (( failed )); then
  cat <<EOF

=========================================================================
Pre-commit blocked: credential/secret file in staged changes.
=========================================================================
This file type holds live secrets and should never land in git. If you
genuinely need a template, rename to .env.example / *.tfvars.example /
*.pub (for public keys) so the blocklist knows it's a placeholder.

If this is a false positive, --no-verify bypasses — but please leave a
note in the commit message explaining why.
EOF
  exit 1
fi

exit 0

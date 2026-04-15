#!/usr/bin/env bash
# =============================================================================
# setup-branch-protection.sh — apply branch protection to `main`
#
# Usage:
#   ./platform/scripts/setup-branch-protection.sh                  # apply
#   ./platform/scripts/setup-branch-protection.sh --show           # preview only (no change)
#   ./platform/scripts/setup-branch-protection.sh --owner X --repo Y
#
# Requirements:
#   - `gh` authenticated as a repo admin (`gh auth login`)
#   - Run from anywhere (script discovers owner/repo via `gh repo view` if not passed)
#
# Rules applied (documented inline in the JSON payload below):
#   - Require 1 approving PR review before merge
#   - Dismiss stale approvals when new commits are pushed
#   - Require the listed status checks to pass
#   - Require branch to be up-to-date with main before merging
#   - No force-pushes, no deletions
#   - Require linear history (no merge commits — enforces squash/rebase)
#   - Enforce the rules for admins too (set to true; flip to false if you
#     want to keep break-glass admin override)
#
# Idempotent: safe to re-run to reset to the known-good state.
# =============================================================================
set -euo pipefail

show_only=0
owner=""
repo=""
branch="main"

while (($#)); do
  case "$1" in
    --show) show_only=1 ;;
    --owner) owner="$2"; shift ;;
    --repo) repo="$2"; shift ;;
    --branch) branch="$2"; shift ;;
    -h|--help)
      sed -n '2,22p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v gh >/dev/null 2>&1; then
  echo "error: gh (GitHub CLI) not installed — https://cli.github.com/" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "error: gh not authenticated — run 'gh auth login' first" >&2
  exit 1
fi

# Discover owner/repo from the current checkout if not passed.
if [[ -z "$owner" || -z "$repo" ]]; then
  info="$(gh repo view --json owner,name -q '.owner.login + "/" + .name' 2>/dev/null || true)"
  if [[ -z "$info" ]]; then
    echo "error: could not detect repo — pass --owner and --repo" >&2
    exit 1
  fi
  owner="${info%%/*}"
  repo="${info##*/}"
fi

cat <<EOF
Applying branch protection:
  repo   : $owner/$repo
  branch : $branch
  mode   : $([ "$show_only" = 1 ] && echo 'PREVIEW (no change)' || echo 'APPLY')
EOF

# -----------------------------------------------------------------------------
# Protection payload.
#
# CI job names → status-check contexts. These come from the `name:` field on
# each job in .github/workflows/ci.yml. Keep in sync if renaming:
#   - "Backend tests"   (job: backend in ci.yml)
#   - "Frontend build"  (job: frontend in ci.yml)
# -----------------------------------------------------------------------------
payload="$(cat <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "Backend tests",
      "Frontend build"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
)"

if [[ "$show_only" == 1 ]]; then
  echo "---"
  echo "$payload"
  echo "---"
  echo "(use without --show to apply)"
  exit 0
fi

# gh api requires the payload on stdin as --input -
echo "$payload" | gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  "/repos/$owner/$repo/branches/$branch/protection" \
  --input -

echo ""
echo "✓ Branch protection applied to $owner/$repo:$branch"
echo ""
echo "Verify in browser:"
echo "  https://github.com/$owner/$repo/settings/branches"

#!/usr/bin/env bash
# =============================================================================
# install-hooks.sh — one-time setup for pre-commit hooks on this clone.
#
# Run once after cloning:
#   bash scripts/install-hooks.sh
#
# After this, `git commit` will automatically run the checks in
# .pre-commit-config.yaml. To run them on the full tree manually:
#   pre-commit run --all-files
#
# To temporarily bypass for a single commit (use sparingly; leave a note in
# the commit message):
#   git commit --no-verify
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

# 1. Ensure pre-commit is installed
if ! command -v pre-commit >/dev/null 2>&1; then
  echo "pre-commit not found. Install with one of:"
  echo "  brew install pre-commit        (macOS)"
  echo "  pipx install pre-commit        (preferred, isolated)"
  echo "  pip install --user pre-commit  (fallback)"
  exit 1
fi

# 2. Make our local scripts executable (pre-commit entrypoints)
chmod +x scripts/check-forbidden-strings.sh scripts/check-no-env-files.sh scripts/security-audit.sh

# 3. Install the git hook
pre-commit install

# 4. Run once on the full tree so you see existing violations up-front
echo
echo "Running initial pass on all files (existing issues flagged below)…"
echo
pre-commit run --all-files || {
  echo
  echo "⚠  Some files are failing the checks. These will block future commits"
  echo "   that touch the same lines. Fix or allowlist as appropriate."
  echo
  exit 0   # don't fail the installer; the state is useful info
}

echo
echo "✓ Hooks installed and clean."

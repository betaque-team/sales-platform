#!/usr/bin/env bash
# =============================================================================
# setup-tunnel.sh — Set up Cloudflare Tunnel on the server
# Run this ON THE SERVER after bootstrap.sh
#
# Usage:
#   bash infra/scripts/setup-tunnel.sh
#   bash infra/scripts/setup-tunnel.sh --token <TOKEN>   # headless mode
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CF_DIR="$PROJECT_DIR/infra/cloudflare"
CREDS_DIR="$CF_DIR/creds"

DOMAIN="salesplatform.reventlabs.com"
TUNNEL_NAME="sales-platform"
TOKEN=""

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[tunnel] $*${NC}"; }
warn() { echo -e "${YELLOW}[tunnel] $*${NC}"; }
fail() { echo -e "${RED}[tunnel] ERROR: $*${NC}" >&2; exit 1; }

# Parse args
for arg in "$@"; do
  case "$arg" in
    --token)   shift; TOKEN="${1:-}"; shift || true ;;
    --token=*) TOKEN="${arg#--token=}" ;;
  esac
done

command -v cloudflared &>/dev/null || fail "cloudflared not installed. Run bootstrap.sh first."
mkdir -p "$CREDS_DIR"

echo -e "${BOLD}"
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║  Cloudflare Tunnel Setup                      ║"
echo "  ║  Domain: ${DOMAIN}            ║"
echo "  ║  Tunnel: ${TUNNEL_NAME}                    ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo -e "${NC}"

# ═══════════════════════════════════════════════════════════════════════════════
# Method 1: Token-based (headless — for CI/CD and remote servers)
# Create token in Cloudflare Zero Trust dashboard:
#   Zero Trust → Networks → Tunnels → Create → select Cloudflared → copy token
# ═══════════════════════════════════════════════════════════════════════════════
if [[ -n "$TOKEN" ]]; then
  log "Using token-based tunnel (headless mode)"

  # Write a simpler config for token mode
  cat > "$CF_DIR/config.yml" <<YAML
# Token-based tunnel — managed via Cloudflare Zero Trust dashboard
# The tunnel ID and ingress rules are configured in the dashboard.
# This file is only needed for local overrides.
YAML

  # Create a systemd service for cloudflared
  cat > /etc/systemd/system/cloudflared-tunnel.service <<SVC
[Unit]
Description=Cloudflare Tunnel for Sales Platform
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/cloudflared tunnel --no-autoupdate run --token ${TOKEN}
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
SVC

  systemctl daemon-reload
  systemctl enable cloudflared-tunnel
  systemctl start cloudflared-tunnel

  log "Tunnel running via systemd (token mode)"
  log "Configure ingress rules in Cloudflare Zero Trust dashboard:"
  log "  https://one.dash.cloudflare.com → Networks → Tunnels"
  echo
  echo -e "${BOLD}Add these public hostname rules in the dashboard:${NC}"
  echo "  ${DOMAIN}         → http://localhost:8080"
  echo "  ${DOMAIN}/api/*   → http://localhost:8000"
  echo
  systemctl status cloudflared-tunnel --no-pager || true
  exit 0
fi

# ═══════════════════════════════════════════════════════════════════════════════
# Method 2: CLI-based (interactive — needs browser for first auth)
# ═══════════════════════════════════════════════════════════════════════════════
log "Step 1/4: Authenticate with Cloudflare"
echo "  This will print a URL. Open it in your browser to authorize."
echo "  (You'll select the zone: reventlabs.com)"
echo
cloudflared tunnel login

# Copy cert to project
if [[ -f "$HOME/.cloudflared/cert.pem" ]]; then
  cp "$HOME/.cloudflared/cert.pem" "$CREDS_DIR/cert.pem"
  log "  Certificate saved"
fi

# ── Create tunnel ─────────────────────────────────────────────────────────────
log "Step 2/4: Creating tunnel '$TUNNEL_NAME'"

# Check if tunnel already exists
EXISTING=$(cloudflared tunnel list --name "$TUNNEL_NAME" -o json 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(d[0]['id'] if d else '')
" 2>/dev/null || echo "")

if [[ -n "$EXISTING" ]]; then
  TUNNEL_ID="$EXISTING"
  warn "  Tunnel already exists: $TUNNEL_ID"
else
  cloudflared tunnel create "$TUNNEL_NAME"
  TUNNEL_ID=$(cloudflared tunnel list --name "$TUNNEL_NAME" -o json 2>/dev/null | python3 -c "
import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')
" 2>/dev/null || echo "")
fi

[[ -n "$TUNNEL_ID" ]] || fail "Could not determine tunnel ID"
log "  Tunnel ID: $TUNNEL_ID"

# Copy credentials
if [[ -f "$HOME/.cloudflared/$TUNNEL_ID.json" ]]; then
  cp "$HOME/.cloudflared/$TUNNEL_ID.json" "$CREDS_DIR/$TUNNEL_ID.json"
  log "  Credentials saved to $CREDS_DIR/"
fi

# ── DNS route ─────────────────────────────────────────────────────────────────
log "Step 3/4: Creating DNS route"
cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN" 2>&1 || warn "  DNS route may already exist"
log "  $DOMAIN → tunnel:$TUNNEL_NAME"

# ── Update config.yml ─────────────────────────────────────────────────────────
log "Step 4/4: Writing tunnel config"
cat > "$CF_DIR/config.yml" <<YAML
# =============================================================================
# Cloudflare Tunnel config — auto-generated by setup-tunnel.sh
# Tunnel: $TUNNEL_NAME ($TUNNEL_ID)
# Domain: $DOMAIN
# =============================================================================

tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/creds/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    path: /api/*
    service: http://nginx:80
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true

  - hostname: $DOMAIN
    service: http://nginx:80
    originRequest:
      connectTimeout: 10s
      noTLSVerify: true

  - hostname: $DOMAIN
    path: /health
    service: http://nginx:80

  - service: http_status:404
YAML

log "Config written to $CF_DIR/config.yml"

# ═══════════════════════════════════════════════════════════════════════════════
echo
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Cloudflare Tunnel configured!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo
echo "  Tunnel:  $TUNNEL_NAME"
echo "  ID:      $TUNNEL_ID"
echo "  Domain:  $DOMAIN"
echo "  Creds:   $CREDS_DIR/$TUNNEL_ID.json"
echo
echo -e "${BOLD}Now deploy:${NC}"
echo "  cd $PROJECT_DIR"
echo "  make build && make tunnel-deploy"
echo
echo -e "${BOLD}After deploy, verify:${NC}"
echo "  make tunnel-status"
echo "  curl https://$DOMAIN/health"
echo

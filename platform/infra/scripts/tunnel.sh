#!/usr/bin/env bash
# =============================================================================
# infra/scripts/tunnel.sh — Cloudflare Tunnel setup and management
#
# Commands:
#   bash infra/scripts/tunnel.sh login                    # authenticate
#   bash infra/scripts/tunnel.sh create <name> <domain>   # create tunnel + DNS
#   bash infra/scripts/tunnel.sh status                   # show tunnel info
#   bash infra/scripts/tunnel.sh list                     # list all tunnels
#   bash infra/scripts/tunnel.sh delete <name>            # delete tunnel
#   bash infra/scripts/tunnel.sh logs                     # tail tunnel logs
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
CF_DIR="$PROJECT_DIR/infra/cloudflare"
CREDS_DIR="$PROJECT_DIR/infra/cloudflare/creds"
CONFIG="$CF_DIR/config.yml"

COMPOSE_TUNNEL="docker compose -f $PROJECT_DIR/docker-compose.prod.yml -f $PROJECT_DIR/docker-compose.tunnel.yml"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()   { echo -e "${GREEN}[tunnel] $*${NC}"; }
warn()  { echo -e "${YELLOW}[tunnel] $*${NC}"; }
error() { echo -e "${RED}[tunnel] ERROR: $*${NC}" >&2; exit 1; }

CMD="${1:-help}"
shift || true

# ── Ensure cloudflared is available ──────────────────────────────────────────
ensure_cloudflared() {
  if command -v cloudflared &>/dev/null; then
    return
  fi
  if docker image inspect cloudflare/cloudflared:latest &>/dev/null; then
    # Use docker as fallback
    cloudflared() {
      docker run --rm -v "$CREDS_DIR:/root/.cloudflared" cloudflare/cloudflared:latest "$@"
    }
    export -f cloudflared 2>/dev/null || true
    return
  fi
  warn "cloudflared not found. Installing..."
  case "$(uname -s)" in
    Linux)
      if [[ "$(uname -m)" == "aarch64" ]]; then
        curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
      else
        curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
      fi
      chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/
      ;;
    Darwin)
      brew install cloudflared 2>/dev/null || {
        curl -L -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz
        tar xzf /tmp/cloudflared -C /tmp && sudo mv /tmp/cloudflared /usr/local/bin/
      }
      ;;
    *) error "Unsupported OS. Install cloudflared manually." ;;
  esac
  log "cloudflared installed: $(cloudflared --version)"
}

# ── Commands ─────────────────────────────────────────────────────────────────
case "$CMD" in
  login)
    ensure_cloudflared
    log "Authenticating with Cloudflare..."
    echo "  This will open a browser. Log in and authorize the tunnel."
    echo
    mkdir -p "$CREDS_DIR"
    cloudflared tunnel login
    # Copy cert to creds dir if it's in default location
    DEFAULT_CERT="$HOME/.cloudflared/cert.pem"
    if [[ -f "$DEFAULT_CERT" ]]; then
      cp "$DEFAULT_CERT" "$CREDS_DIR/cert.pem"
      log "Certificate saved to $CREDS_DIR/cert.pem"
    fi
    log "Login successful!"
    ;;

  create)
    ensure_cloudflared
    TUNNEL_NAME="${1:-sales-platform}"
    DOMAIN="${2:-}"
    [[ -n "$DOMAIN" ]] || error "Usage: tunnel.sh create <name> <domain>"

    log "Creating tunnel: $TUNNEL_NAME"
    mkdir -p "$CREDS_DIR"

    # Create the tunnel
    cloudflared tunnel create "$TUNNEL_NAME" 2>&1 | tee /tmp/tunnel-create.log
    TUNNEL_ID=$(grep -oP '(?<=Created tunnel ).*(?= with id )' /tmp/tunnel-create.log 2>/dev/null || true)
    if [[ -z "$TUNNEL_ID" ]]; then
      TUNNEL_ID=$(cloudflared tunnel list --name "$TUNNEL_NAME" -o json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])" 2>/dev/null || true)
    fi
    [[ -n "$TUNNEL_ID" ]] || error "Could not get tunnel ID. Run 'cloudflared tunnel list' manually."

    log "Tunnel ID: $TUNNEL_ID"

    # Copy credentials file
    SRC_CRED="$HOME/.cloudflared/$TUNNEL_ID.json"
    if [[ -f "$SRC_CRED" ]]; then
      cp "$SRC_CRED" "$CREDS_DIR/$TUNNEL_ID.json"
      log "Credentials saved to $CREDS_DIR/$TUNNEL_ID.json"
    fi

    # Create DNS route (CNAME to tunnel)
    log "Creating DNS route: $DOMAIN → $TUNNEL_NAME"
    cloudflared tunnel route dns "$TUNNEL_NAME" "$DOMAIN" || warn "DNS route may already exist"

    # Update config.yml
    sed -i.bak "s/TUNNEL_ID/$TUNNEL_ID/g" "$CONFIG"
    sed -i.bak "s/DOMAIN/$DOMAIN/g" "$CONFIG"
    rm -f "$CONFIG.bak"

    echo
    log "Tunnel setup complete!"
    echo -e "${BOLD}Next steps:${NC}"
    echo "  1. Verify: cloudflared tunnel list"
    echo "  2. Start:  make tunnel-up"
    echo "  3. Check:  make tunnel-status"
    ;;

  status)
    echo -e "${BOLD}Tunnel Status:${NC}"
    # Check if cloudflared container is running
    if docker ps --format '{{.Names}}' | grep -q cloudflared; then
      echo -e "  Container: ${GREEN}RUNNING${NC}"
      $COMPOSE_TUNNEL logs --tail=5 cloudflared 2>/dev/null | sed 's/^/  /'
    else
      echo -e "  Container: ${RED}NOT RUNNING${NC}"
    fi
    echo
    # Show config
    if [[ -f "$CONFIG" ]]; then
      TUNNEL_ID=$(grep "^tunnel:" "$CONFIG" | awk '{print $2}')
      echo "  Tunnel ID: $TUNNEL_ID"
      DOMAIN=$(grep "hostname:" "$CONFIG" | head -1 | awk '{print $2}')
      echo "  Domain:    $DOMAIN"
    fi
    echo
    # Check connectivity
    ensure_cloudflared 2>/dev/null || true
    if command -v cloudflared &>/dev/null; then
      cloudflared tunnel info "$(grep "^tunnel:" "$CONFIG" | awk '{print $2}')" 2>/dev/null || true
    fi
    ;;

  list)
    ensure_cloudflared
    cloudflared tunnel list
    ;;

  delete)
    ensure_cloudflared
    TUNNEL_NAME="${1:-}"
    [[ -n "$TUNNEL_NAME" ]] || error "Usage: tunnel.sh delete <name>"
    warn "Deleting tunnel: $TUNNEL_NAME"
    read -r -p "  Continue? [y/N] " CONFIRM
    [[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
    # Stop container first
    $COMPOSE_TUNNEL stop cloudflared 2>/dev/null || true
    cloudflared tunnel delete "$TUNNEL_NAME"
    log "Tunnel deleted."
    ;;

  logs)
    $COMPOSE_TUNNEL logs -f --tail=50 cloudflared
    ;;

  help|*)
    echo -e "${BOLD}Cloudflare Tunnel Manager${NC}"
    echo
    echo "  Usage: bash infra/scripts/tunnel.sh <command> [args]"
    echo
    echo "  Commands:"
    echo "    login                     Authenticate with Cloudflare"
    echo "    create <name> <domain>    Create tunnel and DNS route"
    echo "    status                    Show tunnel health"
    echo "    list                      List all tunnels"
    echo "    delete <name>             Delete a tunnel"
    echo "    logs                      Tail tunnel container logs"
    echo
    echo "  Quick start:"
    echo "    1. bash infra/scripts/tunnel.sh login"
    echo "    2. bash infra/scripts/tunnel.sh create sales-platform sales.example.com"
    echo "    3. make tunnel-up"
    ;;
esac

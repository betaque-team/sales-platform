#!/usr/bin/env bash
# =============================================================================
# bootstrap.sh — One-command server setup for Oracle Cloud Free Tier ARM VM
#
# Run this ON THE SERVER after SSH'ing in:
#   curl -sSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/platform/infra/scripts/bootstrap.sh | bash
#
# Or after cloning:
#   bash infra/scripts/bootstrap.sh
#
# What it does:
#   1. Install Docker + Docker Compose
#   2. Install cloudflared
#   3. Configure firewall (SSH only — tunnel handles web traffic)
#   4. Create swap (2GB)
#   5. Clone repo (if not already cloned)
#   6. Prompt for .env setup
#   7. Build images
#   8. Start Cloudflare Tunnel login flow
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[bootstrap] $*${NC}"; }
warn() { echo -e "${YELLOW}[bootstrap] $*${NC}"; }
fail() { echo -e "${RED}[bootstrap] ERROR: $*${NC}" >&2; exit 1; }

APP_DIR="/opt/sales-platform"
DOMAIN="salesplatform.reventlabs.com"
TUNNEL_NAME="sales-platform"

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  Sales Platform — Server Bootstrap               ║"
echo "  ║  Target: Oracle Cloud Free Tier (ARM64)          ║"
echo "  ║  Domain: ${DOMAIN}             ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Must be root or sudo ─────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  fail "Run as root: sudo bash bootstrap.sh"
fi

export DEBIAN_FRONTEND=noninteractive

# ═══════════════════════════════════════════════════════════════════════════════
# 1. System updates + essentials
# ═══════════════════════════════════════════════════════════════════════════════
log "1/8  System update..."
apt-get update -qq && apt-get upgrade -y -qq

log "1/8  Installing essentials..."
apt-get install -y -qq \
  apt-transport-https ca-certificates curl gnupg lsb-release \
  git ufw fail2ban htop jq python3-minimal unzip

# ═══════════════════════════════════════════════════════════════════════════════
# 2. Docker
# ═══════════════════════════════════════════════════════════════════════════════
if ! command -v docker &>/dev/null; then
  log "2/8  Installing Docker..."
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable docker && systemctl start docker
else
  log "2/8  Docker already installed"
fi

# Add default user to docker group (ubuntu for Oracle, opc for older)
for u in ubuntu opc; do
  id "$u" &>/dev/null && usermod -aG docker "$u" 2>/dev/null || true
done

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Cloudflared
# ═══════════════════════════════════════════════════════════════════════════════
if ! command -v cloudflared &>/dev/null; then
  log "3/8  Installing cloudflared..."
  ARCH=$(dpkg --print-architecture)   # arm64 on Oracle free tier
  curl -sSL -o /tmp/cloudflared \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
  chmod +x /tmp/cloudflared
  mv /tmp/cloudflared /usr/local/bin/cloudflared
  log "  cloudflared $(cloudflared --version 2>&1 | head -1)"
else
  log "3/8  cloudflared already installed"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Firewall — SSH only (tunnel handles web traffic, no 80/443 needed)
# ═══════════════════════════════════════════════════════════════════════════════
log "4/8  Configuring firewall (SSH only)..."
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp        # SSH
# NO 80/443 — cloudflared connects outbound, no inbound ports needed
ufw --force enable
log "  Only port 22 open. All web traffic goes through Cloudflare Tunnel."

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Fail2ban
# ═══════════════════════════════════════════════════════════════════════════════
log "5/8  Enabling fail2ban..."
systemctl enable fail2ban && systemctl start fail2ban

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Swap (Oracle free VMs have plenty of RAM but swap is a safety net)
# ═══════════════════════════════════════════════════════════════════════════════
if [ ! -f /swapfile ]; then
  log "6/8  Creating 2GB swap..."
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  echo "vm.swappiness=10" >> /etc/sysctl.conf
else
  log "6/8  Swap already exists"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Clone or update repo
# ═══════════════════════════════════════════════════════════════════════════════
log "7/8  Setting up application directory..."
mkdir -p "$APP_DIR"

if [ -d "$APP_DIR/platform" ]; then
  log "  Repo exists, pulling latest..."
  cd "$APP_DIR/platform" && git pull || true
elif [ -f "$APP_DIR/docker-compose.prod.yml" ]; then
  log "  Code already in place (manual copy)"
else
  warn "  No code found at $APP_DIR"
  warn "  After this script, copy your code:"
  warn "    scp -r platform/ root@YOUR_SERVER:$APP_DIR/"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# 8. Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Server bootstrapped!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo
echo "  Docker:      $(docker --version 2>&1 | head -1)"
echo "  Compose:     $(docker compose version 2>&1 | head -1)"
echo "  cloudflared: $(cloudflared --version 2>&1 | head -1)"
echo "  Firewall:    SSH only (port 22)"
echo "  Swap:        $(swapon --show --noheadings | awk '{print $3}' || echo '2G')"
echo "  RAM:         $(free -h | awk '/Mem:/{print $2}') total"
echo "  Disk:        $(df -h / | awk 'NR==2{print $4}') free"
echo "  Arch:        $(dpkg --print-architecture)"
echo
echo -e "${BOLD}Next steps (run as the normal user, not root):${NC}"
echo
echo "  # 1. Copy code to server (from your Mac):"
echo "  scp -r platform/ ubuntu@YOUR_SERVER_IP:$APP_DIR/"
echo
echo "  # 2. SSH in and configure:"
echo "  ssh ubuntu@YOUR_SERVER_IP"
echo "  cd $APP_DIR"
echo "  cp .env.example .env && nano .env    # set passwords + secrets"
echo
echo "  # 3. Cloudflare Tunnel setup:"
echo "  cloudflared tunnel login             # opens URL — paste in browser"
echo "  cloudflared tunnel create $TUNNEL_NAME"
echo "  cloudflared tunnel route dns $TUNNEL_NAME $DOMAIN"
echo
echo "  # 4. Build and deploy:"
echo "  make build"
echo "  make tunnel-deploy"
echo
echo "  # 5. Verify:"
echo "  make tunnel-status"
echo "  curl https://$DOMAIN/health"
echo

#!/usr/bin/env bash
# =============================================================================
# infra/scripts/provision.sh — Provision a fresh Ubuntu server via SSH
# Called by: make provision SERVER=root@1.2.3.4
#
# What it does:
#   1. System updates + essential packages
#   2. Docker + Docker Compose
#   3. Firewall (SSH, HTTP, HTTPS only)
#   4. Fail2ban
#   5. 2GB swap (for small VMs)
#   6. Clone repo + deploy
# =============================================================================
set -euo pipefail

SERVER="${1:-}"
[[ -n "$SERVER" ]] || { echo "Usage: bash infra/scripts/provision.sh root@1.2.3.4"; exit 1; }

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${GREEN}[provision] $*${NC}"; }
warn() { echo -e "${YELLOW}[provision] $*${NC}"; }

echo -e "${BOLD}Provisioning: $SERVER${NC}"
echo "  This will install Docker, configure firewall, and deploy the platform."
read -r -p "  Continue? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# ── Remote execution ─────────────────────────────────────────────────────────
ssh -o StrictHostKeyChecking=no "$SERVER" bash << 'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "=== System update ==="
apt-get update -qq && apt-get upgrade -y -qq

echo "=== Install essentials ==="
apt-get install -y -qq \
  apt-transport-https ca-certificates curl gnupg lsb-release \
  git ufw fail2ban htop jq python3-pip

echo "=== Install Docker ==="
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable docker
  systemctl start docker
  echo "Docker installed"
else
  echo "Docker already installed"
fi

echo "=== Configure firewall ==="
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw --force enable
echo "Firewall configured"

echo "=== Fail2ban ==="
systemctl enable fail2ban
systemctl start fail2ban

echo "=== Swap ==="
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl vm.swappiness=10
  echo "vm.swappiness=10" >> /etc/sysctl.conf
  echo "2GB swap created"
else
  echo "Swap already exists"
fi

echo "=== Install cloudflared ==="
if ! command -v cloudflared &>/dev/null; then
  ARCH=$(dpkg --print-architecture)
  curl -L -o /tmp/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}"
  chmod +x /tmp/cloudflared
  mv /tmp/cloudflared /usr/local/bin/cloudflared
  echo "cloudflared installed: $(cloudflared --version)"
else
  echo "cloudflared already installed"
fi

echo "=== Create app directory ==="
mkdir -p /opt/sales-platform
cd /opt/sales-platform

echo "=== Server ready ==="
echo "Docker: $(docker --version)"
echo "Compose: $(docker compose version)"
echo "cloudflared: $(cloudflared --version 2>&1 | head -1)"
echo "Disk: $(df -h / | awk 'NR==2{print $4}') free"
echo "RAM: $(free -h | awk '/Mem:/{print $2}') total"
REMOTE

log "Server provisioned!"
echo
echo -e "${BOLD}Next steps:${NC}"
echo "  1. Copy your code to the server:"
echo "     scp -r . $SERVER:/opt/sales-platform/"
echo
echo "  2. SSH in and deploy:"
echo "     ssh $SERVER"
echo "     cd /opt/sales-platform"
echo "     cp .env.example .env   # edit with real values"
echo "     make build"
echo
echo -e "${BOLD}  Option A: Cloudflare Tunnel (recommended — no public ports):${NC}"
echo "     make tunnel-login"
echo "     make tunnel-create TUNNEL_NAME=sales-platform DOMAIN=sales.example.com"
echo "     make tunnel-deploy"
echo
echo -e "${BOLD}  Option B: Traditional (ports 80/443 + SSL):${NC}"
echo "     make deploy"
echo "     make ssl-init DOMAIN=sales.example.com"

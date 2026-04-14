#!/usr/bin/env bash
# =============================================================================
# oci-setup-guide.sh — Interactive wizard: OCI account + Cloudflare + tfvars
# Run: make infra-setup
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TF_DIR="$(cd "$SCRIPT_DIR/../terraform" && pwd)"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'
log()  { echo -e "${GREEN}[setup] $*${NC}"; }
warn() { echo -e "${YELLOW}[setup] $*${NC}"; }
fail() { echo -e "${RED}[setup] ERROR: $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}━━━ Step $1: $2 ━━━${NC}\n"; }
hint() { echo -e "${DIM}  $*${NC}"; }

echo -e "${BOLD}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║  Sales Platform — Infrastructure Setup Wizard        ║"
echo "  ║  Oracle Cloud Free Tier + Cloudflare Tunnel          ║"
echo "  ║  Cost: \$0/month forever                              ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ═══════════════════════════════════════════════════════════════════════════════
step "0" "Prerequisites"
# ═══════════════════════════════════════════════════════════════════════════════

# Terraform
if command -v terraform &>/dev/null; then
  log "Terraform: $(terraform version -json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["terraform_version"])' 2>/dev/null || terraform version | head -1)"
else
  warn "Terraform not found. Install it:"
  echo "  macOS:  brew install terraform"
  echo "  Linux:  https://developer.hashicorp.com/terraform/install"
  echo
  read -r -p "  Press Enter after installing terraform... "
  command -v terraform &>/dev/null || fail "terraform still not found"
fi

# SSH key
SSH_PUB="$HOME/.ssh/id_rsa.pub"
SSH_PRIV="$HOME/.ssh/id_rsa"
if [[ -f "$SSH_PUB" ]]; then
  log "SSH key: $SSH_PUB"
else
  warn "No SSH key found. Generating one..."
  ssh-keygen -t rsa -b 4096 -f "$SSH_PRIV" -N "" -q
  log "SSH key generated: $SSH_PUB"
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "1" "Oracle Cloud Account"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  You need an Oracle Cloud account (free forever, no credit card required for Always Free)."
echo
echo "  1. Go to: ${BOLD}https://signup.cloud.oracle.com/${NC}"
echo "  2. Sign up with your email"
echo "  3. Select home region: ${BOLD}us-ashburn-1${NC} (best free tier availability)"
echo "  4. Wait for account activation (usually instant, max 24h)"
echo
read -r -p "  Press Enter after your account is active... "

# ═══════════════════════════════════════════════════════════════════════════════
step "2" "Tenancy OCID"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  1. Log into Oracle Cloud Console: ${BOLD}https://cloud.oracle.com${NC}"
echo "  2. Click your ${BOLD}profile icon${NC} (top right) → ${BOLD}Tenancy: <your-name>${NC}"
echo "  3. Copy the ${BOLD}OCID${NC} (starts with ocid1.tenancy.oc1..)"
echo
read -r -p "  Paste your Tenancy OCID: " TENANCY_OCID
[[ "$TENANCY_OCID" == ocid1.tenancy.* ]] || fail "Invalid tenancy OCID (must start with ocid1.tenancy.)"
log "Tenancy OCID: ${TENANCY_OCID:0:30}..."

# ═══════════════════════════════════════════════════════════════════════════════
step "3" "User OCID"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  1. Profile icon → ${BOLD}My profile${NC}"
echo "  2. Copy your ${BOLD}OCID${NC} (starts with ocid1.user.oc1..)"
echo
read -r -p "  Paste your User OCID: " USER_OCID
[[ "$USER_OCID" == ocid1.user.* ]] || fail "Invalid user OCID (must start with ocid1.user.)"
log "User OCID: ${USER_OCID:0:30}..."

# ═══════════════════════════════════════════════════════════════════════════════
step "4" "API Signing Key"
# ═══════════════════════════════════════════════════════════════════════════════

OCI_DIR="$HOME/.oci"
OCI_KEY="$OCI_DIR/oci_api_key.pem"
OCI_PUB="$OCI_DIR/oci_api_key_public.pem"

if [[ -f "$OCI_KEY" ]]; then
  log "OCI API key already exists: $OCI_KEY"
else
  log "Generating OCI API signing key..."
  mkdir -p "$OCI_DIR"
  openssl genrsa -out "$OCI_KEY" 2048 2>/dev/null
  chmod 600 "$OCI_KEY"
  openssl rsa -pubout -in "$OCI_KEY" -out "$OCI_PUB" 2>/dev/null
  log "Key generated: $OCI_KEY"
fi

echo
echo "  Now upload the ${BOLD}public key${NC} to Oracle Cloud:"
echo "  1. Profile icon → ${BOLD}My profile${NC} → ${BOLD}API keys${NC} (left sidebar)"
echo "  2. Click ${BOLD}Add API Key${NC} → ${BOLD}Paste Public Key${NC}"
echo "  3. Paste this:"
echo
echo -e "${DIM}$(cat "$OCI_PUB")${NC}"
echo
echo "  4. After pasting, Oracle shows the ${BOLD}fingerprint${NC} (aa:bb:cc:dd:... format)"
echo
read -r -p "  Paste the fingerprint: " FINGERPRINT
[[ "$FINGERPRINT" == *:*:* ]] || fail "Invalid fingerprint format"
log "Fingerprint: $FINGERPRINT"

# ═══════════════════════════════════════════════════════════════════════════════
step "5" "OCI Region"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  Which region did you select as home region?"
hint "us-ashburn-1 and us-phoenix-1 have the best ARM free-tier availability"
echo
read -r -p "  Region [us-ashburn-1]: " REGION
REGION="${REGION:-us-ashburn-1}"
log "Region: $REGION"

# ═══════════════════════════════════════════════════════════════════════════════
step "6" "Cloudflare API Token"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  1. Go to: ${BOLD}https://dash.cloudflare.com/profile/api-tokens${NC}"
echo "  2. Click ${BOLD}Create Token${NC}"
echo "  3. Use ${BOLD}Custom Token${NC} template with these permissions:"
echo "     - ${BOLD}Zone : DNS : Edit${NC}"
echo "     - ${BOLD}Account : Cloudflare Tunnel : Edit${NC}"
echo "     - ${BOLD}Account : Zero Trust : Edit${NC}"
echo "  4. Zone Resources: Include → Specific zone → ${BOLD}reventlabs.com${NC}"
echo "  5. Click ${BOLD}Continue to summary${NC} → ${BOLD}Create Token${NC}"
echo "  6. Copy the token"
echo
read -r -p "  Paste your Cloudflare API Token: " CF_TOKEN
[[ -n "$CF_TOKEN" ]] || fail "Token cannot be empty"
log "Cloudflare token: ${CF_TOKEN:0:8}..."

# ═══════════════════════════════════════════════════════════════════════════════
step "7" "Cloudflare Account & Zone ID"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  1. Go to: ${BOLD}https://dash.cloudflare.com${NC}"
echo "  2. Click on ${BOLD}reventlabs.com${NC}"
echo "  3. Scroll down on the right sidebar → ${BOLD}API${NC} section"
echo "  4. Copy ${BOLD}Zone ID${NC} and ${BOLD}Account ID${NC}"
echo
read -r -p "  Paste your Account ID: " CF_ACCOUNT_ID
read -r -p "  Paste your Zone ID: " CF_ZONE_ID
[[ -n "$CF_ACCOUNT_ID" ]] || fail "Account ID cannot be empty"
[[ -n "$CF_ZONE_ID" ]] || fail "Zone ID cannot be empty"
log "Account: ${CF_ACCOUNT_ID:0:8}... Zone: ${CF_ZONE_ID:0:8}..."

# ═══════════════════════════════════════════════════════════════════════════════
step "8" "Alert Email"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  Email for CPU and budget alerts (Oracle monitoring):"
read -r -p "  Alert email: " ALERT_EMAIL

# ═══════════════════════════════════════════════════════════════════════════════
step "9" "Git Repo URL (optional)"
# ═══════════════════════════════════════════════════════════════════════════════

echo "  Git repo URL to clone on the VM (leave empty to skip):"
hint "Example: https://github.com/your-org/your-repo.git"
read -r -p "  Git URL: " GIT_URL

# ═══════════════════════════════════════════════════════════════════════════════
step "10" "Generating terraform.tfvars"
# ═══════════════════════════════════════════════════════════════════════════════

TFVARS="$TF_DIR/terraform.tfvars"
cat > "$TFVARS" <<EOF
# Auto-generated by oci-setup-guide.sh on $(date)

# --- OCI Authentication ---
tenancy_ocid         = "$TENANCY_OCID"
user_ocid            = "$USER_OCID"
api_key_fingerprint  = "$FINGERPRINT"
api_private_key_path = "$OCI_KEY"
region               = "$REGION"
compartment_ocid     = ""

# --- Cloudflare ---
cloudflare_api_token  = "$CF_TOKEN"
cloudflare_account_id = "$CF_ACCOUNT_ID"
cloudflare_zone_id    = "$CF_ZONE_ID"

# --- SSH ---
ssh_public_key_path  = "$SSH_PUB"
ssh_private_key_path = "$SSH_PRIV"

# --- Compute (Oracle Free Tier) ---
instance_name      = "sales-platform"
instance_ocpus     = 4
instance_memory_gb = 24
boot_volume_gb     = 100

# --- Application ---
app_domain    = "salesplatform.reventlabs.com"
app_subdomain = "salesplatform"
git_repo_url  = "$GIT_URL"
alert_email   = "$ALERT_EMAIL"

# --- Secrets (auto-generated by Terraform) ---
postgres_password = ""
jwt_secret        = ""
anthropic_api_key = ""
EOF

log "Written: $TFVARS"

# ═══════════════════════════════════════════════════════════════════════════════
step "11" "Terraform Init + Plan"
# ═══════════════════════════════════════════════════════════════════════════════

cd "$TF_DIR"

log "Initializing Terraform..."
terraform init

echo
log "Planning infrastructure..."
terraform plan

echo
echo -e "${BOLD}Ready to create:${NC}"
echo "  - Oracle Cloud ARM VM (4 CPU, 24GB RAM, 100GB disk)"
echo "  - Cloudflare Tunnel + DNS (salesplatform.reventlabs.com)"
echo "  - Monitoring alarms + budget guard"
echo "  - Auto-deploy: Docker, app, database, tunnel"
echo
read -r -p "  Apply? [y/N] " CONFIRM
[[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Run 'make infra-up' when ready."; exit 0; }

terraform apply -auto-approve

# ═══════════════════════════════════════════════════════════════════════════════
step "11.5" "GitHub Deploy Key — Add to Repo (REQUIRED for private repos)"
# ═══════════════════════════════════════════════════════════════════════════════

DEPLOY_KEY_PUB="$(terraform output -raw github_deploy_key_public 2>/dev/null || true)"

if [[ -n "$DEPLOY_KEY_PUB" && -n "$GIT_URL" ]]; then
  echo
  echo -e "${BOLD}Terraform generated an ED25519 deploy key for your repo.${NC}"
  echo -e "The ${BOLD}private key${NC} is already installed on the VM (via cloud-init)."
  echo -e "You must add the ${BOLD}public key${NC} to GitHub before the VM can clone the repo."
  echo
  echo -e "${BOLD}Steps:${NC}"
  echo "  1. Go to: ${BOLD}${GIT_URL/git@github.com:/https://github.com/}${NC}"
  echo "     (replace git@github.com: with https://github.com/ if needed)"
  echo "  2. Settings → Deploy keys → Add deploy key"
  echo "  3. Title: ${BOLD}sales-platform-vm${NC}"
  echo "  4. Paste this public key:"
  echo
  echo -e "${DIM}${DEPLOY_KEY_PUB}${NC}"
  echo
  echo "  5. Check ${BOLD}Allow read access${NC} only (do NOT check write access)"
  echo "  6. Click ${BOLD}Add key${NC}"
  echo
  read -r -p "  Press Enter after the deploy key is added to GitHub... "
  log "Deploy key added. Cloud-init on the VM will now be able to clone the repo."
else
  hint "No git repo URL provided — skipping deploy key step."
fi

echo
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Infrastructure created!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo
terraform output -no-color
echo
echo -e "${YELLOW}  Cloud-init is now bootstrapping the VM (~5-8 min).${NC}"
echo -e "  Monitor progress:"
echo -e "    ${BOLD}make infra-ssh${NC}"
echo -e "    ${BOLD}sudo tail -f /var/log/cloud-init-output.log${NC}"
echo
echo -e "  Once cloud-init is complete:"
echo -e "    ${BOLD}https://salesplatform.reventlabs.com${NC}  — app is live"
echo -e "    Login: admin@jobplatform.io / admin123  (change immediately)"
echo
echo -e "${BOLD}  Migrate existing local data to the VM:${NC}"
echo -e "    ${BOLD}make migrate-data${NC}"
echo -e "    (Dumps your local DB, uploads it to the VM, restores + validates)"
echo

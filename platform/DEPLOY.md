# Deploy Guide — Oracle Cloud Free Tier + Cloudflare Tunnel

**Cost: $0/month forever.**

```
Your Mac                Oracle Cloud ARM VM (free)           Cloudflare
  │                       ┌──────────────────────┐
  │ git push / scp        │  Docker containers:  │
  ├──────────────────────►│  postgres, redis     │
                          │  backend, workers    │◄─── cloudflared ───► Edge ──► salesplatform.reventlabs.com
                          │  frontend, nginx     │     (outbound only)
                          │  cloudflared         │
                          └──────────────────────┘
                          No inbound ports needed
                          (firewall: SSH only)
```

---

## Prerequisites

1. **Oracle Cloud account** (free): https://cloud.oracle.com/
2. **Cloudflare account** (free): https://cloudflare.com
3. **Domain `reventlabs.com`** on Cloudflare DNS

---

## Step 1: Create Oracle Cloud VM

1. Go to Oracle Cloud Console → Compute → Instances → Create
2. Select:
   - **Shape**: VM.Standard.A1.Flex (ARM) — 4 OCPU, 24 GB RAM (free)
   - **Image**: Ubuntu 22.04 (or 24.04)
   - **Boot volume**: 100 GB (free up to 200 GB)
   - **Networking**: Create VCN with public subnet
3. Add your SSH public key
4. Note the **public IP**

### Oracle Cloud firewall (Security List)

In the VCN security list, keep only:
- **Ingress**: TCP port 22 (SSH) from 0.0.0.0/0
- **Egress**: All traffic (cloudflared needs outbound)
- **Remove** any rules for ports 80, 443 — tunnel handles it

---

## Step 2: Bootstrap the server

```bash
# SSH into your VM
ssh ubuntu@YOUR_VM_IP

# Run the bootstrap script (installs Docker, cloudflared, firewall)
sudo bash -c "$(curl -sSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/platform/infra/scripts/bootstrap.sh)"

# Or if you've already copied the code:
cd /opt/sales-platform
sudo bash infra/scripts/bootstrap.sh
```

---

## Step 3: Copy code to server

From your Mac:
```bash
scp -r platform/ ubuntu@YOUR_VM_IP:/opt/sales-platform/
```

Or clone from git:
```bash
ssh ubuntu@YOUR_VM_IP
cd /opt/sales-platform
git clone https://github.com/YOUR_ORG/YOUR_REPO.git .
```

---

## Step 4: Configure environment

```bash
ssh ubuntu@YOUR_VM_IP
cd /opt/sales-platform

cp .env.example .env
nano .env
```

Set at minimum:
```
POSTGRES_PASSWORD=<random-strong-password>
JWT_SECRET=<random-64-char-string>
ANTHROPIC_API_KEY=<your-key>   # optional, for AI features
```

Generate random secrets:
```bash
openssl rand -hex 32    # for JWT_SECRET
openssl rand -hex 16    # for POSTGRES_PASSWORD
```

---

## Step 5: Set up Cloudflare Tunnel

### Option A: Dashboard method (easiest, recommended)

1. Go to https://one.dash.cloudflare.com
2. Networks → Tunnels → **Create a tunnel**
3. Select **Cloudflared** connector
4. Name: `sales-platform`
5. Copy the **token** (long string starting with `eyJ...`)
6. On the server:
   ```bash
   bash infra/scripts/setup-tunnel.sh --token YOUR_TOKEN_HERE
   ```
7. Back in Cloudflare dashboard, add **Public Hostname**:
   - Subdomain: `salesplatform` | Domain: `reventlabs.com`
   - Service: `http://localhost:8080`

### Option B: CLI method

```bash
# On the server:
bash infra/scripts/setup-tunnel.sh

# This will:
# 1. Print a URL — open it in your browser to authenticate
# 2. Create the tunnel
# 3. Set up DNS (salesplatform.reventlabs.com → tunnel)
# 4. Write the config files
```

---

## Step 6: Build and deploy

```bash
cd /opt/sales-platform

# Build Docker images (takes ~3 min on ARM)
make build

# Deploy with tunnel
make tunnel-deploy

# Seed the database
make migrate
make seed
```

---

## Step 7: Verify

```bash
# Check everything is running
make tunnel-status

# Check from the internet
curl https://salesplatform.reventlabs.com/health
```

Open https://salesplatform.reventlabs.com in your browser.
Login: `admin@jobplatform.io` / `admin123`

---

## Day-to-day operations

| Task | Command (run on server) |
|------|------------------------|
| Redeploy latest code | `git pull && make build && make tunnel-deploy` |
| View status | `make status` |
| View logs | `make logs` |
| Backup database | `make backup` |
| List backups | `make backup-list` |
| Restore from backup | `make restore` |
| Rollback (code only) | `make rollback` |
| Rollback + DB restore | `make rollback-full` |
| Tunnel logs | `make tunnel-logs` |
| DB shell | `make db-shell` |
| DB row counts | `make db-stats` |

---

## Automated backups

Backups run automatically via Celery beat (nightly). To add cron backup:
```bash
crontab -e
# Add:
0 3 * * * cd /opt/sales-platform && bash infra/scripts/backup.sh >> /opt/sales-platform/backups/cron.log 2>&1
```

---

## CI/CD (optional)

Set these GitHub secrets:
- `SERVER_HOST`: your VM public IP
- `SERVER_USER`: `ubuntu`
- `SSH_PRIVATE_KEY`: your SSH private key
- `USE_TUNNEL`: `true`

Then every push to `main` auto-deploys.

---

## Costs

| Service | Cost |
|---------|------|
| Oracle Cloud VM (A1.Flex, 4 CPU, 24GB RAM) | **Free forever** |
| Oracle Cloud storage (100GB) | **Free forever** |
| Cloudflare Tunnel | **Free** |
| Cloudflare DNS | **Free** |
| Cloudflare SSL | **Free** |
| Cloudflare DDoS protection | **Free** |
| **Total** | **$0/month** |

# Cloudflare Tunnel Credential Rotation

**Context:** `platform/cloudflared/credentials.json` was tracked in git from the initial commit. It holds the live `TunnelSecret` + `AccountTag`. While the file is now removed from tracking and blocked by gitignore + pre-commit hooks, the value is **permanently present in git history** until we rotate.

**Impact of the leak (before rotation):** Anyone with read access to the repo history can authenticate to Cloudflare as this tunnel. Worst case: they run their own `cloudflared` instance with these creds and proxy/sniff traffic intended for your tunnel, or replace your routes.

**Impact if repo is public:** Elevated — assume any GitHub crawler has already seen it.

**Impact if repo is private:** Limited to collaborators past + present.

---

## Rotation plan

Expected downtime: **~30–60 seconds** during the switchover (while DNS propagates and the new tunnel connects). Do this during a quiet window.

### Option A — Recommended: new tunnel, atomic swap

Keeps the old tunnel running until the new one is serving traffic, then cuts over. Minimizes downtime.

```bash
# ─── 1. On your Mac: log in to Cloudflare ─────────────────────────────
cloudflared login
# Opens a browser; authorize the domain reventlabs.com.

# ─── 2. Create the replacement tunnel ────────────────────────────────
cloudflared tunnel create sales-platform-v2
# Prints: Created tunnel sales-platform-v2 with id <NEW_UUID>
# Writes: ~/.cloudflared/<NEW_UUID>.json   ← this is the new credentials file

# ─── 3. Copy the new creds to the VM ─────────────────────────────────
scp ~/.cloudflared/<NEW_UUID>.json \
    ubuntu@<VM_HOST>:/tmp/cf-creds-new.json

ssh ubuntu@<VM_HOST>
sudo install -o deploy -g deploy -m 0600 \
    /tmp/cf-creds-new.json \
    /opt/sales-platform/cloudflared/credentials.json.new
rm /tmp/cf-creds-new.json

# ─── 4. Update the tunnel config on VM ───────────────────────────────
# Edit /opt/sales-platform/cloudflared/config.yml — change:
#   tunnel: <OLD_UUID>
#   credentials-file: /etc/cloudflared/credentials.json
# to:
#   tunnel: <NEW_UUID>
#   credentials-file: /etc/cloudflared/credentials.json
# (ingress section stays identical)

sudo cp /opt/sales-platform/cloudflared/config.yml /opt/sales-platform/cloudflared/config.yml.bak
sudo -u deploy vi /opt/sales-platform/cloudflared/config.yml  # change tunnel UUID

# ─── 5. Atomic swap the credentials file ─────────────────────────────
sudo -u deploy mv /opt/sales-platform/cloudflared/credentials.json \
                  /opt/sales-platform/cloudflared/credentials.json.old
sudo -u deploy mv /opt/sales-platform/cloudflared/credentials.json.new \
                  /opt/sales-platform/cloudflared/credentials.json

# ─── 6. Update DNS CNAME to point at the new tunnel ──────────────────
# In Cloudflare dashboard → DNS → salesplatform.reventlabs.com CNAME:
# Change target from <OLD_UUID>.cfargotunnel.com
#                 to <NEW_UUID>.cfargotunnel.com
# Proxied: ON (orange cloud)
# Propagates in ~seconds.

# ─── 7. Restart the tunnel on VM ─────────────────────────────────────
cd /opt/sales-platform
docker compose -f docker-compose.prod.yml restart cloudflared
# OR if cloudflared runs as systemd:
sudo systemctl restart cloudflared

# ─── 8. Verify ───────────────────────────────────────────────────────
# From Mac:
curl -I https://salesplatform.reventlabs.com/api/v1/monitoring
# Expect HTTP/2 401 (auth enforced, backend serving)

# From Cloudflare dashboard → Zero Trust → Networks → Tunnels:
# - sales-platform-v2 should show "Healthy"
# - old sales-platform tunnel should show "Inactive"

# ─── 9. Delete the old tunnel once verified stable ───────────────────
# Wait 5–10 min to make sure nothing is reaching the old one, then:
cloudflared tunnel delete <OLD_TUNNEL_NAME_OR_UUID>

# Clean up on VM:
ssh ubuntu@<VM_HOST> \
  'sudo -u deploy rm /opt/sales-platform/cloudflared/credentials.json.old /opt/sales-platform/cloudflared/config.yml.bak'

# Clean up on Mac:
rm ~/.cloudflared/<OLD_UUID>.json
```

### Option B — Same tunnel, refresh secret only

Cloudflare does not expose a "rotate secret" operation on an existing tunnel — you have to delete + recreate. So there is no real "Option B"; use Option A.

---

## Post-rotation checklist

- [ ] `curl -I https://salesplatform.reventlabs.com/api/v1/monitoring` → HTTP 401
- [ ] `curl -I https://salesplatform.reventlabs.com/` → HTTP 200
- [ ] Cloudflare dashboard: only one tunnel healthy, others deleted or inactive
- [ ] VM: `stat -c '%a %U:%G' /opt/sales-platform/cloudflared/credentials.json` → `600 deploy:deploy`
- [ ] Git: `git check-ignore -v platform/cloudflared/credentials.json` matches a rule (should be `**/cloudflared/*.json`)
- [ ] Run `bash scripts/security-audit.sh` from Mac (expect 15 PASS / 1 WARN / 0 FAIL as before)

## What NOT to do

- **Do not** `git filter-repo` to scrub history unless you're ready to force-push and coordinate with every collaborator to re-clone. Rotation makes the leaked value useless; history rewrite has high blast radius.
- **Do not** put the new creds anywhere in the repo — even in a `scripts/setup-tunnel.sh`. The VM gets them once via `scp` + `install`, then the file lives only on the VM.
- **Do not** reuse `sales-platform` as the new tunnel name — Cloudflare tombstones deleted names for a short window, and reusing invites confusion. Use `sales-platform-v2` or a dated suffix.

## Other leaked credentials to consider

These are flagged for your review — I can't see their current status without more access:

| Credential | Where it lived | Action |
|---|---|---|
| VM IP `<was committed>` | deploy.yml comment, several docs | Scrubbed. IP itself isn't strongly confidential (port-scannable) — rotation optional. Oracle free-tier IPs are reassignable from the OCI console. |
| VM SSH host-key pin | `docs/DEPLOY_SETUP.md` table row | Scrubbed. Host keys are public by design (published fingerprints). No rotation needed unless the VM is rebuilt. |
| `JWT_SECRET` (23 bytes in `.env`) | VM `/opt/sales-platform/.env` (not in repo) | **Consider rotating to ≥32 bytes** (e.g. `openssl rand -hex 32`). Current value is NOT the literal `"change-me-in-production"` placeholder (verified by hash), but 23 bytes is below the HS256 comfortable-entropy threshold. Rotation invalidates all current JWTs → users re-login. |
| `POSTGRES_PASSWORD` | VM `.env` (not in repo) | Fine if never leaked. Rotate if in doubt — requires `ALTER USER` in postgres + update `.env` + restart backend/celery. |
| `GOOGLE_CLIENT_SECRET` | VM `.env` (not in repo) | Fine if never leaked. Rotate from Google Cloud console if suspected. |
| `RAPIDAPI_KEY` | VM `.env` (not in repo) | Fine if never leaked. Regenerate from RapidAPI dashboard if suspected. |
| `ANTHROPIC_API_KEY` | VM `.env` (empty — not in use) | n/a until set. |
| SSH deploy key (`DEPLOY_SSH_KEY`) | GH Environment secret; public half on VM | See `docs/DEPLOYMENT_PROCESS.md` → Rotating the deploy SSH key. Rotate every 90 days. |
| OCI API signing key | `~/.oci/` on your Mac | Should never be in the repo (gitignored via `**/.oci/`). Rotate in OCI console if Mac was compromised. |
| Cloudflare API token | `~/.cloudflared/cert.pem` on Mac; `terraform.tfvars` (gitignored) | Rotate from Cloudflare dashboard if suspected. |

---

## Why this matters

A tunnel credential is more dangerous than a typical API key because:
1. It grants **persistent outbound-originated** access to Cloudflare Edge — the attacker doesn't need inbound network reach.
2. It can be used to register a rogue origin, potentially stealing decrypted traffic before it reaches your VM.
3. Cloudflare does not show "last used by IP" on tunnel credentials, so detection is near-zero.

Treat it with the same care as a production DB password.

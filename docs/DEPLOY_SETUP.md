# CI/CD Setup — GitHub → Prod VM

One-time setup to wire up the auto-deploy pipeline. After this is done, every push to `main` triggers:

```
GitHub Actions
  └─ build & push images → ghcr.io/betaque-team/sales-platform/{backend,frontend}:sha-<short>
     └─ SSH to VM as `deploy` user (forced-command → ci-deploy.sh only)
        └─ pre-deploy DB backup
        └─ docker pull new tag
        └─ alembic upgrade head
        └─ rolling restart backend → health-check → celery/frontend/nginx
        └─ auto-rollback if health fails
```

---

## What's already done (by Claude)

- ✅ Created `deploy` user on VM (`docker` group only, no sudo, owns `/opt/sales-platform`)
- ✅ Generated dedicated ed25519 keypair `~/.ssh/sales-platform-ci` on your Mac
- ✅ Public half installed on VM at `/home/deploy/.ssh/authorized_keys` with
  `restrict,command="/opt/sales-platform/scripts/ci-deploy.sh"` → a stolen private key
  can only run `deploy <tag> | rollback <tag> | status`, cannot pop a shell
- ✅ `ci-deploy.sh` installed at `/opt/sales-platform/scripts/ci-deploy.sh` (owned by `deploy`)
- ✅ Workflows at repo root: `.github/workflows/{ci,deploy,rollback}.yml`
- ✅ Smoke-tested SSH forced-command (arbitrary commands rejected, tag injection rejected)

---

## What you need to do (one-time, GitHub UI)

GitHub's UI can't be automated for Environments + Secrets, so these few clicks are on you.

### 1. Create the `production` environment

1. Go to **Settings → Environments → New environment**
2. Name: `production`
3. Configure:
   - **Deployment branches**: select *Selected branches* → add rule for `main`
   - **Wait timer**: `2` minutes (cancels window; not a required approval)
   - **Required reviewers**: leave empty (auto-deploy was chosen)

### 2. Add these environment secrets

In the `production` environment → **Add secret**:

| Secret name | Value | Notes |
|---|---|---|
| `DEPLOY_HOST` | `161.118.207.119` | VM public IP |
| `DEPLOY_USER` | `deploy` | VM user with docker group only |
| `DEPLOY_SSH_KEY` | *(paste the full contents of `~/.ssh/sales-platform-ci` from your Mac)* | Include the `-----BEGIN ... END-----` lines |
| `DEPLOY_HOSTKEY` | `\|1\|SaFx4T6ADdCsBlr8zifAn5ZKQf4=\|uhaqBtgyUlPGaFePJbPhaXE1jMM= ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOfzjSsZiXrx4zG/Gofm5pYu73V8d3EH69+MDAY/0deE` | Pins the VM host key. Copy verbatim. |

To grab the private key on your Mac:
```bash
cat ~/.ssh/sales-platform-ci
```

Copy the entire block (including the `-----BEGIN OPENSSH PRIVATE KEY-----` / `-----END` lines) and paste into the `DEPLOY_SSH_KEY` secret.

### 3. Make the GHCR images pullable from the VM

The VM's `deploy` user needs to authenticate to GHCR to pull the images. Two options — pick one:

**Option A (simplest): make the images public.** After the first successful build, go to:
- `https://github.com/orgs/betaque-team/packages` (or wherever the packages show up)
- `sales-platform/backend` and `sales-platform/frontend` → **Package settings** → **Change visibility** → Public

Public GHCR pulls need no auth. Read-only, the images contain no secrets (all secrets are in `/opt/sales-platform/.env` on the VM, not baked in).

**Option B (private): store a GHCR PAT on the VM.**

1. On GitHub: **Settings (your user) → Developer settings → Personal access tokens → Fine-grained tokens → Generate new**
   - Name: `sales-platform-vm-ghcr-read`
   - Resource owner: `betaque-team`
   - Expiration: 90 days
   - Permissions → **Packages (read-only)**
2. Copy the token (starts with `github_pat_...`)
3. On the VM as ubuntu:
   ```bash
   sudo -u deploy bash -c 'echo "YOUR_PAT" | docker login ghcr.io -u YOUR_GH_USERNAME --password-stdin'
   ```
   This creates `/home/deploy/.docker/config.json` (mode 600).
4. Add a 90-day reminder to rotate.

> **Recommendation:** Option A. Zero ongoing maintenance, and the images contain only your open-source code (no secrets). If the repo itself is private, the image can still be public.

### 4. (Optional, stronger) Restrict SSH from GitHub IP ranges

Already safe because of the forced-command, but if you want an extra layer, update `/home/deploy/.ssh/authorized_keys` to:

```
restrict,command="/opt/sales-platform/scripts/ci-deploy.sh",from="140.82.112.0/20,143.55.64.0/20,192.30.252.0/22,185.199.108.0/22,2606:50c0::/32" ssh-ed25519 ...
```

GitHub publishes current ranges at https://api.github.com/meta (`actions` key). If you enable this, refresh monthly (a simple cron job can pull the JSON and rewrite the line).

---

## First deploy

Once the secrets above are set:

1. Merge this branch (or push to `main` directly)
2. Watch: **Actions → Deploy**
3. After the 2-min wait timer, the build job kicks off (~90 sec), then deploy job SSHes and triggers `ci-deploy.sh deploy sha-<short>`
4. Summary in the Actions run shows `status` output (current tag + container health)
5. Visit https://salesplatform.reventlabs.com — should be the new build

If the first deploy fails at SSH, most likely cause: host-key mismatch (check `DEPLOY_HOSTKEY` pasted verbatim, or leave blank to auto-scan the first run).

If it fails at `docker pull`, the GHCR package is still private and the VM isn't authed — pick Option A or B above.

---

## Rolling back

**App-only rollback (recommended, 30 sec):**
1. GitHub → **Actions → Rollback → Run workflow**
2. Input: the prior tag (e.g. `sha-abc1234`)
3. Confirm
4. The VM swaps `RELEASE_TAG` in `.env` and restarts the services to the older image

**DB restore (opt-in, destructive):**
Not automated. If you really need to restore the DB (rare — usually the app rollback is enough):
```bash
ssh ubuntu@161.118.207.119
cd /opt/sales-platform
ls backups/pre-deploy-*.sql.gz
bash scripts/restore.sh <backup-file>
```

---

## Day-2 maintenance

| Event | Action |
|---|---|
| Deploy key compromise suspected | Regenerate on Mac, replace the line in `/home/deploy/.ssh/authorized_keys`, update `DEPLOY_SSH_KEY` secret |
| Image retention filling up GHCR | GitHub Packages UI → Retention policy → Keep 30 most recent |
| ci-deploy.sh needs changes | Edit `platform/scripts/ci-deploy.sh` in repo, SSH to VM as ubuntu, `sudo cp` into place. (Auto-sync via the pipeline itself is a future enhancement.) |
| Add a required reviewer later | Environment settings → Required reviewers → add yourself. Still auto-runs build; blocks the deploy job until approval. |
| Branch protection later | Repo Settings → Branches → Add rule for `main` → Require PR + status checks |

---

## Architecture summary

```
 ┌─ Mac (admin) ────────────┐
 │  ~/.ssh/Sarthak-Betaque  │─── ssh ubuntu@VM ──► sudo, break-glass
 │  ~/.ssh/sales-platform-  │
 │    ci  (CI-only)         │
 └──────────┬───────────────┘
            │   add public to VM, private to GH Secret
            ▼
 ┌─ GitHub Actions ─────────┐      ┌─ Oracle VM (161.118.207.119) ──┐
 │                          │      │                                 │
 │  Environment: production │      │   user: deploy (docker only)    │
 │    - DEPLOY_SSH_KEY      │ ssh  │   authorized_keys:              │
 │    - DEPLOY_HOST/USER    │─────►│     restrict,command="ci-       │
 │    - DEPLOY_HOSTKEY      │      │       deploy.sh" <pubkey>       │
 │                          │      │                                 │
 │  deploy.yml:             │      │   /opt/sales-platform/          │
 │   build+push GHCR        │      │     .env (600, deploy)          │
 │   ssh deploy@host "deploy│      │     scripts/ci-deploy.sh        │
 │     sha-xxx"             │      │     docker-compose.prod.yml     │
 └──────────────────────────┘      │     .last-deploy.json           │
                                   │                                 │
                                   │   deploy ▶ docker pull GHCR     │
                                   │           alembic upgrade       │
                                   │           compose up -d         │
                                   │           healthcheck +         │
                                   │           auto-rollback         │
                                   └─────────────────────────────────┘
```

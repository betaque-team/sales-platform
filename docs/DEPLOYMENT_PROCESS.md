# Deployment Process & Security Model

**Audience:** anyone shipping code to production.

This is the day-2 runbook. For first-time GH setup see [`DEPLOY_SETUP.md`](DEPLOY_SETUP.md). For VM bootstrap see [`../platform/DEPLOY.md`](../platform/DEPLOY.md).

---

## TL;DR

```
git push origin main
        │
        ▼
GitHub Actions
  CI      (tests + build)   ~2 min
  Deploy  (2-min wait)       ─┐
          build arm64 images ─┤ ~5 min (warm cache: ~3 min)
          push to GHCR       ─┘
          SSH → VM
                  │
                  ▼
        VM (ci-deploy.sh):
          pre-deploy pg_dump
          docker pull
          alembic upgrade head
          rolling restart (backend → workers → frontend → nginx)
          health-check (auto-rollback on fail)
          write .last-deploy.json
          keep last 3 image tags
                                ~60 sec

Total: ~8 min cold, ~5 min warm
Live at https://salesplatform.reventlabs.com
```

Rollback: `Actions → Rollback → Run workflow` with prior tag. **<30 sec.**

---

## Architecture

```
┌─ Dev machine ────┐         ┌─ GitHub ──────────────┐         ┌─ Oracle VM (ARM64) ────┐
│                  │  git    │  main branch          │         │  user: deploy          │
│  feature branch  │  push   │   │                   │         │   • docker group only  │
│       │          │────────►│   │                   │         │   • no sudo            │
│   PR → main      │         │   ▼ on push           │         │   • forced-command SSH │
└──────────────────┘         │  CI   (gates merge)   │         │                        │
                             │  Deploy               │         │  /opt/sales-platform/  │
                             │   │                   │         │    .env (600, deploy)  │
                             │   ▼ builds arm64      │         │    scripts/            │
                             │  GHCR packages        │         │      ci-deploy.sh      │
                             │   │                   │         │    docker-compose      │
                             │   ▼ SSH + stdin-token │         │      .prod.yml         │
                             └───┼───────────────────┘         │    .last-deploy.json   │
                                 │  port 22 only               │                        │
                                 └────────────────────────────►│  cloudflared (out)     │
                                                               │   │                    │
                                                               └───┼────────────────────┘
                                                                   │ outbound tunnel
                                                                   ▼
                                                 ┌─── Cloudflare Edge ───┐
                                                 │ salesplatform.        │
                                                 │   reventlabs.com      │
                                                 └───────────────────────┘
```

**Why this shape:**
- **Zero inbound 80/443** on the VM — public traffic enters via outbound Cloudflare Tunnel. ufw blocks everything except 22.
- **Forced-command SSH** — even with a stolen deploy key, an attacker can only run `deploy <tag> | rollback <tag> | status`. No shell, no file read, no lateral movement.
- **Short-lived GHCR auth** — `GITHUB_TOKEN` is piped over SSH stdin each deploy; the VM `docker login`s, pulls, then `docker logout`s. No persistent registry creds on disk.
- **arm64 images** — VM is Oracle Ampere A1 (aarch64); CI builds native arm64 via QEMU on x86 runners.

---

## Security Model

### Threats and controls

| Threat | Blast radius | Control |
|---|---|---|
| Deploy SSH key stolen from GH Secrets | Attacker can deploy any valid `sha-*` tag that exists in GHCR | `restrict,command=` in `authorized_keys` → no shell. `validate_tag` regex blocks injection. `deploy` user has no sudo; can't read `/root` or system files. |
| GH account of a committer compromised | Malicious code auto-deploys | 2-min wait timer on `production` environment (cancel window). `GITHUB_TOKEN` expires at run end. Auto-rollback on health failure. |
| GHCR registry compromise | Poisoned image pulled to VM | `GITHUB_TOKEN` is per-run, never persisted. Future: cosign image signing + VM-side verify. |
| Malicious PR author via fork | Builds arbitrary code | PR workflow runs without `packages: write` or `DEPLOY_SSH_KEY` access. Fork PRs can't mint GHCR pushes or SSH. |
| `.env` exfiltration via VM compromise | JWT_SECRET / DB password / ANTHROPIC_API_KEY leak | `.env` mode 640, owned `deploy:deploy` (ubuntu user can't read it). Offsite encrypted backup in 1Password. Never in repo/logs. |
| Migration or code bug reaches prod | Downtime, data loss | Pre-deploy `pg_dump | gzip` (retained 14 days). Migration failure = no swap. Backend healthcheck failure = auto-rollback. |
| SSH brute-force | Account lockout / log flood | `fail2ban` (systemd-journal backend, 4 tries / 10m → 1h ban). PasswordAuth disabled. |
| Secret leak to CI logs | Credentials in public run logs | GH Actions auto-masks registered secrets. Workflow never `echo`s env values. Commits verify no `grep .env` / `cat .env` in any step. |

### Standing invariants

Re-verify these quarterly (script in `scripts/security-audit.sh` TBD):

```
VM (ssh ubuntu@...):
  id deploy                              # uid/gid, groups: docker ONLY
  sudo cat /home/deploy/.ssh/authorized_keys   # starts with "restrict,command="
  stat -c '%a %U:%G' /opt/sales-platform/.env   # 640 deploy:deploy
  stat -c '%a %U:%G' /opt/sales-platform/cloudflared/credentials.json  # 600 deploy:deploy
  sudo ufw status                        # 22/tcp only, deny incoming default
  sudo ss -tlnp | grep LISTEN            # 22 only on non-loopback
  systemctl is-active fail2ban           # active
  sudo fail2ban-client status sshd       # shows sshd jail active

GitHub (browser):
  Settings → Environments → production   # wait timer present, secrets scoped
  Settings → Actions → Workflow permissions → Read-only for GITHUB_TOKEN (default)
  Packages tab → sales-platform/{backend,frontend} visibility as intended
```

---

## Normal Deploy Flow

### What triggers a deploy

Any `git push origin main` — either direct or via PR merge.

Deploy is **auto** with a 2-min wait timer. To cancel: **Actions → Deploy → (running run) → Cancel workflow** within the first 2 min.

### Step-by-step

1. **CI runs in parallel** (`ci.yml`):
   - Backend: postgres service → `alembic upgrade head` → `pytest tests/`
   - Frontend: `npx tsc --noEmit` → `npm run build`
   - Both must pass for the merge. (Not a hard gate on deploy — but failing CI visibly flags bad commits.)

2. **Deploy waits 2 min** (`environment: production` with wait timer).

3. **Build job** (runs on `ubuntu-latest` x86_64):
   - Computes `TAG=sha-<short>` or uses `workflow_dispatch` input.
   - `docker/setup-qemu-action@v3` + `docker/setup-buildx-action@v3` → arm64 emulation.
   - `docker/login-action@v3` with `GITHUB_TOKEN` (auto-minted, expires at job end).
   - `docker/build-push-action@v5` x2 with `platforms: linux/arm64`, pushes to `ghcr.io/betaque-team/sales-platform/{backend,frontend}:<tag>` + `:latest`.
   - Caches via `type=gha,scope=backend|frontend`.

4. **Deploy job** (SSH to VM):
   - `actions/checkout@v4` → install `DEPLOY_SSH_KEY` to `~/.ssh/deploy_key` (mode 600).
   - Pin host key from `DEPLOY_HOSTKEY` secret (prevents MITM).
   - Pipe `GITHUB_TOKEN` to VM stdin via:
     ```
     printf '%s\n' "$GH_TOKEN" | ssh -i ~/.ssh/deploy_key deploy@host "deploy <tag> <actor>"
     ```
   - The VM's `authorized_keys` has `command="/opt/sales-platform/scripts/ci-deploy.sh"` → the script ignores the SSH command string; it reads `$SSH_ORIGINAL_COMMAND` and parses only `deploy | rollback | status`.
   - `ssh` also fetches `status` for the Actions summary.

5. **`ci-deploy.sh` on VM** (full pipeline):
   ```
   validate_tag              (regex ^[a-zA-Z0-9_.-]+$, ≤64 chars)
   validate_ghcr_user        (^[a-zA-Z0-9-]{1,39}$)
   ghcr_login_from_stdin     (reads token from stdin w/ 10s timeout; --password-stdin)
   pre_deploy_backup         (docker compose exec postgres pg_dump | gzip → backups/)
   docker pull               (fails fast if tag missing)
   docker tag                (retag to platform-{backend,frontend}:<tag>)
   set_release_tag           (idempotent sed on .env to set RELEASE_TAG=<tag>)
   alembic upgrade head      (one-shot backend container; fails → rollback tag in .env)
   docker compose up -d --no-deps backend
   wait_for_healthy backend 90s    (else rollback)
   backend_http_check        (curl http://localhost:8000/api/v1/monitoring; expects 200 or 401)
   docker compose up -d --no-deps celery-worker celery-beat frontend
   docker compose up -d --no-deps --force-recreate nginx   (re-resolves upstream DNS)
   write .last-deploy.json   ({release, previous, deployed_at})
   image retention           (keep last 3 tags per repo, drop older)
   ghcr_logout               (docker logout ghcr.io → config.json = {auths:{}})
   ```

6. **Step Summary** in the Actions run shows tag, SHA, ref, URL, and status output.

### Timings (observed)

| Phase | Cold | Warm |
|---|---|---|
| Wait timer | 2:00 | 2:00 |
| Build backend (arm64 via QEMU) | 4:30 | 1:30 |
| Build frontend | 2:00 | 0:45 |
| Push to GHCR | 0:30 | 0:15 |
| SSH + deploy on VM | 1:00 | 0:40 |
| **Total** | **~10 min** | **~5 min** |

Backend build dominates — pip install on qemu is slow. Cache hits (unchanged `requirements.txt`) bring it down to ~1:30.

---

## Manual Deploy (workflow_dispatch)

Use when you want to deploy an arbitrary tag (e.g., re-deploy a known-good version after an out-of-band change):

1. **Actions → Deploy → Run workflow**
2. (optional) enter tag override, e.g. `sha-abc1234`. Blank = `sha-<current_HEAD>`.
3. Run.

This still goes through the 2-min wait and `production` environment scoping.

---

## Rollback

### App-only (99% of cases, <30 sec)

The app rollback swaps `RELEASE_TAG` in `.env` to a prior image and restarts containers. DB stays as-is.

1. **Actions → Rollback → Run workflow**
2. Enter `target_tag` — the tag to roll back *to*. Look it up:
   - `Actions → Deploy → (prior green run) → tag in summary`, or
   - SSH: `ssh ubuntu@... 'cat /opt/sales-platform/.last-deploy.json'` — `previous` field.
3. Run. Same SSH path; calls `ci-deploy.sh rollback <tag>`.
4. Verify: `curl -I https://salesplatform.reventlabs.com/api/v1/monitoring` should return `200` or `401`.

### DB restore (rare, destructive)

Only if a migration corrupted data. Rollback image first (above); then if data is still bad:

```bash
ssh ubuntu@161.118.207.119
cd /opt/sales-platform
ls -lh backups/pre-deploy-*.sql.gz          # find the right one
# stop writes
docker compose -f docker-compose.prod.yml stop backend celery-worker celery-beat
# restore
gunzip -c backups/pre-deploy-<tag>.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U postgres -d jobplatform
# resume
docker compose -f docker-compose.prod.yml up -d
```

**Data loss between the backup time and the restore is permanent.** Any writes committed after the pre-deploy snapshot are gone. If there's writable human data (pipeline entries, resume uploads) in that window, coordinate before restoring.

---

## Incident Response

### Deploy failed — now what?

First, identify which phase failed. Look at the Actions run summary; if inconclusive, `ssh ubuntu@... 'sudo tail -40 /opt/sales-platform/logs/ci-deploy.log'`.

| Failure | Symptom | Action |
|---|---|---|
| **GHCR login failed** | `ghcr login failed` in log | Check `GITHUB_TOKEN` permissions in `deploy.yml` (`packages: write`). Rare — GH-side issue. Re-run. |
| **`docker pull` failed** | `Failed to pull ghcr.io/...:<tag>` | Image not built or pushed. Check build job completed. If first deploy after renaming packages: verify `GHCR_IMAGE_BACKEND` env in `ci-deploy.sh` matches. |
| **Migration failed** | `Migration failed -- rolling back` | `.env` auto-reverts to prior tag; no container swap happened. Fix the migration in a PR, re-deploy. Prior version is still serving traffic. |
| **Backend unhealthy** | `Backend failed to report healthy -- rolling back` | Auto-rollback restarts backend on prior image. Check backend logs: `docker compose logs backend | tail -200`. |
| **502 after deploy** | `/` returns 502; `/api/...` works | nginx has stale upstream DNS. Fixed automatically by force-recreate step. If not, manually: `docker compose up -d --force-recreate nginx`. |
| **Deploy hangs** | Actions run stuck at "Trigger deploy on VM" | SSH timeout. Check VM up (ping 161.118.207.119). Cancel run; investigate VM. |

### Break-glass — bypass the pipeline

If the pipeline itself is broken (e.g. GH Actions down), deploy manually:

```bash
# On your Mac:
ssh ubuntu@161.118.207.119
cd /opt/sales-platform
sudo -u deploy docker login ghcr.io -u <your-gh-user>   # needs GHCR read
sudo -u deploy /opt/sales-platform/scripts/ci-deploy.sh
# Note: without SSH_ORIGINAL_COMMAND set, the script falls back to $@:
SSH_ORIGINAL_COMMAND="deploy sha-<short>" sudo -u deploy /opt/sales-platform/scripts/ci-deploy.sh
```

Admins use the `ubuntu` user (has sudo, keeps `Sarthak-Betaque` key). Never use `deploy`'s key for break-glass.

---

## Operational Tasks

### Rotating the deploy SSH key (every 90 days, or on suspected compromise)

```bash
# On Mac:
ssh-keygen -t ed25519 -f ~/.ssh/sales-platform-ci-new -C "github-ci-deploy-$(date +%Y%m)"
cat ~/.ssh/sales-platform-ci-new.pub
```

Then:
1. SSH as `ubuntu` to VM; append new pubkey to `/home/deploy/.ssh/authorized_keys` (with same `restrict,command=` prefix).
2. GitHub → `production` environment → update `DEPLOY_SSH_KEY` with contents of `~/.ssh/sales-platform-ci-new` (private half).
3. Trigger a deploy to verify the new key works.
4. Remove the **old** line from `/home/deploy/.ssh/authorized_keys` on VM.
5. Shred the old private key on Mac: `rm -P ~/.ssh/sales-platform-ci.old`.

### Rotating the host key pin

If you rebuild the VM or regenerate sshd host keys:

```bash
ssh-keyscan -t ed25519 161.118.207.119
```

Paste the full output (`|1|...|` prefix included) into the `DEPLOY_HOSTKEY` GH environment secret.

### Reviewing deploy history

```bash
ssh ubuntu@161.118.207.119 'sudo tail -100 /opt/sales-platform/logs/ci-deploy.log'
# or per-deploy breadcrumbs:
ssh ubuntu@161.118.207.119 'cat /opt/sales-platform/.last-deploy.json'
```

Every deploy writes one line to `.last-deploy.json`: release, previous, timestamp. Keeps a single-entry audit trail of the *current* state; for history, use the log file.

### Verifying fail2ban

```bash
ssh ubuntu@161.118.207.119 'sudo fail2ban-client status sshd'
# Shows: Currently failed / Total failed / Currently banned / Total banned / Banned IP list
```

### Image cleanup (if VM disk fills)

Retention is automatic (last 3 tags per repo). To force a deeper clean:

```bash
ssh ubuntu@161.118.207.119
sudo -u deploy docker image prune -a -f       # rmi untagged + unused
sudo -u deploy docker system prune -f         # also stopped containers, unused volumes
```

---

## Change History

| Date | Change | PR/Commit |
|---|---|---|
| 2026-04-15 | Initial pipeline: forced-command SSH, GHCR stdin-token auth, arm64 via QEMU | `5ce5d0b`..`2ab8d37` |
| 2026-04-15 | Security hardening: fail2ban, rpcbind off, cloudflared 600, backup rotation, image retention | (this commit) |

---

## Pending (optional) hardening

These are low-priority but worth the eventual flip:

- **`PermitRootLogin no`** in `/etc/ssh/sshd_config.d/50-cloud-init.conf` (currently `without-password`, i.e. key-only, which is already safe; but hard-disable is stronger). Requires SSH restart — do during a maintenance window.
- **`from=` IP allowlist** on `/home/deploy/.ssh/authorized_keys` — restrict to GitHub Actions ranges (`https://api.github.com/meta`, `actions` key). Needs a monthly cron to refresh. The forced-command already bounds what a stolen key can do, so this is defense-in-depth.
- **Branch protection on `main`** — currently direct-push allowed. Switch to required-PR + review once team grows past solo dev.
- **Cosign image signing** — sign images in CI, verify on VM before swap. Guards against GHCR compromise.
- **Slack/Discord deploy webhook** — post success/failure to a channel. Quality-of-life, not security.

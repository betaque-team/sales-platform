# VM Ops — approval-gated ad-hoc scripts via GitHub Actions

This replaces the "SSH into the VM and run things" workflow. Nobody except
the original admin ever needs the deploy key — all ops now go through a
dispatchable GitHub Actions workflow that requires explicit approval and is
restricted to `main`.

---

## How it works

```
you (GitHub UI)
  │ click "Run workflow" on VM Ops → pick action, give reason
  │
  ▼
.github/workflows/vm-ops.yml  (environment: production-ops)
  │ blocks until an approver in production-ops approves
  │
  ▼
runs on ubuntu-latest:
  1. Checks out repo (for the canonical vm-ops.sh source)
  2. Loads deploy key from secrets into ~/.ssh/deploy_key (600)
  3. Pipes platform/scripts/vm-ops.sh over SSH → ci-deploy.sh `install-script vm-ops`
     → atomically writes /opt/sales-platform/scripts/vm-ops.sh on the VM
  4. Issues `ops <action>` → ci-deploy.sh `action_ops` → exec's vm-ops.sh
  5. Streams stdout back, writes to step summary
  6. `if: always()` wipes ~/.ssh and ~/.docker on the runner
```

**The deploy key cannot get a shell.** The VM's `authorized_keys` pins the
key to `command="/opt/sales-platform/scripts/ci-deploy.sh"`, which only
accepts: `deploy`, `rollback`, `status`, `install-script vm-ops`, `ops <allowlisted action>`.

---

## One-time setup (in GitHub repo settings)

### 1. Create the `production-ops` environment

`Settings → Environments → New environment → production-ops`

Configure:

| Setting | Value |
|---|---|
| **Required reviewers** | Add yourself (and any trusted teammate). The workflow pauses for your click. |
| **Wait timer** | 0 (optional; can set a cool-off window) |
| **Deployment branches and tags** | "Selected branches and tags" → add rule for `main` only |

That last one is the hard lock: even someone with `workflow_dispatch` write
access can't point the workflow at a feature branch to run modified code.

### 2. (Already done) Environment secrets — inherited from `production`

The workflow reads `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_HOSTKEY`
the same way `deploy.yml` does. If you use environment-scoped secrets, copy
them into `production-ops` too (GitHub environments don't inherit each other).

### 3. Apply branch protection to `main`

```bash
./platform/scripts/setup-branch-protection.sh --show   # preview
./platform/scripts/setup-branch-protection.sh          # apply
```

Requires `gh` authenticated as a repo admin. Applies:

- 1 required approving PR review (stale approvals dismissed on new commits)
- Required passing status checks: `Backend tests`, `Frontend build`
- Branch must be up-to-date with `main` before merging (`strict: true`)
- Linear history (no merge commits — squash/rebase only)
- No force-pushes, no deletions
- Required conversation resolution
- Admins also enforced (`enforce_admins: true`)

Re-run anytime to reset to the known-good state.

---

## Running an action

1. Go to **Actions → VM Ops → Run workflow**
2. Pick a branch: `main` (the only option once branch policy is set)
3. Pick an action from the dropdown
4. Fill in **reason** (shows up in the step summary for audit)
5. Click **Run workflow**
6. The run pauses with "Waiting for approval". An approver clicks **Review deployments → Approve and deploy**
7. The run completes, output is in the **Summary** tab

---

## Available actions

All actions run as the `deploy` user on the VM (docker group, no sudo).

| Action | What it does | Destructive? |
|---|---|---|
| `health` | One-screen green/red summary: containers, host-metrics freshness, keepalive, cloudflared, disk, current release tag. Exits non-zero if anything is red. | no (read-only) |
| `audit` | Full state dump: OS info, docker stats per container, host-metrics snapshot, keepalive journal, cloudflared state, disk usage, crontab, last deploy, container log sizes. Intended for human reading. | no (read-only) |
| `restart-backend` | `docker compose up -d --force-recreate --no-deps backend`, then waits up to 60s for healthy. Picks up env/compose-override changes. | yes — ~20s backend downtime |
| `restart-all` | Rolling force-recreate of backend, celery-worker, celery-beat, frontend, nginx. Postgres and redis are left alone. | yes — brief blip |
| `docker-prune` | Prunes dangling images + stopped containers. Volumes intentionally NOT pruned (postgres data lives there). | yes (removes unused images) |
| `tail-deploy-log` | Last 200 lines of `/opt/sales-platform/logs/ci-deploy.log`. | no |
| `show-crontab` | `crontab -l` for the deploy user. | no |

---

## Adding a new action

1. Edit `platform/scripts/vm-ops.sh`: add a `do_<name>()` function and a case branch in the dispatch at the bottom.
2. Edit `.github/workflows/vm-ops.yml`: add the action name to both the `type: choice` `options:` list and the validation case.
3. PR it. After merge, the next run will sync the new script to the VM automatically (via `install-script vm-ops`).

**Do not** add actions that require sudo. The deploy user doesn't have it, and
shouldn't — see `VM_MONITORING.md` for anything that needs root access
(crontab for root, daemon.json, systemd units). Those stay manual; audit
them via the `audit` action but change them by hand.

---

## Why not just give people SSH keys?

- Deploy keys have blast radius: once copied out they can't be reliably rotated.
- SSH auth lacks an approval step — you click, it happens.
- With this workflow: every action has an actor, a reason, a timestamp, and an approver logged in GH. Audit trail is free.
- Runs on main only, so a malicious PR can't add a new action and ship it.

---

## Troubleshooting

### "Waiting for approval" forever

You haven't configured the `production-ops` environment yet, or no reviewer is
set. See one-time setup above.

### "Run action" step fails with `ops: ... not installed`

The `install-script` step above it probably failed. Check the SSH key
secret (`DEPLOY_SSH_KEY`) is present in the environment, and that the
forced-command on the VM (`authorized_keys`) points at
`/opt/sales-platform/scripts/ci-deploy.sh`. Run `action=status` as a smoke
test — that doesn't need vm-ops.sh to be installed.

### Action runs but output is truncated in the Summary

The step summary caps at 60 KB. For long `audit` runs, expand the job log
(stdout is in there verbatim, un-truncated).

### I need to run something not in the allowlist

Don't widen the allowlist for a one-off. SSH in as the admin user the old
way, do the thing, and if it's worth keeping, PR a new action.

---

## Design rationale

- **Self-syncing script**: piping `vm-ops.sh` over stdin on every run means
  there's no drift between what's on main and what actually runs. No cron,
  no separate deploy. The canonical copy lives in the repo.
- **Forced-command SSH**: the deploy key can only run `ci-deploy.sh`'s five
  allowed actions (deploy, rollback, status, install-script, ops). A
  stolen key can't pop a shell or read `.env`.
- **Two-layer allowlist**: `ci-deploy.sh` restricts which script names
  `install-script` will write (currently just `vm-ops`). `vm-ops.sh`
  restricts which actions are runnable. Both have to be widened to exfil.
- **Environment-scoped approval**: environment reviewers are separate from
  repo write access. Someone with push rights can't self-approve their own
  ops action.
- **Branch lock**: the environment's deployment-branch policy + the
  `if: github.ref == 'refs/heads/main'` guard on the job mean that even a
  typo or misconfigured reviewer can't run modified code against prod.
- **Explicit key cleanup**: runners are ephemeral but we shred `~/.ssh`
  and `~/.docker` in an `always()` step anyway — costs nothing, covers
  the case where GH changes runner lifecycle assumptions later.

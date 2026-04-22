# VM Monitoring — Oracle Always-Free Guardrails

Operator runbook for wiring up the VM host-level monitoring that feeds the
admin-only `/monitoring` page. This layer is what answers the two questions that
matter on a $0 tier:

1. **Is Oracle about to reclaim the VM?** (CPU idle → 7-day reclaim)
2. **Is anything about to cost us money?** (disk >200GB, egress >10TB/mo,
   containers crashing, tunnel down)

---

## Architecture

```
  VM host (Ubuntu 22.04)
  ├─ cron: * * * * *   collect-host-metrics.sh
  │                      │
  │                      └─ writes /opt/sales-platform/host-metrics/metrics.json (atomic)
  │
  └─ cron: 0 */6 * * *  keepalive.sh   (2 min CPU burst → stays above Oracle's 10% reclaim threshold)

  backend container
  └─ bind-mount: /opt/sales-platform/host-metrics → /host  (ro, dir)
      │   (so the JSON file is reachable inside as `/host/metrics.json`)
      │
      └─ app.services.host_stats.get_vm_metrics()
            │
            └─ GET /api/v1/monitoring/vm  (admin)
                  │
                  └─ <VmHealthPanel> on /monitoring
```

No psutil, no privileged mounts, no docker socket inside the backend — the
collector does all the work on the host and the backend is a plain file
reader.

---

## What's in the repo (already)

- `platform/infra/scripts/collect-host-metrics.sh` — host snapshot script (run by cron)
- `platform/infra/scripts/keepalive.sh` — CPU-burst anti-reclaim (run by cron)
- `platform/backend/app/services/host_stats.py` — JSON reader + guardrail evaluator
- `platform/backend/app/api/v1/monitoring.py` — `GET /monitoring/vm` endpoint
- `platform/frontend/src/components/VmHealthPanel.tsx` — admin UI panel
- `platform/docker-compose.prod.yml` — backend service has the bind-mount + `HOST_METRICS_PATH` env

---

## One-time install on the VM

Run these as the admin user on the VM (the one with sudo). Everything else in
the platform lives under `/opt/sales-platform/`, so keep scripts under
`/usr/local/bin/` so they aren't wiped by a git pull.

### 1. Install the collector

```bash
# from the repo on the VM (e.g. /opt/sales-platform)
sudo install -m 755 infra/scripts/collect-host-metrics.sh /usr/local/bin/

# Create the host-metrics directory the bind-mount targets. The collector
# now self-creates this on first run too, but pre-creating it lets the
# `docker compose up` below succeed even if collector cron lags by a few
# seconds.
sudo mkdir -p /opt/sales-platform/host-metrics

# first manual run — produces metrics.json inside the dir above
sudo /usr/local/bin/collect-host-metrics.sh

# verify
jq . /opt/sales-platform/host-metrics/metrics.json
```

You should see a single JSON object with `timestamp`, `cpu`, `memory`,
`disk`, `cloudflared`, `keepalive`, `containers`, etc.

### 2. Schedule the collector (every minute)

```bash
( sudo crontab -l 2>/dev/null | grep -v collect-host-metrics; \
  echo '* * * * * /usr/local/bin/collect-host-metrics.sh >/dev/null 2>&1' \
) | sudo crontab -

sudo crontab -l   # sanity-check
```

### 3. Schedule the keepalive (every 6h) — CRITICAL for $0

Oracle reclaims Always-Free VMs when the 7-day average CPU utilization is
below 10%. This cron forces a 2-minute CPU burst every 6h so we stay above
that line with ~1.4% duty cycle (well within free-tier).

```bash
# the script must be executable — this was the bug that broke prod once
sudo install -m 755 /opt/sales-platform/infra/scripts/keepalive.sh /opt/sales-platform/infra/scripts/keepalive.sh

( sudo crontab -l 2>/dev/null | grep -v keepalive.sh; \
  echo '0 */6 * * * /opt/sales-platform/infra/scripts/keepalive.sh' \
) | sudo crontab -

# manual smoke test (takes 120s)
sudo /opt/sales-platform/infra/scripts/keepalive.sh

# verify it logged
journalctl --since "5 minutes ago" | grep keepalive
```

You should see `keepalive: burst completed`. If you don't, fix it before
moving on — the monitoring panel will flag it as `critical` once installed,
but *you're still at reclaim risk* until the cron fires correctly.

### 4. Recreate the backend container to pick up the bind-mount

The bind-mount for `/host/metrics.json` was added to
`docker-compose.prod.yml`. Once the host JSON file exists (step 1), recreate:

```bash
cd /opt/sales-platform
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```

### 5. Verify the admin endpoint

From the VM (or through the tunnel):

```bash
# local
curl -s -u admin@... http://127.0.0.1:8000/api/v1/monitoring/vm | jq .

# via tunnel (needs admin JWT cookie)
curl -s --cookie "access_token=..." https://salesplatform.reventlabs.com/api/v1/monitoring/vm | jq .overall_status
```

Expected: `"available": true`, `"overall_status": "ok" | "warn" | "critical"`,
and a fully populated payload.

### 6. Visit `/monitoring` in the browser

Sign in as admin. You should see a new **VM Health · Oracle Always Free**
card with:

- Guardrail banner (green if all OK, amber/red otherwise)
- 4 usage bars (OCPUs, RAM, block storage, projected egress)
- Live stat tiles (CPU util, memory, disk, uptime)
- Cloudflare tunnel / keepalive / last-deploy cards
- Container list + per-interface network counters

The page polls `/monitoring/vm` every 30 seconds.

---

## What the guardrails actually check

`host_stats._evaluate_guardrails()` produces the banner. Each alert has a
severity (`critical`, `warn`, `info`) and the overall status is the max.

| Guardrail | Severity | Trigger |
|---|---|---|
| `keepalive` | critical | no `keepalive: burst completed` in journal in 13h (two missed runs) |
| `keepalive` | warn | > 7h since last run (one missed run) |
| `disk_free_tier` | critical | block storage used (sum of all mounts) > 95% of 200 GB cap |
| `disk_free_tier` | warn | block storage used (sum of all mounts) > 80% of 200 GB cap |
| `disk_fs` | critical | root filesystem > 95% full (separate from free-tier cap) |
| `mount:*` | critical / warn | any non-root mount > 95% / > 85% full |
| `inodes` | critical / warn | inode usage > 95% / > 80% (disk has space but no new files) |
| `oom_kills` | critical | kernel OOM killer fired in the last hour (memory pressure event) |
| `container_mem:*` | warn | any running container at ≥ 90% of its memory limit (OOM imminent) |
| `egress` | critical / warn | projected monthly tx > 95% / > 80% of 10 TB cap |
| `cloudflared` | critical | tunnel process not running (site unreachable) |
| `cloudflared_connections` | warn | tunnel has < 2 edge connections (HA pair expects 4) |
| `container:*` | critical | any container in a non-running state |
| `metrics_snapshot` | warn | snapshot file older than 5 min (cron failing) |

### What the panel surfaces beyond the banner

- **Per-container resources** (`docker stats`): live CPU%, mem% + raw usage ("465MiB / 1024MiB"), net I/O, block I/O, PID count per container.
- **Top 5 processes by CPU + top 5 by memory**: catches a runaway worker or a stuck cron. Also shows OOM-kill count if any.
- **Storage deep-dive**: inode bar, all mount points with per-mount fill %, and `/var/lib/docker` + backups + `/var/log` byte breakdown.

Egress projection assumes uniform traffic since boot — pessimistic during
traffic spikes, reasonable as a floor. After 30 days of uptime the projection
is very accurate.

---

## Troubleshooting

### Panel shows "VM metrics unavailable"

The backend can't read `/host/metrics.json`. Either:

- the collector hasn't run yet → run it manually (see step 1)
- the bind-mount isn't there → `docker compose -f docker-compose.prod.yml config | grep '/host'` should show `/opt/sales-platform/host-metrics:/host:ro`. If missing, the deployed `docker-compose.prod.yml` is older than the git copy — rsync the fresh one to `/opt/sales-platform/` and recreate the backend.
- The bind-mount is there but `/host` is empty → the host-metrics directory doesn't exist yet (or got removed). Fix: `sudo mkdir -p /opt/sales-platform/host-metrics && sudo /usr/local/bin/collect-host-metrics.sh` and confirm `metrics.json` lands inside.

### Keepalive guardrail is firing

```bash
# is the cron installed?
sudo crontab -l | grep keepalive

# is the script executable?
ls -la /opt/sales-platform/infra/scripts/keepalive.sh   # should be -rwxr-xr-x

# run it manually
sudo /opt/sales-platform/infra/scripts/keepalive.sh

# did it log?
journalctl --since "5 minutes ago" | grep keepalive
```

If the script runs but the collector can't detect it: the collector greps
`journalctl --since "24 hours ago"` for `keepalive: burst completed`. Make
sure your keepalive is using `logger -t keepalive` with that message.

### Container guardrail stays red for an exited container

Containers in `exited` state (including short-lived one-shot commands like
alembic migrations) will be flagged. Either prune them (`docker container prune`)
or add a filter. For now this is intentional — any non-running container in
prod is worth looking at.

### Cloudflared shows "running" but connections = null

The collector scrapes the Prometheus metrics endpoint at
`http://127.0.0.1:20241/metrics`. If cloudflared wasn't started with
`--metrics 127.0.0.1:20241`, the counters will be null. Check the systemd
unit file or the command it was launched with.

### Egress projection looks wrong

- Right after a reboot, uptime < 1h and the projection is suppressed (shown
  as `null`). Wait.
- `collect-host-metrics.sh` filters out `lo`, `docker0`, `veth*`, `br-*`. If
  you have another virtual interface, add it to the filter.

---

## Uninstall

```bash
# stop the cron jobs
sudo crontab -l | grep -v -e collect-host-metrics -e keepalive | sudo crontab -

# remove the collector binary
sudo rm /usr/local/bin/collect-host-metrics.sh

# remove the host metrics directory (file + parent)
sudo rm -rf /opt/sales-platform/host-metrics

# revert the compose bind-mount (edit docker-compose.prod.yml), then
docker compose -f docker-compose.prod.yml up -d --force-recreate backend
```

The `/monitoring/vm` endpoint will return `{"available": false, ...}` and the
panel will render a graceful "not available" card.

"""VM host metrics reader + free-tier guardrail evaluator.

The actual host snapshot is produced by `/usr/local/bin/collect-host-metrics.sh`
on the VM (cron, every 1 minute) and written to `/opt/sales-platform/host-metrics.json`.
That path is bind-mounted read-only into the backend container as
`/host/metrics.json` so this module can read it without any privileged mounts
or psutil.

If the file isn't present (e.g. local dev, CI), we return an empty-state
payload with `available: False` so the frontend can render a "Not available
in this environment" panel rather than crashing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HOST_METRICS_PATH = Path(os.environ.get("HOST_METRICS_PATH", "/host/metrics.json"))

# ── Oracle Cloud Always Free ceilings (per-tenancy, as of 2026-04) ─────────
# These are the limits we must stay under to keep $/month = 0.
FREE_TIER = {
    "max_ocpus": 4,                 # across all A1 Flex instances
    "max_memory_gb": 24,            # across all A1 Flex instances
    "max_disk_gb": 200,             # total block vol storage
    "max_egress_tb_month": 10,      # network egress per region
}

# Thresholds for guardrail severity.
_DISK_PCT_WARN = 80.0
_DISK_PCT_CRIT = 95.0
_EGRESS_PCT_WARN = 80.0
_EGRESS_PCT_CRIT = 95.0
_KEEPALIVE_AGE_WARN_SECONDS = 7 * 3600   # expected every 6h; 7h = missed run
_KEEPALIVE_AGE_CRIT_SECONDS = 13 * 3600  # two missed runs
_CONTAINER_HEALTHY_STATES = {"running"}


def _read_host_metrics() -> dict[str, Any]:
    """Read the JSON snapshot; return {} if unavailable / malformed."""
    if not _HOST_METRICS_PATH.exists():
        return {}
    try:
        return json.loads(_HOST_METRICS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _snapshot_age_seconds(snapshot: dict[str, Any]) -> int | None:
    ts = snapshot.get("timestamp")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except (ValueError, TypeError):
        return None


def _project_monthly_egress_bytes(
    tx_bytes: int, host_uptime_seconds: int
) -> int | None:
    """Very rough egress-per-month projection from lifetime-since-boot bytes.

    Assumes uniform traffic, which is pessimistic during promo spikes but
    useful as a floor. Returns None for uptime < 1h (too noisy).
    """
    if host_uptime_seconds < 3600:
        return None
    seconds_in_month = 30 * 24 * 3600
    return int(tx_bytes * (seconds_in_month / host_uptime_seconds))


def _evaluate_guardrails(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Produce the prioritized list of alerts for the top-of-page banner."""
    if not snapshot:
        return []

    alerts: list[dict[str, str]] = []

    # ── snapshot freshness ────────────────────────────────────────────────
    age = _snapshot_age_seconds(snapshot)
    if age is None:
        alerts.append({
            "name": "metrics_snapshot",
            "severity": "warn",
            "message": "Host-metrics snapshot has no timestamp — collector may be misconfigured.",
        })
    elif age > 300:
        alerts.append({
            "name": "metrics_snapshot",
            "severity": "warn",
            "message": f"Host-metrics snapshot is {age}s old — cron job may be failing.",
        })

    # ── keepalive (Oracle free-tier reclaim defense) ──────────────────────
    keepalive = snapshot.get("keepalive") or {}
    ka_seconds = keepalive.get("seconds_since")
    if ka_seconds is None:
        alerts.append({
            "name": "keepalive",
            "severity": "critical",
            "message": (
                "Keepalive cron has not run in the last 24h. Oracle will "
                "reclaim Always-Free VMs if 7-day CPU avg < 10%."
            ),
        })
    elif ka_seconds > _KEEPALIVE_AGE_CRIT_SECONDS:
        alerts.append({
            "name": "keepalive",
            "severity": "critical",
            "message": f"Keepalive last ran {ka_seconds // 3600}h ago (expected every 6h). VM reclaim risk.",
        })
    elif ka_seconds > _KEEPALIVE_AGE_WARN_SECONDS:
        alerts.append({
            "name": "keepalive",
            "severity": "warn",
            "message": f"Keepalive last ran {ka_seconds // 3600}h ago (expected every 6h). Check cron.",
        })

    # ── disk vs free-tier cap ─────────────────────────────────────────────
    disk = snapshot.get("disk") or {}
    total = disk.get("total_bytes") or 0
    used = disk.get("used_bytes") or 0
    if total:
        used_pct = used * 100 / total
        free_tier_pct = used * 100 / (FREE_TIER["max_disk_gb"] * 1024**3)
        if free_tier_pct >= _DISK_PCT_CRIT:
            alerts.append({
                "name": "disk_free_tier",
                "severity": "critical",
                "message": (
                    f"Disk usage is {free_tier_pct:.1f}% of the 200 GB free-tier cap. "
                    "Any additional block storage will be billed."
                ),
            })
        elif free_tier_pct >= _DISK_PCT_WARN:
            alerts.append({
                "name": "disk_free_tier",
                "severity": "warn",
                "message": f"Disk usage is {free_tier_pct:.1f}% of the 200 GB free-tier cap. Consider pruning backups/images.",
            })
        elif used_pct >= _DISK_PCT_CRIT:
            alerts.append({
                "name": "disk_fs",
                "severity": "critical",
                "message": f"Root filesystem is {used_pct:.1f}% full. Free up space or the VM will stop writing.",
            })

    # ── egress vs free-tier cap ───────────────────────────────────────────
    network = snapshot.get("network") or {}
    tx_bytes = network.get("total_tx_bytes") or 0
    host_uptime = snapshot.get("host_uptime_seconds") or 0
    projected_bytes = _project_monthly_egress_bytes(tx_bytes, host_uptime)
    if projected_bytes is not None:
        projected_tb = projected_bytes / 1024**4
        cap_tb = FREE_TIER["max_egress_tb_month"]
        pct = projected_tb * 100 / cap_tb
        if pct >= _EGRESS_PCT_CRIT:
            alerts.append({
                "name": "egress",
                "severity": "critical",
                "message": f"Projected monthly egress is {projected_tb:.2f} TB ({pct:.1f}% of 10 TB free tier). Overage will be billed.",
            })
        elif pct >= _EGRESS_PCT_WARN:
            alerts.append({
                "name": "egress",
                "severity": "warn",
                "message": f"Projected monthly egress is {projected_tb:.2f} TB ({pct:.1f}% of 10 TB free tier).",
            })

    # ── cloudflared tunnel ────────────────────────────────────────────────
    cloudflared = snapshot.get("cloudflared") or {}
    if not cloudflared.get("running"):
        alerts.append({
            "name": "cloudflared",
            "severity": "critical",
            "message": "Cloudflared tunnel is not running — site is unreachable via https://salesplatform.reventlabs.com.",
        })
    else:
        conns = cloudflared.get("connections")
        if conns is not None and conns < 2:
            alerts.append({
                "name": "cloudflared_connections",
                "severity": "warn",
                "message": f"Cloudflared has only {conns} edge connection(s); HA pair expects 4.",
            })

    # ── container health ──────────────────────────────────────────────────
    for c in snapshot.get("containers") or []:
        state = (c.get("state") or "").lower()
        if state and state not in _CONTAINER_HEALTHY_STATES:
            alerts.append({
                "name": f"container:{c.get('name', '?')}",
                "severity": "critical",
                "message": f"Container {c.get('name', '?')} is {state} — {c.get('status', '?')}",
            })

    return alerts


def get_vm_metrics() -> dict[str, Any]:
    """Assemble the VM-monitoring payload served by GET /monitoring/vm."""
    snapshot = _read_host_metrics()

    if not snapshot:
        return {
            "available": False,
            "reason": (
                f"host-metrics snapshot not present at {_HOST_METRICS_PATH}. "
                "Install collect-host-metrics.sh on the VM (see docs/VM_MONITORING.md)."
            ),
            "free_tier": FREE_TIER,
        }

    # Compute derived fields the frontend will use directly.
    disk = snapshot.get("disk") or {}
    disk_used_pct = (
        round((disk.get("used_bytes", 0) * 100) / disk["total_bytes"], 1)
        if disk.get("total_bytes") else 0.0
    )
    disk_free_tier_pct = (
        round((disk.get("used_bytes", 0) * 100) / (FREE_TIER["max_disk_gb"] * 1024**3), 1)
    )

    network = snapshot.get("network") or {}
    host_uptime = snapshot.get("host_uptime_seconds") or 0
    projected_egress = _project_monthly_egress_bytes(
        network.get("total_tx_bytes") or 0, host_uptime
    )
    projected_egress_tb = round(projected_egress / 1024**4, 3) if projected_egress else None
    egress_pct = (
        round((projected_egress_tb * 100) / FREE_TIER["max_egress_tb_month"], 1)
        if projected_egress_tb else None
    )

    guardrails = _evaluate_guardrails(snapshot)
    severity_order = {"critical": 0, "warn": 1, "info": 2}
    guardrails.sort(key=lambda a: severity_order.get(a["severity"], 99))

    critical_count = sum(1 for a in guardrails if a["severity"] == "critical")
    warn_count = sum(1 for a in guardrails if a["severity"] == "warn")
    if critical_count:
        overall_status = "critical"
    elif warn_count:
        overall_status = "warn"
    else:
        overall_status = "ok"

    return {
        "available": True,
        "overall_status": overall_status,
        "snapshot_age_seconds": _snapshot_age_seconds(snapshot),
        "timestamp": snapshot.get("timestamp"),
        "host_uptime_seconds": host_uptime,
        "cpu": snapshot.get("cpu") or {},
        "memory": snapshot.get("memory") or {},
        "network": {
            **network,
            "projected_monthly_egress_tb": projected_egress_tb,
            "projected_egress_pct_of_free_tier": egress_pct,
        },
        "disk": {
            **disk,
            "used_percent": disk_used_pct,
            "free_tier_used_percent": disk_free_tier_pct,
        },
        "cloudflared": snapshot.get("cloudflared") or {},
        "keepalive": snapshot.get("keepalive") or {},
        "containers": snapshot.get("containers") or [],
        "last_deploy": snapshot.get("last_deploy"),
        "backups": snapshot.get("backups") or {},
        "free_tier": FREE_TIER,
        "guardrails": guardrails,
        "guardrail_counts": {
            "critical": critical_count,
            "warn": warn_count,
        },
    }

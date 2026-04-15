#!/bin/bash
# =============================================================================
# keepalive.sh — Prevents Oracle Cloud free-tier instance reclaim
#
# Oracle reclaims Always Free instances with <10% avg CPU over 7 days.
# This script generates a short CPU burst (2 min) every 6 hours.
# Installed automatically by cloud-init via cron: 0 */6 * * *
#
# Total CPU impact: 2min/6h = ~0.5% duty cycle (negligible)
# But spikes the average above the 10% threshold when sampled.
# =============================================================================
set -euo pipefail

logger "keepalive: starting CPU burst"

# Run CPU-intensive work for 2 minutes across 2 threads
timeout 120 sh -c '
  for i in 1 2; do
    (while true; do echo "keepalive-$i" | md5sum > /dev/null; done) &
  done
  wait
' 2>/dev/null || true

logger "keepalive: burst completed"

#!/usr/bin/env bash
# =============================================================================
# collect-host-metrics.sh — snapshot host metrics into a JSON file that the
# backend container reads via a read-only bind mount.
#
# Runs on the VM host every 1 min via cron. All metrics live in one place so
# the backend doesn't need any privileged mounts or psutil dependencies.
#
# Install (one-time, on the VM — see docs/VM_MONITORING.md):
#   sudo install -m 755 collect-host-metrics.sh /usr/local/bin/
#   ( sudo crontab -l 2>/dev/null; \
#     echo '* * * * * /usr/local/bin/collect-host-metrics.sh >/dev/null 2>&1' \
#   ) | sudo crontab -
#
# Output (world-readable, atomic-replace):
#   /opt/sales-platform/host-metrics.json
#
# Needs: jq, curl, docker CLI, journalctl. All standard on Ubuntu 22.04.
# =============================================================================
set -uo pipefail

OUT="/opt/sales-platform/host-metrics.json"
TMP="${OUT}.tmp.$$"
APP_ROOT="/opt/sales-platform"
BACKUPS_DIR="${APP_ROOT}/backups"
CLOUDFLARED_METRICS_URL="http://127.0.0.1:20241/metrics"

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

json_str_or_null() {
  local v="$1"
  if [[ -z "$v" ]]; then echo "null"; else printf '"%s"' "$v"; fi
}

# ── CPU ──────────────────────────────────────────────────────────────────────
cpu_cores=$(nproc)
read -r load1 load5 load15 _ < /proc/loadavg

# CPU % — sample /proc/stat twice with a 500ms gap, compute delta.
read_cpu_times() {
  awk '/^cpu / {
    idle=$5+$6
    total=0; for (i=2; i<=NF; i++) total+=$i
    print total, idle
  }' /proc/stat
}
t1_total=$(read_cpu_times | awk '{print $1}')
t1_idle=$(read_cpu_times  | awk '{print $2}')
sleep 0.5
t2_total=$(read_cpu_times | awk '{print $1}')
t2_idle=$(read_cpu_times  | awk '{print $2}')
dt=$(( t2_total - t1_total ))
di=$(( t2_idle  - t1_idle  ))
if (( dt > 0 )); then
  cpu_percent=$(awk -v dt="$dt" -v di="$di" 'BEGIN {printf "%.1f", (dt-di)*100/dt}')
else
  cpu_percent="0.0"
fi

# ── Memory ───────────────────────────────────────────────────────────────────
mem_total=$(awk '/^MemTotal:/ {print $2*1024}' /proc/meminfo)
mem_avail=$(awk '/^MemAvailable:/ {print $2*1024}' /proc/meminfo)
mem_free=$(awk  '/^MemFree:/  {print $2*1024}' /proc/meminfo)
swap_total=$(awk '/^SwapTotal:/ {print $2*1024}' /proc/meminfo)
swap_free=$(awk  '/^SwapFree:/  {print $2*1024}' /proc/meminfo)
mem_used=$(( mem_total - mem_avail ))
swap_used=$(( swap_total - swap_free ))
mem_used_pct=$(awk -v u="$mem_used" -v t="$mem_total" 'BEGIN {printf "%.1f", (t>0?u*100/t:0)}')

# ── Host uptime ──────────────────────────────────────────────────────────────
uptime_seconds=$(awk '{printf "%d", $1}' /proc/uptime)

# ── Network (per-interface bytes, filtering virtual) ─────────────────────────
interfaces_json="[]"
total_rx=0; total_tx=0
tmp_if=$(mktemp)
trap 'rm -f "$tmp_if"' EXIT
for iface_path in /sys/class/net/*; do
  iface=$(basename "$iface_path")
  case "$iface" in
    lo|docker0|veth*|br-*) continue ;;
  esac
  rx=$(cat "$iface_path/statistics/rx_bytes" 2>/dev/null || echo 0)
  tx=$(cat "$iface_path/statistics/tx_bytes" 2>/dev/null || echo 0)
  total_rx=$(( total_rx + rx ))
  total_tx=$(( total_tx + tx ))
  printf '{"name":"%s","rx_bytes":%s,"tx_bytes":%s}\n' "$iface" "$rx" "$tx" >> "$tmp_if"
done
if [[ -s "$tmp_if" ]]; then
  interfaces_json=$(jq -s '.' "$tmp_if" 2>/dev/null || echo "[]")
fi

# ── Disk (root fs) ───────────────────────────────────────────────────────────
df_root=$(df -B1 / 2>/dev/null | awk 'NR==2 {print $2","$3","$4}')
disk_total="${df_root%%,*}"; rest="${df_root#*,}"
disk_used="${rest%%,*}";     disk_avail="${rest#*,}"
disk_total="${disk_total:-0}"; disk_used="${disk_used:-0}"; disk_avail="${disk_avail:-0}"

# Inode usage on root — rare but deadly (disk shows free space but no new files)
inode_line=$(df -i / 2>/dev/null | awk 'NR==2 {print $2","$3","$5}')
inode_total="${inode_line%%,*}"; rest="${inode_line#*,}"
inode_used="${rest%%,*}";        inode_used_pct_raw="${rest#*,}"
inode_total="${inode_total:-0}"; inode_used="${inode_used:-0}"
inode_used_pct="${inode_used_pct_raw%%%*}"   # strip trailing %
inode_used_pct="${inode_used_pct:-0}"

# All non-virtual mounts (for free-tier cap tracking across any attached
# block volumes). Filters tmpfs/devtmpfs/overlay/squashfs so we only see
# real storage that counts against the 200 GB Oracle Always-Free cap.
mounts_tmp=$(mktemp); trap 'rm -f "$mounts_tmp" "${tmp_if:-}"' EXIT
df -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs -x none 2>/dev/null \
  | awk 'NR>1 && NF>=6 {
      used_pct=$5; gsub(/%/, "", used_pct);
      printf "{\"mount\":\"%s\",\"total_bytes\":%s,\"used_bytes\":%s,\"available_bytes\":%s,\"used_percent\":%s}\n", $6,$2,$3,$4,used_pct
    }' > "$mounts_tmp"
mounts_json="[]"
[[ -s "$mounts_tmp" ]] && mounts_json=$(jq -s '.' "$mounts_tmp" 2>/dev/null || echo "[]")

# Disk breakdown (time-bounded — du can be slow on huge trees).
# Returns bare int (bytes) or literal `null` safe for JSON.
path_size_bytes() {
  local p="$1"
  if [[ -d "$p" ]]; then
    local v
    v=$(timeout 10 du -sb "$p" 2>/dev/null | awk '{print $1}')
    [[ -n "$v" ]] && echo "$v" || echo "null"
  else
    echo "null"
  fi
}
du_docker=$(path_size_bytes /var/lib/docker)
du_backups=$(path_size_bytes "${BACKUPS_DIR}")
du_logs=$(path_size_bytes /var/log)

# ── Cloudflared ──────────────────────────────────────────────────────────────
cf_pid=$(pgrep -x cloudflared 2>/dev/null | head -1 || true)
cf_running="false"
cf_conns="null"
cf_uptime_seconds="null"
cf_pid_json="null"
if [[ -n "$cf_pid" ]]; then
  cf_running="true"
  cf_pid_json="$cf_pid"
  cf_start=$(ps -o lstart= -p "$cf_pid" 2>/dev/null | xargs -I{} date -d "{}" +%s 2>/dev/null || echo "")
  if [[ -n "$cf_start" ]]; then
    cf_uptime_seconds=$(( $(date +%s) - cf_start ))
  fi
  metrics=$(curl -sf --max-time 2 "$CLOUDFLARED_METRICS_URL" 2>/dev/null || true)
  if [[ -n "$metrics" ]]; then
    parsed=$(echo "$metrics" | awk '/^cloudflared_tunnel_ha_connections[ {]/ {sum+=$NF} END {print sum+0}' 2>/dev/null || echo "")
    [[ -n "$parsed" ]] && cf_conns="$parsed"
  fi
fi

# ── Keepalive (parsed from journalctl) ───────────────────────────────────────
last_keepalive_epoch=""
if command -v journalctl >/dev/null 2>&1; then
  last_keepalive_epoch=$(journalctl --no-pager --since "24 hours ago" 2>/dev/null \
    | grep -F "keepalive: burst completed" \
    | tail -1 \
    | awk '{print $1" "$2" "$3}' \
    | xargs -I{} date -d "{}" +%s 2>/dev/null || echo "")
fi
keepalive_seconds_since="null"
keepalive_last_json="null"
if [[ -n "$last_keepalive_epoch" ]]; then
  keepalive_seconds_since=$(( $(date +%s) - last_keepalive_epoch ))
  keepalive_last_json=$(json_str_or_null "$(date -u -d "@${last_keepalive_epoch}" +"%Y-%m-%dT%H:%M:%SZ")")
fi

# ── Containers (docker ps) ───────────────────────────────────────────────────
containers_json="[]"
if command -v docker >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  containers_json=$(docker ps -a --format '{{json .}}' 2>/dev/null \
    | jq -s 'map({
        name: .Names,
        image: .Image,
        state: .State,
        status: .Status,
        started_at: .CreatedAt
      })' 2>/dev/null || echo "[]")
fi

# ── Per-container resources (docker stats) ───────────────────────────────────
# docker stats --no-stream takes a single snapshot; shows running containers
# only. Raw values are strings like "123MiB / 1GiB"; backend parses them.
# timeout 10 guards against docker daemon hangs (would otherwise stall cron).
container_stats_json="[]"
if command -v docker >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  ds_raw=$(timeout 10 docker stats --no-stream --format '{{json .}}' 2>/dev/null || true)
  if [[ -n "$ds_raw" ]]; then
    container_stats_json=$(echo "$ds_raw" | jq -s 'map({
        name: .Name,
        cpu_percent: ((.CPUPerc | rtrimstr("%") | tonumber?) // 0),
        memory_percent: ((.MemPerc | rtrimstr("%") | tonumber?) // 0),
        memory_usage: .MemUsage,
        net_io: .NetIO,
        block_io: .BlockIO,
        pids: ((.PIDs | tonumber?) // 0)
      })' 2>/dev/null || echo "[]")
  fi
fi

# ── Top processes by CPU + memory (5 hogs each) ─────────────────────────────
# Surfaces the "what's hot right now" view when something drifts. `ps comm=`
# prints just the executable basename; full cmdline is in /proc/<pid>/cmdline
# if you need more — kept short for UI.
build_top_procs() {
  local sort_key="$1"  # -pcpu or -pmem
  ps -eo pid,user,pcpu,pmem,comm --sort="$sort_key" --no-headers 2>/dev/null \
    | head -5 \
    | awk '{
        # escape backslashes + quotes in comm (column 5)
        cmd=$5; gsub(/\\/, "\\\\", cmd); gsub(/"/, "\\\"", cmd);
        printf "{\"pid\":%s,\"user\":\"%s\",\"cpu_percent\":%s,\"memory_percent\":%s,\"command\":\"%s\"}\n", $1, $2, $3, $4, cmd
      }' \
    | jq -s '.' 2>/dev/null || echo "[]"
}
top_cpu_json=$(build_top_procs -pcpu)
top_mem_json=$(build_top_procs -pmem)

# ── OOM kills in the last hour (journalctl kernel log) ───────────────────────
# Detects `oom-kill` or `Killed process <pid>` emitted by the Linux OOM killer.
# Zero on a healthy system; anything > 0 = memory pressure event worth a look.
oom_kills_1h=0
if command -v journalctl >/dev/null 2>&1; then
  oom_kills_1h=$(journalctl -k --since "1 hour ago" --no-pager 2>/dev/null \
    | grep -Eic "(killed process|oom-kill)" || echo 0)
  # guard against grep returning no-match exit code tainting the value
  [[ "$oom_kills_1h" =~ ^[0-9]+$ ]] || oom_kills_1h=0
fi

# ── Last deploy ──────────────────────────────────────────────────────────────
last_deploy_json="null"
if [[ -f "${APP_ROOT}/.last-deploy.json" ]]; then
  candidate=$(cat "${APP_ROOT}/.last-deploy.json" 2>/dev/null || echo "")
  if [[ -n "$candidate" ]] && echo "$candidate" | jq . >/dev/null 2>&1; then
    last_deploy_json="$candidate"
  fi
fi

# ── Backups ──────────────────────────────────────────────────────────────────
backup_count=0; backup_size=0
backup_newest_json="null"; backup_oldest_json="null"
if [[ -d "$BACKUPS_DIR" ]]; then
  backup_count=$(find "$BACKUPS_DIR" -maxdepth 2 -type f -name '*.sql.gz' 2>/dev/null | wc -l | tr -d ' ')
  backup_size=$(du -sb "$BACKUPS_DIR" 2>/dev/null | awk '{print $1}')
  : "${backup_size:=0}"
  newest_epoch=$(find "$BACKUPS_DIR" -maxdepth 2 -type f -name '*.sql.gz' -printf '%T@\n' 2>/dev/null | sort -rn | head -1 | cut -d. -f1)
  oldest_epoch=$(find "$BACKUPS_DIR" -maxdepth 2 -type f -name '*.sql.gz' -printf '%T@\n' 2>/dev/null | sort -n | head -1 | cut -d. -f1)
  [[ -n "$newest_epoch" ]] && backup_newest_json=$(json_str_or_null "$(date -u -d "@${newest_epoch}" +"%Y-%m-%dT%H:%M:%SZ")")
  [[ -n "$oldest_epoch" ]] && backup_oldest_json=$(json_str_or_null "$(date -u -d "@${oldest_epoch}" +"%Y-%m-%dT%H:%M:%SZ")")
fi

# ── Assemble ─────────────────────────────────────────────────────────────────
cat > "$TMP" <<EOF
{
  "timestamp": "$(now_iso)",
  "host_uptime_seconds": ${uptime_seconds},
  "cpu": {
    "cores": ${cpu_cores},
    "load_1m": ${load1},
    "load_5m": ${load5},
    "load_15m": ${load15},
    "utilization_percent": ${cpu_percent}
  },
  "memory": {
    "total_bytes": ${mem_total},
    "used_bytes": ${mem_used},
    "available_bytes": ${mem_avail},
    "used_percent": ${mem_used_pct},
    "swap_total_bytes": ${swap_total},
    "swap_used_bytes": ${swap_used}
  },
  "network": {
    "interfaces": ${interfaces_json},
    "total_rx_bytes": ${total_rx},
    "total_tx_bytes": ${total_tx}
  },
  "disk": {
    "mount": "/",
    "total_bytes": ${disk_total},
    "used_bytes": ${disk_used},
    "available_bytes": ${disk_avail},
    "inode_total": ${inode_total},
    "inode_used": ${inode_used},
    "inode_used_percent": ${inode_used_pct},
    "mounts": ${mounts_json},
    "breakdown": {
      "docker_bytes": ${du_docker},
      "backups_bytes": ${du_backups},
      "logs_bytes": ${du_logs}
    }
  },
  "container_stats": ${container_stats_json},
  "top_processes": {
    "by_cpu": ${top_cpu_json},
    "by_memory": ${top_mem_json}
  },
  "oom_kills_1h": ${oom_kills_1h},
  "cloudflared": {
    "running": ${cf_running},
    "pid": ${cf_pid_json},
    "uptime_seconds": ${cf_uptime_seconds},
    "connections": ${cf_conns}
  },
  "keepalive": {
    "last_run": ${keepalive_last_json},
    "seconds_since": ${keepalive_seconds_since}
  },
  "containers": ${containers_json},
  "last_deploy": ${last_deploy_json},
  "backups": {
    "count": ${backup_count},
    "total_size_bytes": ${backup_size},
    "newest": ${backup_newest_json},
    "oldest": ${backup_oldest_json}
  }
}
EOF

# Validate JSON; if broken, keep the previous file
if command -v jq >/dev/null 2>&1; then
  if ! jq . "$TMP" >/dev/null 2>&1; then
    echo "collect-host-metrics: produced invalid JSON, not replacing output" >&2
    rm -f "$TMP"
    exit 1
  fi
fi

mv "$TMP" "$OUT"
chmod 644 "$OUT"
exit 0

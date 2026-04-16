"""Shared SSRF defense-in-depth guard.

Regression finding 140 (CWE-918, severity:red): the alerts endpoint
accepted any `webhook_url` and the worker `httpx.post`-ed it from
inside the VPC. An admin-compromise + IMDS SSRF (`http://169.254.169.254/`)
on Oracle Cloud yields instance-role credentials → S3/EFS/full-cloud
takeover. This is the Capital One 2019 pattern.

The same primitive existed at `career_page_task.py` (F151) and was
fixed inline. This module centralizes the guard so future SSRF-prone
surfaces (alert webhooks, future scrapers, image-proxy endpoints,
oembed unfurlers, …) can pull one consistent implementation.

What this guards:
  1. Scheme — only http/https allowed (rejects file://, gopher://,
     ftp://, redis://, etc. that httpx may otherwise honor).
  2. Hostname is required (rejects `http:///path` and similar).
  3. Hostname must NOT resolve to any private/reserved IP range:
     RFC 1918 private, loopback, link-local (incl. AWS/Oracle IMDS),
     CGNAT, multicast, IPv6 ULA, IPv6 link-local.
  4. Literal IPv4-in-IPv6 addresses (`::ffff:127.0.0.1`) are unwrapped
     and re-checked against the v4 blocklist.
  5. DNS lookup uses `getaddrinfo` so BOTH A and AAAA records are
     considered. ANY resolved IP in the blocklist → reject (strictest
     interpretation, defeats split-result rebinding tricks).

What this does NOT guard:
  - DNS rebinding where the A record changes BETWEEN the validate call
    and the actual httpx.post. To close that, callers should re-resolve
    inside the request and refuse if the resolved IP isn't what was
    validated. For higher-stakes endpoints, route through an egress
    proxy (e.g., httpx.Client(proxies=…)) that does its own egress
    allowlist enforcement.
  - IPv6 unique-local that isn't `fc00::/7` (no such range exists, but
    new ones could be allocated; revisit if RFC changes).
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


# Private / reserved IP ranges that internal services live on. Any URL
# resolving to ANY of these is refused. Mirrors career_page_task.py's
# F151 list — keep in sync.
_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        # IPv4 private ranges (RFC 1918) + loopback + link-local + CGNAT
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",      # link-local incl. Oracle/AWS IMDS
        "100.64.0.0/10",       # CGNAT
        "0.0.0.0/8",           # "this network"
        "224.0.0.0/4",         # multicast
        "240.0.0.0/4",         # reserved / broadcast
        # IPv6 equivalents
        "::1/128",             # loopback
        "fc00::/7",            # unique local (RFC 4193)
        "fe80::/10",           # link-local
        "ff00::/8",            # multicast
        # IPv4-mapped / 4-in-6 — caught via dual lookup + ipv4_mapped
        # unwrap below.
    )
]


# Public, vetted webhook destinations whose hostnames we treat as
# implicitly safe so callers don't have to round-trip DNS for every
# Slack / Google Chat / Discord notification. Exact-match against the
# parsed hostname (no wildcards). Adding a new entry here is a
# deliberate decision — it bypasses DNS resolution and trusts the
# vendor not to suddenly point their webhook host at a private IP.
KNOWN_WEBHOOK_HOSTS = frozenset({
    "hooks.slack.com",
    "chat.googleapis.com",
    "discord.com",
    "discordapp.com",
    "outlook.office.com",
    "outlook.office365.com",
})


def _is_blocked_literal(addr: str) -> bool:
    """Return True if `addr` is a literal IP that falls in the
    blocklist (or is an IPv4-mapped IPv6 wrapping one).
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if any(ip in n for n in _BLOCKED_IP_NETWORKS):
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        if any(ip.ipv4_mapped in n for n in _BLOCKED_IP_NETWORKS):
            return True
    return False


def url_is_safe_for_egress(url: str) -> tuple[bool, str]:
    """Return (allowed, reason).

    `allowed=True` means the URL passes the SSRF guard and the caller
    may proceed with the HTTP request. `reason` is a short
    machine-friendly string suitable for log lines / error responses
    (NOT for end-user UI — those should get a generic "invalid URL"
    message to avoid leaking internal-network reconnaissance).

    Caller contract:
      - This is a defense-in-depth check. Callers should still wrap the
        actual httpx call in a tight timeout and not surface response
        body / status to the user, since an attacker who finds a
        bypass would otherwise get a leak channel.
      - On `allowed=False`, the caller should refuse the request with
        a generic 400 / 422 — NOT echo `reason` back to the client.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "url_parse_error"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, f"scheme_not_http_https:{scheme or 'empty'}"

    host = parsed.hostname
    if not host:
        return False, "missing_host"

    # Known providers — short-circuit DNS lookup. A vendor compromise
    # could in theory point one of these at a private IP, but that's
    # several orders of magnitude less likely than an attacker
    # supplying `127.0.0.1` directly. If paranoia warrants, remove
    # this fast-path and force every URL through the resolver below.
    if host.lower() in KNOWN_WEBHOOK_HOSTS:
        return True, "known_provider"

    # Literal IP given directly in the URL — check before DNS so we
    # catch `http://127.0.0.1/`, `http://[::1]/`, `http://[::ffff:127.0.0.1]/`.
    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        if _is_blocked_literal(host):
            return False, f"literal_ip_blocked:{host}"
        return True, "literal_ip_public"

    # DNS resolve — both A and AAAA. ANY resolved IP that's blocked
    # → refuse (defeats DNS rebinding tricks that mix public + private
    # records).
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # Unresolvable: don't let through. The actual httpx call would
        # fail anyway, but explicitly refusing here makes the intent
        # clear in audit logs.
        return False, f"dns_resolve_failed:{host}"

    for info in infos:
        sockaddr = info[4]
        raw = sockaddr[0]
        # IPv6 sockaddr may include `%scope` suffix — strip it.
        if "%" in raw:
            raw = raw.split("%", 1)[0]
        if _is_blocked_literal(raw):
            return False, f"resolved_ip_blocked:{host}->{raw}"

    return True, "dns_public"

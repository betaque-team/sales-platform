"""SMTP-based email verification -- completely free, no API keys.

Verifies whether an email address exists by performing SMTP handshake
without actually sending any mail.
"""

import logging
import random
import smtplib
import string

import dns.resolver

logger = logging.getLogger(__name__)

# Module-level cache for catch-all detection per domain.
# Persists within the Celery worker process lifetime.
_catch_all_cache: dict[str, bool] = {}


def _get_mx_host(domain: str) -> str | None:
    """Look up the highest-priority MX record for *domain*.

    Returns the MX hostname or None on failure.
    """
    try:
        answers = dns.resolver.resolve(domain, "MX")
        # Sort by priority (lower = higher priority)
        mx_records = sorted(answers, key=lambda r: r.preference)
        if mx_records:
            # MX record exchange value has a trailing dot
            return str(mx_records[0].exchange).rstrip(".")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers, dns.resolver.Timeout, Exception) as exc:
        logger.debug("MX lookup failed for %s: %s", domain, exc)
    return None


def _smtp_check(email: str, mx_host: str) -> int:
    """Perform SMTP RCPT TO check and return the response code.

    Returns the SMTP response code for RCPT TO, or -1 on connection error.
    """
    try:
        with smtplib.SMTP(mx_host, 25, timeout=10) as smtp:
            smtp.ehlo("mail.jobplatform.io")
            smtp.mail("verify@jobplatform.io")
            code, _ = smtp.rcpt(email)
            smtp.quit()
            return code
    except smtplib.SMTPServerDisconnected:
        return -1
    except smtplib.SMTPConnectError:
        return -1
    except smtplib.SMTPResponseException as exc:
        return exc.smtp_code
    except (OSError, TimeoutError) as exc:
        logger.debug("SMTP connection error for %s via %s: %s", email, mx_host, exc)
        return -1


def _is_catch_all(domain: str, mx_host: str) -> bool:
    """Detect whether *domain* is a catch-all (accepts any address).

    Result is cached per domain for the lifetime of the worker process.
    """
    if domain in _catch_all_cache:
        return _catch_all_cache[domain]

    random_local = "xyzrandomtest" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    random_email = f"{random_local}@{domain}"

    code = _smtp_check(random_email, mx_host)
    is_catch = code == 250
    _catch_all_cache[domain] = is_catch
    if is_catch:
        logger.debug("Domain %s detected as catch-all", domain)
    return is_catch


def verify_email_smtp(email: str) -> dict:
    """Verify that an email address exists via SMTP without sending.

    Returns:
        {
            "email": email,
            "status": "valid" | "invalid" | "catch_all" | "unknown",
            "mx_host": "<MX hostname or empty>",
        }
    """
    if not email or "@" not in email:
        return {"email": email, "status": "invalid", "mx_host": ""}

    domain = email.rsplit("@", 1)[1].lower()

    # Step 1: DNS MX lookup
    mx_host = _get_mx_host(domain)
    if not mx_host:
        return {"email": email, "status": "unknown", "mx_host": ""}

    # Step 2: SMTP RCPT TO check
    code = _smtp_check(email, mx_host)

    if code == -1:
        return {"email": email, "status": "unknown", "mx_host": mx_host}

    if code == 250:
        # Server accepted -- check for catch-all
        if _is_catch_all(domain, mx_host):
            return {"email": email, "status": "catch_all", "mx_host": mx_host}
        return {"email": email, "status": "valid", "mx_host": mx_host}

    if code in (550, 551, 552, 553):
        return {"email": email, "status": "invalid", "mx_host": mx_host}

    # Any other code
    return {"email": email, "status": "unknown", "mx_host": mx_host}

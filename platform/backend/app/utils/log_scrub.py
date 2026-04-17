"""Logging filter that redacts secret-shaped strings from log records.

Defense-in-depth for the Anthropic key (and a handful of other credential
shapes the repo handles). Even though the config layer uses
:class:`pydantic.SecretStr` so ``str(settings)`` / ``model_dump()`` render
the key as ``**********``, and call sites use ``.get_secret_value()``
only where an outbound API client needs the raw value, a future bug
could still materialise the raw key somewhere in a log record — e.g.:

* an exception from the Anthropic SDK that happens to include the key
  in the message (rare, but we don't control their internals);
* a ``logger.debug(repr(request_headers))`` that accidentally picks up
  an ``Authorization: Bearer sk-ant-…`` header;
* a future code path that logs ``body`` before we've scrubbed it.

This filter runs at the ``logging.Logger`` level, so every handler
(stdout, file, structured JSON, syslog) inherits the redaction without
each having to be configured individually. The regex set matches the
credential shapes in ``scripts/check-forbidden-strings.sh`` — keep the
two aligned so anything the pre-commit hook blocks at push-time also
gets scrubbed if it ever shows up at runtime.

Wiring: :mod:`app.main` attaches the filter to the root logger at
startup. That covers every module's ``logging.getLogger(__name__)``
because child loggers inherit filters from the root when they don't
have their own handlers.
"""
from __future__ import annotations

import logging
import re

# Patterns we redact on sight. Ordered most-specific-first because the
# OpenAI-shaped `sk-...{48,}` regex would otherwise also match Anthropic
# keys (they start with `sk-ant-` but the substring `sk-` is the same).
# Keep synchronized with scripts/check-forbidden-strings.sh.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Anthropic — the value we shipped the feature for. Base62 + _ / -,
    # at least 20 chars of body after the `sk-ant-` prefix.
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # OpenAI project keys (different shape than the legacy sk-)
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    # OpenAI legacy — 48+ base62 body.
    re.compile(r"\bsk-[A-Za-z0-9]{48,}"),
    # GitHub fine-grained + classic tokens. All four prefixes share a
    # handful of entropy-bearing bodies; keep the 30+ char floor.
    re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    # Google API keys — fixed 35-char body.
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    # AWS access key id (not the secret, but also a credential).
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # Slack user/bot tokens.
    re.compile(r"\bxox[baprs]-[0-9]{10,}-[0-9]{10,}[A-Za-z0-9-]*"),
)

_REDACTED = "***REDACTED-SECRET***"


def _scrub(value: str) -> str:
    """Return ``value`` with every match of ``_SECRET_PATTERNS`` replaced.

    Runs each pattern in sequence. The vast majority of log records don't
    match any pattern, so the hot path is N compiled regex scans against
    short strings — low microseconds per log call, well below the noise
    floor of the surrounding I/O.
    """
    if not value:
        return value
    for pat in _SECRET_PATTERNS:
        value = pat.sub(_REDACTED, value)
    return value


class SecretScrubFilter(logging.Filter):
    """Logging filter that redacts secret-shaped tokens from every record.

    Scrubs three surfaces on each ``LogRecord``:

    * ``record.msg`` — the format string passed to ``logger.x()``. Most
      logs put user input through ``args`` (safe, below) but occasionally
      someone pre-formats, so we scrub the message too.
    * ``record.args`` — the tuple (or dict) interpolated into ``msg``.
      This is where an accidentally-logged key is most likely to land,
      since ``logger.warning("got %s", token)`` puts the token here.
    * ``record.exc_info`` — if the record came from ``logger.exception()``
      the traceback is still live here. We materialize it ourselves
      (``Formatter.formatException``), scrub, and stash back into
      ``record.exc_text``. Handlers see ``exc_text`` already populated
      and skip re-formatting, so our scrubbed copy is what ends up on
      disk. Without this, handler-time formatting would bypass the
      scrubber entirely and the raw exception string would leak.

    Returns ``True`` unconditionally — a redactor must never drop a
    record, only mutate it.
    """

    # Private formatter for exception materialization. Cached on the
    # class so we don't rebuild one per log call. Python's default
    # `Formatter()` is fine here — we only call `formatException`.
    _exc_formatter = logging.Formatter()

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: (_scrub(v) if isinstance(v, str) else v)
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _scrub(a) if isinstance(a, str) else a
                    for a in record.args
                )

        # Force-materialize exception text BEFORE the handler does it.
        # `logger.exception()` leaves exc_text=None and expects the
        # handler's formatter to render it at write-time — which
        # bypasses this filter. Pre-rendering here and caching into
        # exc_text makes the handler reuse our scrubbed string (see
        # `logging.Formatter.format` check for `record.exc_text`).
        if record.exc_info and not record.exc_text:
            record.exc_text = self._exc_formatter.formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = _scrub(record.exc_text)

        return True


def install_root_scrubber() -> None:
    """Attach :class:`SecretScrubFilter` to the root logger.

    Idempotent — re-running doesn't stack filters. Called once from
    :mod:`app.main` at process startup so every subsequent
    ``logging.getLogger(...)`` inherits the redaction.
    """
    root = logging.getLogger()
    # Idempotence: skip if a scrubber is already attached. Uses class
    # identity, so a user-installed drop-in that happens to be a
    # subclass still counts as "already protected".
    if any(isinstance(f, SecretScrubFilter) for f in root.filters):
        return
    root.addFilter(SecretScrubFilter())

    # Also attach to uvicorn's loggers. Uvicorn installs its own
    # handlers before our app code runs, and records emitted through
    # those handlers bypass the root filter chain. Attaching directly
    # is belt-and-suspenders.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error"):
        logging.getLogger(name).addFilter(SecretScrubFilter())

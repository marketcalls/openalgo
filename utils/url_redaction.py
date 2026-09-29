"""Redact replayable credentials embedded in public webhook URL paths."""

from __future__ import annotations

import re
from typing import Any

# The first path segment after each prefix is the credential. Flow may retain a
# non-secret symbol suffix, so the match stops at the next slash. Keeping this
# as one expression makes the same rule usable for a bare Flask path, a full
# URL, a Werkzeug request line, and arbitrary application-log text.
_URL_CREDENTIAL = re.compile(
    r"(?P<prefix>/(?:strategy|flow|chartink)/webhook/)[^/\s?#'\"<>]+",
    flags=re.IGNORECASE,
)

# Broker OAuth callbacks carry short-lived but replayable credentials in query
# parameters. Keep this URL-specific so an ordinary application line such as
# ``HTTP status code=200`` remains untouched while callback ``code=...`` is
# masked. The names cover the aliases accepted by ``blueprints/brlogin.py``.
_QUERY_CREDENTIAL = re.compile(
    r"(?P<prefix>[?&](?:"
    r"api[_-]?session|token(?:[_-]?id)?|request[_-]?token|auth[_-]?code|"
    r"access[_-]?token|session|code"
    r")=)[^&#\s'\"<>]+",
    flags=re.IGNORECASE,
)


def redact_url_credentials(value: Any) -> str:
    """Return ``value`` with shipped path and query credentials masked."""
    redacted = _URL_CREDENTIAL.sub(r"\g<prefix><redacted>", str(value))
    return _QUERY_CREDENTIAL.sub(r"\g<prefix>[REDACTED]", redacted)

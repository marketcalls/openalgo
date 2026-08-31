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


def redact_url_credentials(value: Any) -> str:
    """Return ``value`` with every shipped URL-secret segment masked."""
    return _URL_CREDENTIAL.sub(r"\g<prefix><redacted>", str(value))

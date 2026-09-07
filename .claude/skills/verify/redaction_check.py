#!/usr/bin/env python
"""Decide whether a log message shape leaks a secret past SensitiveDataFilter.

Reading the patterns in utils/logging.py does not tell you the answer. The key
alternation contains a bare ``token``, so ``"Feed Token: {t}"`` redacts, while
``"Access Token obtained: {t}"`` does not, because a word sits between the
keyword and the colon. Run the real patterns instead of predicting them.

Usage:
    uv run python .claude/skills/verify/redaction_check.py "<shape>" [value]

    # a shape whose value is a URL: pass the URL the code really builds,
    # because the parameter name decides the outcome
    ... "Connecting to: {u}" "wss://host/ws?Value1=SEKRET|CLIENT"

The value substitutes into every ``{...}`` slot. It must contain the marker
SEKRET (or pass your own value containing it) so the check can tell whether the
secret survived. Exits 1 when it leaks, so this works in a loop or a test.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from utils.logging import SENSITIVE_PATTERNS  # noqa: E402

MARKER = "SEKRET"


def redact(text: str) -> str:
    """Apply the production redaction patterns exactly as the filter does."""
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def render(shape: str, value: str) -> str:
    """Substitute the sample value into every {...} slot of the message shape."""
    return re.sub(r"\{[^}]*\}", value, shape)


def leaks(shape: str, value: str = MARKER) -> bool:
    """True when the marker survives redaction, i.e. the shape leaks."""
    return MARKER in redact(render(shape, value))


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__)
        return 2

    shape = argv[1]
    value = argv[2] if len(argv) == 3 else MARKER

    # Without a slot nothing substitutes, so the marker can never appear and the
    # shape would report "redact" no matter what. Refuse rather than reassure.
    if not re.search(r"\{[^}]*\}", shape):
        print(f"shape must contain a {{...}} slot for the value, got: {shape!r}")
        return 2

    if MARKER not in value:
        print(f"value must contain the marker {MARKER!r} so the check can detect survival")
        return 2

    out = redact(render(shape, value))
    leaked = MARKER in out
    print(f"{'LEAKS ' if leaked else 'redact'} | {out}")
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

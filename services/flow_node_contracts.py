"""Side-effect-free contracts shared by Flow node validation and execution."""

import re

# Order-update status values a watch can match on; ``any`` matches every update.
VALID_STATUSES = frozenset(
    {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}
)


def normalize_status(value: str | None) -> str:
    """Canonicalize a broker order status for watch validation and matching."""
    return str(value or "").strip().lower().replace("_", " ")


def parse_underlying_symbol(underlying: str) -> tuple[str, str | None]:
    """Split an optional ``DDMMMYY`` expiry from an underlying symbol."""
    match = re.match(r"^([A-Z]+)(\d{2}[A-Z]{3}\d{2})(?:FUT)?$", underlying.upper())
    if match:
        return match.group(1), match.group(2)
    return underlying.upper(), None

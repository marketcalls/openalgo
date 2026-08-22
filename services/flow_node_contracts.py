"""Side-effect-free contracts shared by Flow node validation and execution."""

# Order-update status values a watch can match on; ``any`` matches every update.
VALID_STATUSES = frozenset(
    {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}
)


def normalize_status(value: str | None) -> str:
    """Canonicalize a broker order status for watch validation and matching."""
    return str(value or "").strip().lower().replace("_", " ")

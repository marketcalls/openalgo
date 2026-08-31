"""Canonical intent-only audit messages for manual strategy exits."""

CLOSE_ALL_REQUESTED_MESSAGE = "Operator requested closure of all held legs"


def leg_close_requested_message(leg_id: object) -> str:
    """Describe accepted close intent without claiming a broker fill."""
    return f"Operator requested closure of leg {leg_id}"

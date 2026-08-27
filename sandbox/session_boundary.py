"""Session boundary helpers for sandbox position bookkeeping.

``sandbox_positions.updated_at`` is written by the database clock
(``func.now()``), which on the default SQLite database is UTC
(``CURRENT_TIMESTAMP``). ``SESSION_EXPIRY_TIME`` is a wall-clock time on
the host. Comparisons against position timestamps must resolve the
boundary in the database clock.
"""

from datetime import UTC, datetime, timedelta

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

# Host session schedule is anchored to IST; a naive caller is treated as
# IST wall-clock so the boundary is never silently read as UTC or system time.
IST = pytz.timezone("Asia/Kolkata")


def last_session_expiry_utc(session_expiry_str, now_local):
    """Resolve the most recent session boundary as a naive UTC datetime.

    Args:
        session_expiry_str: Wall-clock boundary from config (e.g. '03:00').
        now_local: Timezone-aware current time in the host's timezone.

    Returns:
        Naive UTC datetime of the most recent session expiry.
    """
    if now_local.tzinfo is None:
        logger.warning(
            "last_session_expiry_utc received a naive datetime; assuming Asia/Kolkata"
        )
        now_local = IST.localize(now_local)

    # Parse and range-check together. Splitting them leaves "25:00" parsing
    # cleanly as two ints and then raising from replace() below, which the
    # caller's broad `except Exception` swallows -- so a config typo silently
    # skips the MIS square-off instead of falling back.
    try:
        expiry_hour, expiry_minute = map(int, session_expiry_str.split(":"))
        boundary_today = now_local.replace(
            hour=expiry_hour, minute=expiry_minute, second=0, microsecond=0
        )
    except ValueError:
        logger.warning(
            f"Invalid SESSION_EXPIRY_TIME format: {session_expiry_str}. "
            "Using default 03:00"
        )
        boundary_today = now_local.replace(hour=3, minute=0, second=0, microsecond=0)
    if now_local >= boundary_today:
        boundary = boundary_today
    else:
        boundary = boundary_today - timedelta(days=1)
    return boundary.astimezone(UTC).replace(tzinfo=None)

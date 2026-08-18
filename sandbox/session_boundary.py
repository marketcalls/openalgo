"""Session boundary helpers for sandbox position bookkeeping.

``sandbox_positions.updated_at`` is written by the database clock
(``func.now()``), which on the default SQLite database is UTC
(``CURRENT_TIMESTAMP``). ``SESSION_EXPIRY_TIME`` is a wall-clock time on
the host. Comparisons against position timestamps must resolve the
boundary in the database clock.
"""

from datetime import UTC, datetime, timedelta


def last_session_expiry_utc(session_expiry_str, now_local):
    """Resolve the most recent session boundary as a naive UTC datetime.

    Args:
        session_expiry_str: Wall-clock boundary from config (e.g. '03:00').
        now_local: Timezone-aware current time in the host's timezone.

    Returns:
        Naive UTC datetime of the most recent session expiry.
    """
    expiry_hour, expiry_minute = map(int, session_expiry_str.split(":"))
    boundary_today = now_local.replace(
        hour=expiry_hour, minute=expiry_minute, second=0, microsecond=0
    )
    if now_local >= boundary_today:
        boundary = boundary_today
    else:
        boundary = boundary_today - timedelta(days=1)
    return boundary.astimezone(UTC).replace(tzinfo=None)

"""Where one trading session ends and the next begins.

OpenAlgo logs the user out at ``SESSION_EXPIRY_TIME``, 03:00 IST by default,
because Indian broker tokens expire daily around then. That hour, not
midnight, is the boundary every "today" in this module means: a strategy is
restarted after it, a signal run rolls at it, and a daily loss limit resets on
it.

Its own module because the engine and the signal path both need it and neither
may import the other.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from datetime import time as dt_time

import pytz

from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")


def session_reset_time() -> dt_time:
    """The hour the platform ends a trading session and revokes broker tokens."""
    raw = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
        return dt_time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        logger.warning("SESSION_EXPIRY_TIME is not HH:MM (%r); using 03:00", raw)
        return dt_time(hour=3)


def session_day(moment: datetime) -> date:
    """Which trading session an IST moment belongs to.

    Not the calendar date. A session runs until the platform's own reset, so
    anything before that hour still belongs to the previous day's session:
    01:00 on Tuesday is Monday's session, and Monday 22:00 and Tuesday 01:00
    are the same one.

    Using midnight instead would split a session in half and merge across the
    real boundary, which is exactly backwards.
    """
    if moment.time() < session_reset_time():
        return (moment - timedelta(days=1)).date()
    return moment.date()


def session_started_at(moment: datetime | None = None) -> datetime:
    """The instant the session containing ``moment`` began, in IST."""
    now = moment or datetime.now(IST)
    if now.tzinfo is None:
        now = IST.localize(now)
    return IST.localize(datetime.combine(session_day(now), session_reset_time()))

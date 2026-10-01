# database/alert_log_db.py
"""
What the chart's alerts actually did.

Alerts themselves are evaluated by the chart and live with it: a definition is
part of the chart's own state, and one only fires while /trading is open. That
is a deliberate limit, not an oversight, and it is why nothing here evaluates
anything. What the browser cannot keep is the *history*. A tab closed at four
o'clock takes the afternoon's fires with it, and an alert that fired while you
were looking at another screen left nothing behind at all.

So this table is a log, not a queue and not a scheduler. One row per fire,
written by the page the moment its chart raises one, and read back by the Log
tab in the alerts panel. It is also the only record that survives the delivery
attempt, which matters when a message did not arrive and the question is
whether the alert fired at all.

Source-agnostic on purpose. A fire is a fire whether it came from a price, a
study's plot, a drawing's level or a named candle condition, and the panel lists
them together because a trader wants one history rather than four. `kind` says
which it was for anybody filtering.

Mirrors database/watchlist_db.py:
- SQLite via the canonical engine factory (NullPool, closed immediately)
- scoped_session registered in utils/db_sessions.py for FD hygiene

Rows are scoped by ``user_id``, the session username. OpenAlgo is single-user
per deployment, so that is about keeping the schema honest rather than
isolating tenants.
"""

import math
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text, delete
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

#: How many rows the Log tab will return in one request. A trader scanning what
#: fired today is reading the top of the list; anything past this is history
#: nobody scrolls to, and an unbounded read is how one page load becomes a
#: multi-megabyte response after a busy month.
MAX_LOG_PAGE = 200

#: How long a fire is kept. Long enough to answer "did that alert fire last
#: week", short enough that the table never becomes something to maintain. The
#: trim runs on write, so there is no scheduler to forget about.
RETENTION_DAYS = 90

#: Trim at most this many rows per write. Deleting an unbounded number inside a
#: request is how a single fire blocks the worker: the app runs one cooperative
#: worker, and a long DELETE holds it for every user.
TRIM_BATCH = 500


def _utc_now():
    """Now, in UTC, as a naive datetime.

    Naive because the column is a plain ``DateTime`` and SQLite has no timezone
    of its own, so an aware value would be stored with its offset silently
    dropped and read back meaning something else. Naive-but-always-UTC is the
    only consistent choice, and ``_epoch`` below is the other half of it:
    nothing in this module may call ``.timestamp()`` on one of these directly.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _epoch(when):
    """A stored timestamp as epoch seconds, read as the UTC it was written as.

    ``datetime.timestamp()`` on a naive value assumes the *server's local*
    timezone, so on an IST host every firing would come back 5.5 hours in the
    past. That is the worst kind of wrong: the times look plausible, they sort
    correctly, and only somebody comparing the log against the chart would ever
    notice.
    """
    if when is None:
        return None
    return when.replace(tzinfo=UTC).timestamp()


class AlertFire(Base):
    """One alert firing, as the chart reported it."""

    __tablename__ = "alert_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(80), nullable=False)
    #: The chart's own id for the alert, so a row can be grouped with its
    #: siblings even after the alert itself has been deleted from the chart.
    alert_id = Column(String(64), nullable=False)
    title = Column(String(200), nullable=False, default="")
    #: price | indicator | drawing | barCondition. Stored as the chart's own
    #: word rather than a number, so a new source kind needs no migration here.
    kind = Column(String(24), nullable=False, default="price")
    condition = Column(String(24), nullable=False, default="")
    symbol = Column(String(60), nullable=False, default="")
    exchange = Column(String(20), nullable=False, default="")
    interval = Column(String(16), nullable=False, default="")
    #: What it fired at. Nullable because a candle-condition alert has no price
    #: of its own: it is true or it is not.
    price = Column(Float, nullable=True)
    #: The trader's own message, which is also what was delivered.
    message = Column(Text, nullable=True)
    #: Which channels accepted it, comma separated, e.g. "telegram,whatsapp".
    #: Empty means nothing was configured or nothing took it, and the panel
    #: says so rather than implying a message went out.
    delivered = Column(String(64), nullable=False, default="")
    fired_at = Column(DateTime, nullable=False, default=_utc_now)

    __table_args__ = (
        # The Log tab reads one user's rows newest first, which is this index
        # exactly. Without it every page load is a full scan plus a sort.
        Index("ix_alert_log_user_fired", "user_id", "fired_at"),
    )

    def to_dict(self):
        """The shape the Log tab renders, times as epoch seconds."""
        return {
            "id": self.id,
            "alertId": self.alert_id,
            "title": self.title,
            "kind": self.kind,
            "condition": self.condition,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "interval": self.interval,
            "price": self.price,
            "message": self.message or "",
            # A list rather than a string, because the caller renders one badge
            # per channel and splitting a string is the caller's job twice over.
            "delivered": [one for one in (self.delivered or "").split(",") if one],
            "firedAt": _epoch(self.fired_at),
        }


def init_db():
    """Create the alert log table if it is not there yet."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Alert Log DB", logger)


def record_fire(user_id, fire, delivered=()):
    """Write one firing and return it as a dict, or None if it could not be written.

    ``fire`` is the payload the chart reported. Everything is read defensively:
    it arrives from the browser, and a log that refuses to record because one
    optional field was missing is a log that is empty exactly when it matters.
    """
    if not user_id:
        return None
    alert_id = str(fire.get("alertId") or "").strip()[:64]
    if not alert_id:
        return None
    try:
        row = AlertFire(
            user_id=user_id,
            alert_id=alert_id,
            title=str(fire.get("title") or "")[:200],
            kind=str(fire.get("kind") or "price")[:24],
            condition=str(fire.get("condition") or "")[:24],
            symbol=str(fire.get("symbol") or "")[:60],
            exchange=str(fire.get("exchange") or "")[:20],
            interval=str(fire.get("interval") or "")[:16],
            price=_as_float(fire.get("price")),
            message=str(fire.get("message") or "")[:2000] or None,
            delivered=_channels(delivered),
            fired_at=_utc_now(),
        )
        db_session.add(row)
        db_session.commit()
        recorded = row.to_dict()
    except Exception:
        db_session.rollback()
        logger.exception("Could not record an alert firing")
        return None

    # Outside the try, and after the row has been read back. Housekeeping runs
    # on the back of a firing purely because there is no scheduler to hang it
    # on, and it must not be able to fail the thing it followed: the row is
    # already committed, so reporting "could not be recorded" here would send a
    # trader looking for an alert that did fire and is in the log.
    #
    # Swallowed rather than logged, because _trim has already logged whatever
    # went wrong with the detail it has. This guard exists so that the rule
    # holds for whatever gets added after the commit next.
    try:
        _trim(user_id)
    except Exception:
        pass
    return recorded


def list_fires(user_id, limit=MAX_LOG_PAGE):
    """This user's fires, newest first."""
    if not user_id:
        return []
    try:
        capped = max(1, min(int(limit or MAX_LOG_PAGE), MAX_LOG_PAGE))
    except (TypeError, ValueError):
        capped = MAX_LOG_PAGE
    try:
        rows = (
            db_session.query(AlertFire)
            .filter(AlertFire.user_id == user_id)
            .order_by(AlertFire.fired_at.desc(), AlertFire.id.desc())
            .limit(capped)
            .all()
        )
        return [row.to_dict() for row in rows]
    except Exception:
        db_session.rollback()
        logger.exception("Could not read the alert log")
        return []


def clear_fires(user_id, alert_id=None):
    """Delete this user's log, or just the rows for one alert. Returns the count."""
    if not user_id:
        return 0
    try:
        query = db_session.query(AlertFire).filter(AlertFire.user_id == user_id)
        if alert_id:
            query = query.filter(AlertFire.alert_id == str(alert_id)[:64])
        removed = query.delete(synchronize_session=False)
        db_session.commit()
        return int(removed or 0)
    except Exception:
        db_session.rollback()
        logger.exception("Could not clear the alert log")
        return 0


def _channels(delivered):
    """The channels that took the message, as a comma-separated field.

    Whole names only. Truncating the joined string would leave a half word in
    the column, and the panel renders one badge per name, so a row would grow a
    channel called "whats" that nobody can act on. Dropping a name that does not
    fit is the honest failure: it under-reports delivery rather than inventing a
    destination.
    """
    kept = []
    used = 0
    for name in sorted({str(one).strip() for one in delivered if str(one).strip()}):
        cost = len(name) + (1 if kept else 0)
        if used + cost > 64:
            break
        kept.append(name)
        used += cost
    return ",".join(kept)


def _as_float(value):
    """A price, or None. A string from JSON is still a price."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # NaN and the infinities are not prices, and each of them is what a JSON
    # number becomes when the browser had nothing to send.
    return number if math.isfinite(number) else None


def _trim(user_id):
    """Drop this user's rows past the retention window, a batch at a time."""
    try:
        cutoff = _utc_now() - timedelta(days=RETENTION_DAYS)
        old = (
            db_session.query(AlertFire.id)
            .filter(AlertFire.user_id == user_id, AlertFire.fired_at < cutoff)
            .limit(TRIM_BATCH)
            .all()
        )
        if not old:
            return
        db_session.execute(delete(AlertFire).where(AlertFire.id.in_([row.id for row in old])))
        db_session.commit()
    except Exception:
        db_session.rollback()
        # A trim that failed is not worth failing the fire it followed: the row
        # the trader cares about is already committed.
        logger.exception("Could not trim the alert log")

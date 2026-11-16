import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

from database.latency_groups import (
    ALL,
    ALL_GROUP,
    DEFAULT_GROUP,
    GROUPS,
    KNOWN_TAGS,
    ORDER_TAGS,
    OTHER,
    OTHER_GROUP,
    RETENTION_DAYS,
    canonical,
    endpoint_order,
    get_group,
    group_key_of,
    is_group,
    label_of,
    tags_in,
)
from utils.thread_safe_cache import LockedTTLCache

logger = logging.getLogger(__name__)

# Use a separate database for latency logs
LATENCY_DATABASE_URL = os.getenv("LATENCY_DATABASE_URL", "sqlite:///db/latency.db")

# Conditionally create engine based on DB type
if LATENCY_DATABASE_URL and "sqlite" in LATENCY_DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    latency_engine = create_engine(
        LATENCY_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    latency_engine = create_engine(
        LATENCY_DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10
    )

latency_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=latency_engine)
)

# Percentiles need raw values in Python (numpy), so those queries are bounded
# to a recent window — order latency rows are kept forever and an unbounded
# fetch grows with the install's lifetime. Aggregates (counts/averages/SLA)
# remain all-time SQL aggregations.
PERCENTILE_WINDOW_DAYS = 30

# The dashboard polls stats; cache the computed result briefly so polling
# does not re-scan the table on every request. One entry per group: the page
# asks for a group at a time, and a single shared entry would answer a request
# for market data with the figures last worked out for orders.
_stats_cache = LockedTTLCache(maxsize=16, ttl=60)

#: Upper bounds, in milliseconds, of the page's Excellent, Good and Acceptable
#: bands. Anything slower is Slow. They describe an order confirmation, which
#: is why only a rated group is shown against them.
EXCELLENT_MS = 150
GOOD_MS = 250
ACCEPTABLE_MS = 400
LatencyBase = declarative_base()
LatencyBase.query = latency_session.query_property()


class OrderLatency(LatencyBase):
    """Model for tracking end-to-end order execution latency"""

    __tablename__ = "order_latency"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    order_id = Column(String(100), nullable=False)
    user_id = Column(Integer)
    broker = Column(String(50))
    symbol = Column(String(50))
    # Which endpoint the call was to: PLACE, HISTORY, FUNDS and so on. The
    # column name is from when only orders were recorded. The tags and their
    # groups are in database/latency_groups.py.
    order_type = Column(String(20))

    # Round-trip time (comparable to Postman/Bruno)
    rtt_ms = Column(Float)

    # Our processing overhead
    validation_latency_ms = Column(Float)  # Pre-request processing
    response_latency_ms = Column(Float)  # Post-response processing
    overhead_ms = Column(Float)  # Total overhead

    # Total time including overhead
    total_latency_ms = Column(Float, nullable=False)

    # Request details
    request_body = Column(JSON)  # Original request
    response_body = Column(JSON)  # Broker response
    status = Column(String(20))  # SUCCESS, FAILED, PARTIAL
    error = Column(String(500))  # Error message if any

    @staticmethod
    def log_latency(
        order_id,
        user_id,
        broker,
        symbol,
        order_type,
        latencies,
        request_body,
        response_body,
        status,
        error=None,
    ):
        """Log order execution latency"""
        try:
            # The error column is a String, but callers may hand us a non-string
            # payload — e.g. a failed request's response "message" can be a
            # marshmallow validation-errors dict ({'symbol': ['Missing data...']}).
            # SQLite cannot bind a dict/list to a text column, so coerce any
            # non-string error to str and bound it to the column width.
            if error is not None and not isinstance(error, str):
                error = str(error)
            if isinstance(error, str) and len(error) > 500:
                error = error[:500]

            log = OrderLatency(
                order_id=order_id,
                user_id=user_id,
                broker=broker,
                symbol=symbol,
                order_type=order_type,
                rtt_ms=latencies.get("rtt", 0),
                validation_latency_ms=latencies.get("validation", 0),
                response_latency_ms=latencies.get("broker_response", 0),
                overhead_ms=latencies.get("overhead", 0),
                total_latency_ms=latencies.get("total", 0),
                request_body=request_body,
                response_body=response_body,
                status=status,
                error=error,
            )
            latency_session.add(log)
            latency_session.commit()
            return True
        except Exception as e:
            logger.exception(f"Error logging latency: {str(e)}")
            latency_session.rollback()
            return False

    @staticmethod
    def get_recent_logs(limit=100, group=None):
        """The newest latency records, newest first.

        Args:
            limit: How many to return. None returns every record.
            group: A key from ``database.latency_groups`` to return only that
                group's records. None returns records of every kind, which is
                what this did before groups existed.
        """
        try:
            query = OrderLatency.query
            condition = _group_condition(group) if group else None
            if condition is not None:
                query = query.filter(condition)
            return query.order_by(OrderLatency.timestamp.desc()).limit(limit).all()
        except Exception as e:
            logger.exception(f"Error getting recent latency logs: {str(e)}")
            return []

    @staticmethod
    def get_latency_stats(group=DEFAULT_GROUP):
        """Latency figures for one group of endpoints.

        Every figure describes the records of ``group`` and no others. They used
        to describe every record together, on a page that called them orders,
        so a few hundred history calls decided the average, the P99 and the
        share under 150 ms that a trader read as order speed (issues #2421 and
        #2286). The default is the orders group, which is what the page's name
        has always said it shows.

        Counts, averages and the speed bands cover everything stored for the
        group. Percentiles need the raw values, so they cover the last
        ``PERCENTILE_WINDOW_DAYS`` days.

        Args:
            group: A key from ``database.latency_groups``: a named group,
                ``"other"`` for records in none of them, or ``"all"``.

        Returns:
            A dict whose shape is the same for every group, including an empty
            one and a failed read: see ``_empty_stats``.
        """
        if not is_group(group):
            group = DEFAULT_GROUP

        cached = _stats_cache.get(group)
        if cached is not None:
            return cached

        try:
            import numpy as np

            by_tag = _totals_by_tag()
            stats = _empty_stats(group, by_tag)
            order = endpoint_order(group)
            selected = {
                tag: row
                for tag, row in by_tag.items()
                if group == ALL or group_key_of(tag) == group
            }
            if not selected:
                _stats_cache[group] = stats
                return stats

            condition = _group_condition(group)
            cutoff = datetime.utcnow() - timedelta(days=PERCENTILE_WINDOW_DAYS)
            recent = latency_session.query(
                OrderLatency.order_type, OrderLatency.broker, OrderLatency.total_latency_ms
            ).filter(
                OrderLatency.total_latency_ms.isnot(None),
                OrderLatency.timestamp >= cutoff,
            )
            if condition is not None:
                recent = recent.filter(condition)

            every_value, by_tag_values, by_broker_values = [], {}, {}
            for tag, broker, value in recent.all():
                every_value.append(value)
                by_tag_values.setdefault(canonical(tag), []).append(value)
                if broker:
                    by_broker_values.setdefault(broker, []).append(value)

            def percentile(values, q):
                return float(np.percentile(values, q)) if values else 0.0

            total = _Totals()
            for row in selected.values():
                total.add(row)

            stats.update(total.figures())
            stats.update(
                {
                    "p50_total": percentile(every_value, 50),
                    "p90_total": percentile(every_value, 90),
                    "p95_total": percentile(every_value, 95),
                    "p99_total": percentile(every_value, 99),
                    "sla_100ms": total.share(total.under_100),
                    "sla_150ms": total.share(total.under_150),
                    "sla_200ms": total.share(total.under_200),
                    "distribution": {
                        "excellent": int(total.under_150),
                        "good": int(total.under_250 - total.under_150),
                        "acceptable": int(total.under_400 - total.under_250),
                        "slow": int(total.count - total.under_400),
                    },
                }
            )

            stats["endpoints"] = [
                {
                    "type": tag,
                    "label": label_of(tag),
                    **row.figures(),
                    "p50_total": percentile(by_tag_values.get(tag), 50),
                    "p99_total": percentile(by_tag_values.get(tag), 99),
                }
                for tag, row in sorted(
                    selected.items(),
                    # A group's own order, then anything else by name, untagged last.
                    key=lambda item: (
                        order.get(item[0], len(order)),
                        item[0] is None,
                        str(item[0]),
                    ),
                )
            ]

            brokers = latency_session.query(OrderLatency.broker, *_Totals.columns()).filter(
                OrderLatency.broker.isnot(None)
            )
            if condition is not None:
                brokers = brokers.filter(condition)
            for broker_row in brokers.group_by(OrderLatency.broker).all():
                broker = broker_row[0]
                row = _Totals.from_row(broker_row[1:])
                stats["broker_stats"][broker] = {
                    **row.figures(),
                    "p50_total": percentile(by_broker_values.get(broker), 50),
                    "p99_total": percentile(by_broker_values.get(broker), 99),
                    "sla_150ms": row.share(row.under_150),
                }

            _stats_cache[group] = stats
            return stats
        except Exception as e:
            logger.exception(f"Error getting latency stats: {str(e)}")
            return _empty_stats(group, {})


class _Totals:
    """Running totals for a set of latency records.

    Sums rather than averages are read from SQL so that totals for several
    endpoints can be added together: an average of averages is wrong whenever
    the endpoints were not called equally often, which they never are.
    """

    __slots__ = (
        "count",
        "failed",
        "rtt",
        "overhead",
        "total",
        "under_100",
        "under_150",
        "under_200",
        "under_250",
        "under_400",
    )

    def __init__(self):
        for name in self.__slots__:
            setattr(self, name, 0)

    @staticmethod
    def columns():
        """The SQL aggregates, in the order of ``__slots__``."""
        from sqlalchemy import case

        elapsed = OrderLatency.total_latency_ms

        def under(limit):
            return func.sum(case((elapsed < limit, 1), else_=0))

        return (
            func.count(OrderLatency.id),
            func.sum(case((OrderLatency.status == "FAILED", 1), else_=0)),
            func.sum(OrderLatency.rtt_ms),
            func.sum(OrderLatency.overhead_ms),
            func.sum(elapsed),
            under(100),
            under(EXCELLENT_MS),
            under(200),
            under(GOOD_MS),
            under(ACCEPTABLE_MS),
        )

    @classmethod
    def from_row(cls, values):
        row = cls()
        for name, value in zip(cls.__slots__, values, strict=True):
            setattr(row, name, value or 0)
        return row

    def add(self, other):
        for name in self.__slots__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def share(self, part):
        """``part`` as a percentage of the records counted."""
        return float(part / self.count * 100) if self.count else 0.0

    def figures(self):
        count = self.count
        return {
            "total_orders": int(count),
            "failed_orders": int(self.failed),
            "success_rate": self.share(count - self.failed),
            "avg_rtt": float(self.rtt / count) if count else 0.0,
            "avg_overhead": float(self.overhead / count) if count else 0.0,
            "avg_total": float(self.total / count) if count else 0.0,
        }


def _group_condition(group):
    """The SQL condition that picks a group's records, or None for every record."""
    from sqlalchemy import or_

    if group == ALL or not is_group(group):
        return None
    if group == OTHER:
        return or_(OrderLatency.order_type.is_(None), ~OrderLatency.order_type.in_(KNOWN_TAGS))
    return OrderLatency.order_type.in_(tags_in(group))


def _totals_by_tag():
    """Totals for every endpoint, from one pass over the table.

    Keyed by the tag a stored value stands for, so rows written under an older
    spelling are counted with the endpoint they belong to. A record with no tag
    is kept under None, which is in no group and so counts as "other".
    """
    by_tag = {}
    rows = (
        latency_session.query(OrderLatency.order_type, *_Totals.columns())
        .group_by(OrderLatency.order_type)
        .all()
    )
    for row in rows:
        tag = canonical(row[0])
        totals = _Totals.from_row(row[1:])
        if tag in by_tag:
            by_tag[tag].add(totals)
        else:
            by_tag[tag] = totals
    return by_tag


def _empty_stats(group, by_tag):
    """The figures for a group with no records, and the list of groups.

    Also what a failed read returns, so the page is handed the same keys
    whatever happened. The fallback this replaces had its own keys, which did
    not match the ones a successful read used.
    """
    counts = {}
    for tag, row in by_tag.items():
        key = group_key_of(tag)
        counts[key] = counts.get(key, 0) + int(row.count)
    counts[ALL] = sum(counts.values())

    listed = [*GROUPS]
    if counts.get(OTHER) or group == OTHER:
        listed.append(OTHER_GROUP)
    listed.append(ALL_GROUP)

    chosen = get_group(group)
    return {
        "group": group,
        "groups": [
            {
                "key": item.key,
                "label": item.label,
                "description": item.description,
                "count": counts.get(item.key, 0),
                "rated": item.rated,
            }
            for item in listed
        ],
        "label": chosen.label,
        "description": chosen.description,
        "rated": chosen.rated,
        # None when the records are kept forever.
        "retention_days": None if chosen.kept else RETENTION_DAYS,
        "percentile_window_days": PERCENTILE_WINDOW_DAYS,
        "total_orders": 0,
        "failed_orders": 0,
        "success_rate": 0.0,
        "avg_rtt": 0.0,
        "avg_overhead": 0.0,
        "avg_total": 0.0,
        "p50_total": 0.0,
        "p90_total": 0.0,
        "p95_total": 0.0,
        "p99_total": 0.0,
        "sla_100ms": 0.0,
        "sla_150ms": 0.0,
        "sla_200ms": 0.0,
        "distribution": {"excellent": 0, "good": 0, "acceptable": 0, "slow": 0},
        "endpoints": [],
        "broker_stats": {},
    }


def init_latency_db():
    """Initialize the latency database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = LATENCY_DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(LatencyBase, latency_engine, "Latency DB", logger)


def purge_old_data_logs(days=RETENTION_DAYS):
    """
    Purge non-order endpoint latency logs older than specified days.
    Order execution logs (PLACE, SMART, MODIFY, CANCEL, etc.) are kept forever.

    What counts as an order is ``database.latency_groups.ORDER_TAGS``: the same
    list the recorder tags with and the page totals as orders. This function
    used to carry its own copy, and options orders, recorded under tags that
    were on neither copy, were purged with the data queries.
    """
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Delete non-order logs older than cutoff
        deleted = (
            latency_session.query(OrderLatency)
            .filter(OrderLatency.timestamp < cutoff, ~OrderLatency.order_type.in_(ORDER_TAGS))
            .delete(synchronize_session=False)
        )

        latency_session.commit()
        _stats_cache.clear()
        logger.debug(f"Purged {deleted} old data endpoint latency logs (older than {days} days)")
        return deleted
    except Exception as e:
        logger.exception(f"Error purging old latency logs: {str(e)}")
        latency_session.rollback()
        return 0

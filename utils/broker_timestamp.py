"""Parsing of broker tradebook/orderbook timestamps into naive datetimes."""

from datetime import datetime

from utils.logging import get_logger

logger = get_logger(__name__)


def parse_broker_timestamp(value, fallback=None):
    """Best-effort parse of a broker/CSV/ledger timestamp into a naive
    datetime. Falls back to ``fallback`` (or now) rather than raising - one
    malformed timestamp must not take down an entire order/trade fetch,
    capture run, or import batch.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value

    if value:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%d-%b-%Y %H:%M:%S",
            "%Y-%m-%d",
            "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
        logger.warning(f"Could not parse broker timestamp {value!r}")

    return fallback if fallback is not None else datetime.now()

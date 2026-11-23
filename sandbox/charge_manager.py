# sandbox/charge_manager.py
"""Charge settings and the transaction cost report.

The arithmetic lives in :mod:`sandbox.charges`, which performs no I/O. This
module is the part that touches the database: it reads the trader's brokerage
plan for a fill, saves it from the settings page, and reads the charges back
off the trades for the report.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytz
from sqlalchemy import case, func, or_

from database.sandbox_db import SandboxTrades, db_session, get_configs, set_configs
from sandbox.charges import (
    CHARGE_COLUMNS,
    CHARGES_ENABLED_KEY,
    MAX_BROKERAGE_FLAT,
    MAX_BROKERAGE_PERCENT,
    NO_CHARGES,
    SEGMENTS_BY_KEY,
    STATUTORY_SCHEDULE_AS_OF,
    Charges,
    brokerage_flat_key,
    brokerage_percent_key,
    classify_segment,
    compute_charges,
    config_keys,
    default_config_rows,
    default_config_values,
    describe_brokerage,
    estimate_round_trip,
    exchanges_of,
    is_enabled,
    paisa,
    plain,
    segments_for,
    split_exchange_charges,
    to_decimal,
    validate_brokerage,
)
from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

#: Trades listed on the report page. The totals always cover every trade in
#: the range; the CSV export has no limit.
REPORT_TRADE_LIMIT = 200

#: Days the report covers when no range is asked for.
REPORT_DEFAULT_DAYS = 30

#: Label for trades on an exchange the rate card has no segment for.
_OTHER_SEGMENT = ("other", "Other")


# ---------------------------------------------------------------------------
# Applying charges
# ---------------------------------------------------------------------------


def _contract_value(symbol: str, exchange: str) -> Decimal:
    """The symbol's contract multiplier (0.01 for some crypto contracts), else 1."""
    try:
        from database.token_db import get_symbol_info

        info = get_symbol_info(symbol, exchange)
        if info is not None and info.contract_value:
            return Decimal(str(info.contract_value))
    except Exception:
        logger.debug(f"No contract value for {symbol} on {exchange}; using 1", exc_info=True)
    return Decimal("1")


def brokerage_plan(segment_key: str) -> tuple[bool, Decimal, Decimal]:
    """The charges switch and one segment's brokerage, in a single read.

    A value that is missing or unreadable falls back to the segment's default,
    so a damaged setting can never make trades silently free.

    Returns:
        ``(enabled, flat, percent)``.
    """
    segment = SEGMENTS_BY_KEY[segment_key]
    flat_key = brokerage_flat_key(segment_key)
    percent_key = brokerage_percent_key(segment_key)
    stored = get_configs([CHARGES_ENABLED_KEY, flat_key, percent_key])
    return (
        is_enabled(stored.get(CHARGES_ENABLED_KEY, "true")),
        to_decimal(stored.get(flat_key), segment.default_flat),
        to_decimal(stored.get(percent_key), segment.default_percent),
    )


def charges_for_fill(symbol, exchange, product, action, quantity, price) -> Charges:
    """What a fill of this order at this price is charged under the saved plan.

    Args:
        symbol: OpenAlgo symbol.
        exchange: OpenAlgo exchange code.
        product: CNC, MIS or NRML.
        action: BUY or SELL.
        quantity: Filled quantity.
        price: Fill price.

    Returns:
        The charges; all zero when charges are switched off or the exchange has
        no segment on the rate card.
    """
    segment_key = classify_segment(exchange, product, symbol)
    if segment_key is None:
        return NO_CHARGES
    enabled, flat, percent = brokerage_plan(segment_key)
    if not enabled:
        return NO_CHARGES
    trade_value = _trade_value(symbol, exchange, quantity, price)
    return compute_charges(segment_key, exchange, action, trade_value, flat, percent)


def _trade_value(symbol, exchange, quantity, price) -> Decimal:
    """Price times quantity, times the contract multiplier where there is one."""
    return Decimal(str(price)) * abs(Decimal(str(quantity))) * _contract_value(symbol, exchange)


def order_charges(symbol, exchange, product, action, quantity, price) -> dict | None:
    """What an order would be charged under the saved plan, for the charges API.

    An estimate of what the trade costs, so it does not look at the charges
    switch: with the switch off a sandbox fill pays nothing, and the same
    order in a live account still pays this.

    Args:
        symbol: OpenAlgo symbol.
        exchange: OpenAlgo exchange code.
        product: CNC, MIS or NRML.
        action: BUY or SELL.
        quantity: Order quantity.
        price: The price the order would trade at.

    Returns:
        The segment, the trade value and the charges laid out as the API
        returns them, or None when orders cannot be placed on the exchange.
    """
    segment_key = classify_segment(exchange, product, symbol)
    if segment_key is None:
        return None
    _enabled, flat, percent = brokerage_plan(segment_key)
    trade_value = _trade_value(symbol, exchange, quantity, price)
    charges = compute_charges(segment_key, exchange, action, trade_value, flat, percent)
    transaction, ipft = split_exchange_charges(
        segment_key, exchange, trade_value, charges.exchange_charges
    )
    return {
        "segment": SEGMENTS_BY_KEY[segment_key].label,
        "trade_value": float(paisa(trade_value)),
        "charges": {
            "total": float(charges.total),
            "brokerage": float(charges.brokerage),
            "taxes": {
                "gst": float(charges.gst),
                "stt": float(charges.stt),
                "stamp_duty": float(charges.stamp_duty),
            },
            "other_charges": {
                "transaction": float(transaction),
                "clearing": 0.0,
                "ipft": float(ipft),
                "sebi_turnover": float(charges.sebi_charges),
            },
        },
    }


# ---------------------------------------------------------------------------
# The settings page
# ---------------------------------------------------------------------------


def get_charge_settings(market=None) -> dict:
    """The brokerage plan and the statutory schedule, as the settings page shows them.

    Args:
        market: ``MARKET_INDIAN`` or ``MARKET_CRYPTO`` to list that market's
            segments alone, which is what a page shows: a trader on an Indian
            broker is never offered the crypto rate card, nor the other way
            round. None lists every segment.
    """
    stored = get_configs(config_keys())
    segments = []
    for segment in segments_for(market):
        flat = to_decimal(stored.get(brokerage_flat_key(segment.key)), segment.default_flat)
        percent = to_decimal(
            stored.get(brokerage_percent_key(segment.key)), segment.default_percent
        )
        segments.append(
            {
                "key": segment.key,
                "label": segment.label,
                "group": segment.group,
                "applies_to": segment.applies_to,
                "flat": plain(flat),
                "percent": plain(percent),
                "default_flat": plain(segment.default_flat),
                "default_percent": plain(segment.default_percent),
                "summary": describe_brokerage(flat, percent),
                # A list, main exchange first: the order of the rates below
                # does not survive being sent as an object.
                "exchanges": list(exchanges_of(segment)),
                "statutory": {
                    "stt_label": segment.stt_label,
                    "stt_buy": plain(segment.stt_buy),
                    "stt_sell": plain(segment.stt_sell),
                    "stamp_buy": plain(segment.stamp_buy),
                    "sebi": plain(segment.sebi),
                    "gst": plain(segment.gst),
                    "exchange_txn": {
                        exchange: plain(rate) for exchange, rate in segment.exchange_txn.items()
                    },
                },
            }
        )
    return {
        "enabled": is_enabled(stored.get(CHARGES_ENABLED_KEY, "true")),
        "market": market,
        "segments": segments,
        "limits": {
            "flat_max": plain(MAX_BROKERAGE_FLAT),
            "percent_max": plain(MAX_BROKERAGE_PERCENT),
        },
        "statutory_as_of": STATUTORY_SCHEDULE_AS_OF,
    }


def save_charge_settings(payload) -> tuple[bool, str]:
    """Validate and store what the settings page submitted.

    Everything is checked before anything is written, and the write is one
    commit, so a fill that lands during a save is charged under the old plan
    or the new one and never a mixture.

    Args:
        payload: ``{"enabled": bool, "segments": {key: {"flat": .., "percent": ..}}}``.
            Either part may be left out; segments that are not named keep
            their values.

    Returns:
        ``(ok, message)``, the message being a sentence for the trader.
    """
    if not isinstance(payload, dict):
        return False, "Nothing was saved: the settings could not be read."

    values: dict[str, str] = {}

    if "enabled" in payload:
        enabled = payload["enabled"]
        if isinstance(enabled, str):
            if enabled.strip().lower() not in ("true", "false"):
                return False, "Charges can only be switched on or off."
            enabled = enabled.strip().lower() == "true"
        if not isinstance(enabled, bool):
            return False, "Charges can only be switched on or off."
        values[CHARGES_ENABLED_KEY] = "true" if enabled else "false"

    segments = payload.get("segments") or {}
    if not isinstance(segments, dict):
        return False, "Nothing was saved: the brokerage plan could not be read."

    for segment_key, entry in segments.items():
        if not isinstance(entry, dict):
            return False, "Nothing was saved: the brokerage plan could not be read."
        flat, percent, error = validate_brokerage(
            segment_key, entry.get("flat", ""), entry.get("percent", "")
        )
        if error:
            return False, error
        values[brokerage_flat_key(segment_key)] = plain(flat)
        values[brokerage_percent_key(segment_key)] = plain(percent)

    if not values:
        return False, "There was nothing to save."

    descriptions = {row["config_key"]: row["description"] for row in default_config_rows()}
    if not set_configs(values, descriptions):
        return False, "The settings could not be saved. Please try again."
    return True, "Charges saved. They apply from the next trade."


def reset_charge_settings() -> bool:
    """Put the brokerage plan and the charges switch back to their defaults."""
    descriptions = {row["config_key"]: row["description"] for row in default_config_rows()}
    return set_configs(default_config_values(), descriptions)


def estimate(payload, market=None) -> tuple[bool, dict | str]:
    """A round trip under a brokerage plan, for the page's calculator.

    Uses the flat and percentage values in the payload when they are given,
    so a trader can see what a plan costs before saving it, and the saved plan
    otherwise.

    Args:
        payload: The trade: segment, exchange, buy and sell price, quantity.
        market: The market of the broker the trader is logged in to. A segment
            of the other market is refused: the calculator of an Indian broker
            does not price crypto, and a crypto venue's does not price the
            Indian exchanges. None prices any segment.

    Returns:
        ``(True, breakdown)`` or ``(False, sentence for the trader)``.
    """
    if not isinstance(payload, dict):
        return False, "Enter the trade to estimate."

    segment_key = str(payload.get("segment", ""))
    segment = SEGMENTS_BY_KEY.get(segment_key)
    if segment is None:
        return False, "Choose a segment."
    if market is not None and segment.market != market:
        return False, f"{segment.label} is not traded with the broker you are logged in to."

    exchange = str(payload.get("exchange", "")).upper()
    exchanges = exchanges_of(segment)
    if exchange not in exchanges:
        return False, f"{segment.label} trades on {' or '.join(exchanges)}. Choose one of them."

    buy_price = to_decimal(payload.get("buy_price"), Decimal("-1"))
    sell_price = to_decimal(payload.get("sell_price"), Decimal("-1"))
    quantity = to_decimal(payload.get("quantity"), Decimal("-1"))
    if buy_price <= 0 or sell_price <= 0:
        return False, "Enter a buy price and a sell price above zero."
    if quantity <= 0:
        return False, "Enter a quantity above zero."

    if "flat" in payload or "percent" in payload:
        flat, percent, error = validate_brokerage(
            segment_key, payload.get("flat", ""), payload.get("percent", "")
        )
        if error:
            return False, error
    else:
        _enabled, flat, percent = brokerage_plan(segment_key)

    result = estimate_round_trip(
        segment_key, exchange, buy_price, sell_price, quantity, flat, percent
    )
    return True, {
        "segment": segment_key,
        "exchange": exchange,
        "brokerage_plan": describe_brokerage(flat, percent),
        "stt_label": segment.stt_label or "STT",
        "turnover": float(result["turnover"]),
        "total": _charges_dict(result["total"]),
        "gross_pnl": float(result["gross_pnl"]),
        "net_pnl": float(result["net_pnl"]),
        "points_to_breakeven": float(result["points_to_breakeven"]),
    }


def _charges_dict(charges: Charges) -> dict[str, float]:
    return {name: float(value) for name, value in charges.as_columns().items()}


# ---------------------------------------------------------------------------
# The transaction cost report
# ---------------------------------------------------------------------------


def parse_report_range(from_text, to_text, today: date | None = None):
    """Turn the report's two date fields into a half-open timestamp range.

    Trade timestamps are IST wall-clock, so the dates are read as IST days.

    Args:
        from_text: ``YYYY-MM-DD`` or empty.
        to_text: ``YYYY-MM-DD`` or empty.
        today: The IST date to count back from; defaults to now.

    Returns:
        ``(from_date, to_date, error)``. With no dates given the range is the
        last REPORT_DEFAULT_DAYS days. ``error`` is a sentence for the trader.
    """
    today = today or datetime.now(IST).date()

    def parse(text):
        text = (text or "").strip()
        if not text:
            return None, None
        try:
            return datetime.strptime(text, "%Y-%m-%d").date(), None
        except ValueError:
            return None, "Dates must look like 2026-11-23 (year, month, day)."

    to_date, error = parse(to_text)
    if error:
        return None, None, error
    from_date, error = parse(from_text)
    if error:
        return None, None, error

    to_date = to_date or today
    from_date = from_date or (to_date - timedelta(days=REPORT_DEFAULT_DAYS - 1))
    if from_date > to_date:
        return None, None, "The start date is after the end date."
    return from_date, to_date, None


def _range_filter(user_id, from_date: date, to_date: date):
    start = datetime.combine(from_date, time.min)
    end = datetime.combine(to_date + timedelta(days=1), time.min)
    return (
        SandboxTrades.user_id == user_id,
        SandboxTrades.trade_timestamp >= start,
        SandboxTrades.trade_timestamp < end,
    )


def _money(value) -> Decimal:
    """A database sum as a paisa-rounded Decimal (SQLite sums DECIMAL as float)."""
    return paisa(Decimal(str(value or 0)))


def _empty_bucket() -> dict:
    bucket = {"trades": 0, "turnover": Decimal("0.00")}
    bucket.update({name: Decimal("0.00") for name in CHARGE_COLUMNS})
    return bucket


def _bucket_json(bucket: dict) -> dict:
    return {
        key: (float(value) if isinstance(value, Decimal) else value)
        for key, value in bucket.items()
    }


def trade_row(trade) -> dict:
    """One trade with its charges, as the report and the P&L page list it."""
    price = Decimal(str(trade.price or 0))
    quantity = abs(int(trade.quantity or 0))
    segment_key = classify_segment(trade.exchange, trade.product, trade.symbol)
    segment = SEGMENTS_BY_KEY.get(segment_key or "")
    row = {
        "tradeid": trade.tradeid,
        "orderid": trade.orderid,
        "timestamp": (
            trade.trade_timestamp.strftime("%Y-%m-%d %H:%M:%S") if trade.trade_timestamp else ""
        ),
        "symbol": trade.symbol,
        "exchange": trade.exchange,
        "product": trade.product,
        "action": trade.action,
        "quantity": trade.quantity,
        "price": float(price),
        "turnover": float(paisa(price * quantity)),
        "segment": segment.key if segment else _OTHER_SEGMENT[0],
        "segment_label": segment.label if segment else _OTHER_SEGMENT[1],
        "strategy": trade.strategy or "",
    }
    for name in CHARGE_COLUMNS:
        row[name] = float(getattr(trade, name, None) or 0)
    return row


def cost_report(user_id, from_date: date, to_date: date, limit: int = REPORT_TRADE_LIMIT) -> dict:
    """Charges paid in a date range: totals, by segment, by day and by trade.

    The totals and both breakdowns are summed in the database over every trade
    in the range, so they are complete however many trades there are. Only the
    trade list is cut to ``limit`` rows, most recent first.

    Args:
        user_id: Whose trades.
        from_date: First IST day, inclusive.
        to_date: Last IST day, inclusive.
        limit: Most trades to list.

    Returns:
        The report as plain JSON-ready values.
    """
    in_range = _range_filter(user_id, from_date, to_date)

    day = func.date(SandboxTrades.trade_timestamp).label("day")
    is_option = case(
        (or_(SandboxTrades.symbol.like("%CE"), SandboxTrades.symbol.like("%PE")), 1),
        else_=0,
    ).label("is_option")
    sums = [
        func.coalesce(func.sum(getattr(SandboxTrades, name)), 0).label(name)
        for name in CHARGE_COLUMNS
    ]
    grouped = (
        db_session.query(
            day,
            SandboxTrades.exchange,
            SandboxTrades.product,
            is_option,
            func.count(SandboxTrades.id).label("trades"),
            func.coalesce(func.sum(SandboxTrades.price * SandboxTrades.quantity), 0).label(
                "turnover"
            ),
            *sums,
        )
        .filter(*in_range)
        .group_by(day, SandboxTrades.exchange, SandboxTrades.product, is_option)
        .all()
    )

    totals = _empty_bucket()
    by_day: dict[str, dict] = {}
    by_segment: dict[str, dict] = {}

    for row in grouped:
        # The exchange decides the segment; the flag only tells an option from
        # a future on a derivatives exchange, so a stand-in symbol is enough.
        segment_key = classify_segment(row.exchange, row.product, "XCE" if row.is_option else "X")
        segment = SEGMENTS_BY_KEY.get(segment_key or "")
        key, label = (segment.key, segment.label) if segment else _OTHER_SEGMENT

        day_bucket = by_day.setdefault(str(row.day), _empty_bucket())
        segment_bucket = by_segment.setdefault(key, {"segment": key, "label": label})
        if "trades" not in segment_bucket:
            segment_bucket.update(_empty_bucket())

        for bucket in (totals, day_bucket, segment_bucket):
            bucket["trades"] += int(row.trades or 0)
            bucket["turnover"] += _money(row.turnover)
            for name in CHARGE_COLUMNS:
                bucket[name] += _money(getattr(row, name))

    order = {segment.key: index for index, segment in enumerate(segments_for())}
    segment_rows = sorted(
        by_segment.values(), key=lambda bucket: order.get(bucket["segment"], len(order))
    )
    day_rows = [{"date": day_key, **by_day[day_key]} for day_key in sorted(by_day, reverse=True)]

    trades = (
        SandboxTrades.query.filter(*in_range)
        .order_by(SandboxTrades.trade_timestamp.desc(), SandboxTrades.id.desc())
        .limit(limit)
        .all()
    )

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "totals": _bucket_json(totals),
        "by_segment": [_bucket_json(bucket) for bucket in segment_rows],
        "by_day": [_bucket_json(bucket) for bucket in day_rows],
        "trades": [trade_row(trade) for trade in trades],
        "trades_listed": len(trades),
        "trades_total": totals["trades"],
    }


#: Column headings of the report's CSV, with the trade_row keys they print.
REPORT_CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Timestamp", "timestamp"),
    ("Trade ID", "tradeid"),
    ("Order ID", "orderid"),
    ("Symbol", "symbol"),
    ("Exchange", "exchange"),
    ("Product", "product"),
    ("Segment", "segment_label"),
    ("Action", "action"),
    ("Quantity", "quantity"),
    ("Price", "price"),
    ("Turnover", "turnover"),
    ("Brokerage", "brokerage"),
    ("STT/CTT", "stt"),
    ("Exchange Charges", "exchange_charges"),
    ("SEBI Charges", "sebi_charges"),
    ("Stamp Duty", "stamp_duty"),
    ("GST", "gst"),
    ("Total Charges", "total_charges"),
    ("Strategy", "strategy"),
)


def cost_report_trades(user_id, from_date: date, to_date: date) -> list[dict]:
    """Every trade in the range with its charges, oldest first, for the CSV."""
    trades = (
        SandboxTrades.query.filter(*_range_filter(user_id, from_date, to_date))
        .order_by(SandboxTrades.trade_timestamp.asc(), SandboxTrades.id.asc())
        .all()
    )
    return [trade_row(trade) for trade in trades]

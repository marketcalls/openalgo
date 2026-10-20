# broker/hdfcsecurities/mapping/order_data.py
#
# Converts raw HDFC Securities InvestRight account JSON into the documented
# OpenAlgo common format (docs/api/account-services/*).
#
# InvestRight response envelopes (from the docs):
#   order book : {"status": "success", "data": [...]}
#   trade book : {"status": "success", "data": [...]}
#   positions  : {"status": "success", "data": {"net": [...]}}
#   holdings   : {"status": "success", "data": [...]}
#
# Response quirks the mappers have to absorb, all confirmed in the docs' own
# samples:
#   - `option_type` comes back as "Call" / "Put", never the CE / PE that orders
#     send.
#   - `expiry_date` comes back as "30 APR 2024" (orders/trades) or "27-JUN-24"
#     (positions), never the YYYYMMDD that orders send.
#   - `transaction_type` comes back title-cased ("Buy").
#   - The trade book returns the UNDERLYING name in `security_id`
#     ("BANKNIFTY") where the order book returns the real broker code
#     ("49599"), so symbol resolution needs a reconstruct-from-parts fallback.
#   - Holdings return `security_id` empty, leaving `isin` as the only
#     identifier on some rows.

import threading

from cachetools import TTLCache

from broker.hdfcsecurities.mapping.transform_data import (
    reverse_map_option_type,
    reverse_map_order_type,
    reverse_map_product_type,
    reverse_map_transaction_type,
    to_oa_exchange,
)
from database.token_db import get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

# InvestRight order status -> OpenAlgo lowercase status. Keys are normalized by
# _normalise_status(): uppercased with separators collapsed to single spaces.
_STATUS_MAP = {
    "TRADED": "complete",
    "EXECUTED": "complete",
    "COMPLETE": "complete",
    "COMPLETED": "complete",
    "FULLY EXECUTED": "complete",
    "REJECTED": "rejected",
    "CANCEL REJECTED": "rejected",
    "MODIFY REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "CANCELED": "cancelled",
    "CANCEL CONFIRMED": "cancelled",
    "TRIGGER PENDING": "trigger pending",
    "SL TRIGGER PENDING": "trigger pending",
    "PENDING": "open",
    "OPEN": "open",
    "PLACED": "open",
    "ACCEPTED": "open",
    "CONFIRMED": "open",
    "RECEIVED": "open",
    "MODIFIED": "open",
    "MODIFY PENDING": "open",
    "CANCEL PENDING": "open",
    "PARTIALLY TRADED": "open",
    "PARTIAL TRADE": "open",
    "PUT ORDER REQ RECEIVED": "open",
    "VALIDATION PENDING": "open",
    "AFTER MARKET ORDER REQ RECEIVED": "open",
    "OPEN PENDING": "open",
    "TRANSIT": "open",
}

# Statuses that can still be cancelled (used by cancel_all_orders_api).
CANCELLABLE_STATUSES = {
    status for status, mapped in _STATUS_MAP.items() if mapped in ("open", "trigger pending")
}


def _normalise_status(status):
    return " ".join(str(status or "").replace("_", " ").replace("-", " ").upper().split())


def map_order_status(status):
    normalised = _normalise_status(status)
    return _STATUS_MAP.get(normalised, normalised.lower())


def is_cancellable(order):
    """Whether an order-book row is still cancellable.

    Prefers the broker's own `cancellation_allowed` flag; it is documented as
    YES/NO but the sample returns an empty string, so the status map is the
    fallback rather than the primary signal.
    """
    flag = str(order.get("cancellation_allowed", "")).strip().upper()
    if flag in ("YES", "Y", "TRUE"):
        return True
    if flag in ("NO", "N", "FALSE"):
        return False
    return _normalise_status(order.get("status")) in CANCELLABLE_STATUSES


def _unwrap(payload, key=None):
    """Pull a list out of the InvestRight {status, message, data} envelope.

    `data` is a bare list for orders/trades/holdings and a dict keyed by "net"
    for positions, so both shapes are accepted.
    """
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    data = payload.get("data")
    if data is None:
        logger.info("No data available in HDFC Securities response.")
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get(key) if key else None
        if rows is None:
            # Positions come back as {"net": [...]}; fall back to the first
            # list-valued key so a renamed bucket does not silently blank out.
            rows = next((v for v in data.values() if isinstance(v, list)), [])
        return rows if isinstance(rows, list) else []
    return []


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# --- symbol resolution ---------------------------------------------------

_MONTHS = {
    "JAN": "JAN",
    "FEB": "FEB",
    "MAR": "MAR",
    "APR": "APR",
    "MAY": "MAY",
    "JUN": "JUN",
    "JUL": "JUL",
    "AUG": "AUG",
    "SEP": "SEP",
    "OCT": "OCT",
    "NOV": "NOV",
    "DEC": "DEC",
}


def _compact_expiry(expiry):
    """ "30 APR 2024" or "27-JUN-24" -> "30APR24". Returns "" when unparseable."""
    parts = str(expiry or "").replace("-", " ").upper().split()
    if len(parts) != 3:
        return ""
    day, month, year = parts
    if month not in _MONTHS:
        return ""
    return f"{int(day):02d}{month}{year[-2:]}" if day.isdigit() else ""


def _format_strike(strike):
    """Render a strike the way OpenAlgo symbols embed it: 22400 or 262.5."""
    value = _float(strike)
    return str(int(value)) if value == int(value) else str(value)


# Underlying names for an exchange are fixed for the trading day; this cache
# only stops the trade-book mapping from issuing one query per row. Bounded on
# both size and staleness, per the codebase's cachetools convention.
_UNDERLYING_NAME_CACHE = TTLCache(maxsize=2048, ttl=3600)
_UNDERLYING_NAME_LOCK = threading.Lock()


def _is_known_underlying(name, exchange):
    """Whether `name` is a real derivative underlying listed on `exchange`.

    Derivative rows in the master carry the underlying in `name` (BANKNIFTY,
    CIPLA, GOLD), so this separates a genuine display name from an unresolved
    broker code.
    """
    key = (exchange, name)
    with _UNDERLYING_NAME_LOCK:
        cached = _UNDERLYING_NAME_CACHE.get(key)
    if cached is not None:
        return cached

    from broker.hdfcsecurities.database.master_contract_db import SymToken, db_session

    try:
        with db_session() as session:
            found = (
                session.query(SymToken.id)
                .filter(SymToken.exchange == exchange, SymToken.name == name)
                .first()
                is not None
            )
    except Exception as e:
        # Unverifiable is not the same as verified: refuse the candidate rather
        # than let a broker code through into a fabricated symbol.
        logger.debug(f"Could not verify underlying {exchange}:{name}: {e}")
        return False

    with _UNDERLYING_NAME_LOCK:
        _UNDERLYING_NAME_CACHE[key] = found
    return found


def _underlying_name(row, exchange, verify_broker_code):
    """The underlying's display name for a row, or "" when there is none.

    The trade book is the awkward case: it puts the UNDERLYING name in
    `security_id` ("BANKNIFTY") where the order book puts the broker code
    ("49599"), and it may carry no `underlying_symbol` / `company_name` at all.
    An unresolved `security_id` is therefore usable as the underlying -- but
    only after the master confirms it: InvestRight broker codes are mostly
    alphanumeric ("CIPLTDEQNR", "B843283"), so a shape test alone would splice
    one into a plausible-looking but entirely fabricated symbol such as
    "CIPLTDEQNR30APR24100CE". `verify_broker_code` is False when the row has no
    expiry, where the candidate is returned verbatim either way and the lookup
    would be pure cost.
    """
    name = str(row.get("underlying_symbol") or row.get("company_name") or "").strip()
    if name:
        return name

    candidate = str(row.get("security_id") or "").strip()
    if not candidate or candidate.isdigit():
        return ""
    if verify_broker_code and not _is_known_underlying(candidate, exchange):
        return ""
    return candidate


def _reconstruct_symbol(row, exchange):
    """Rebuild the OpenAlgo symbol from the parts InvestRight spells out.

    Used when `security_id` does not resolve against the master contract, which
    is the normal case for trade-book rows.
    """
    expiry = _compact_expiry(row.get("expiry_date"))
    underlying = _underlying_name(row, exchange, verify_broker_code=bool(expiry))
    if not underlying:
        return ""
    if not expiry:
        return underlying
    option_type = reverse_map_option_type(row.get("option_type"))
    if option_type:
        return f"{underlying}{expiry}{_format_strike(row.get('strike_price'))}{option_type}"
    return f"{underlying}{expiry}FUT"


def _oa_symbol(row, exchange):
    """Broker row -> OpenAlgo symbol, never blank when anything is resolvable.

    Last resort is `isin`: holdings can come back with `security_id`,
    `company_name` and every other name field empty, leaving the ISIN as the
    only identifier on the row. It is not a tradable OpenAlgo symbol and
    InvestRight's security master carries no ISIN column to map it back
    through, but surfacing it beats returning a blank row the user cannot
    identify at all.
    """
    security_id = str(row.get("security_id") or "").strip()
    if security_id:
        try:
            resolved = get_oa_symbol(brsymbol=security_id, exchange=exchange)
        except Exception as e:
            logger.debug(f"Could not map HDFC Securities symbol {exchange}:{security_id}: {e}")
            resolved = None
        if resolved:
            return resolved

    reconstructed = _reconstruct_symbol(row, exchange)
    if reconstructed:
        return reconstructed
    if security_id:
        return security_id

    isin = str(row.get("isin") or "").strip()
    if isin:
        logger.warning(
            f"HDFC Securities {exchange} row carries no security_id or name; "
            f"falling back to ISIN {isin} as the symbol"
        )
    return isin


def _normalise_row(row):
    """Shared normalization for order / trade / position rows."""
    exchange = to_oa_exchange(row.get("exchange"), row.get("instrument_segment"))
    row["exchange"] = exchange
    row["symbol"] = _oa_symbol(row, exchange)
    row["product"] = reverse_map_product_type(exchange, row.get("product")) or row.get("product")
    return row


# --- order book ---------------------------------------------------------


def map_order_data(order_data):
    """Normalize broker symbols/codes in the order book in place."""
    orders = _unwrap(order_data)
    for order in orders:
        _normalise_row(order)
        order["order_type"] = reverse_map_order_type(order.get("order_type"))
    return orders


def calculate_order_statistics(order_data):
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    for order in order_data or []:
        action = reverse_map_transaction_type(order.get("transaction_type"))
        if action == "BUY":
            total_buy_orders += 1
        elif action == "SELL":
            total_sell_orders += 1

        # Accept both raw broker statuses and already-transformed lowercase
        # ones, so the counts hold whichever stage the caller passes in.
        status = map_order_status(order.get("order_status") or order.get("status"))
        if status == "complete":
            total_completed_orders += 1
        elif status in ("open", "trigger pending"):
            total_open_orders += 1
        elif status == "rejected":
            total_rejected_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]

    transformed = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(f"Expected a dict, found {type(order)}. Skipping.")
            continue
        transformed.append(
            {
                "symbol": order.get("symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": reverse_map_transaction_type(order.get("transaction_type")),
                "quantity": _int(order.get("quantity")),
                "price": _float(order.get("price")),
                "trigger_price": _float(order.get("trigger_price")),
                "pricetype": order.get("order_type", ""),
                "product": order.get("product", ""),
                "orderid": str(order.get("order_id", "")),
                "order_status": map_order_status(order.get("status")),
                "timestamp": order.get("order_timestamp", ""),
            }
        )
    return transformed


# --- trade book ---------------------------------------------------------


def map_trade_data(trade_data):
    trades = _unwrap(trade_data)
    for trade in trades:
        _normalise_row(trade)
    return trades


def transform_tradebook_data(tradebook_data):
    transformed = []
    for trade in tradebook_data or []:
        quantity = _int(trade.get("filled_quantity"))
        average_price = _float(trade.get("average_price"))
        # Prefer the broker's own traded value; it already accounts for
        # multi-fill averaging.
        trade_value = _float(trade.get("total_traded_value"), quantity * average_price)
        transformed.append(
            {
                "symbol": trade.get("symbol", ""),
                "exchange": trade.get("exchange", ""),
                "product": trade.get("product", ""),
                "action": reverse_map_transaction_type(trade.get("transaction_type")),
                "quantity": quantity,
                "average_price": average_price,
                "trade_value": round(trade_value, 2),
                "orderid": str(trade.get("order_id", "")),
                "timestamp": trade.get("fill_timestamp", ""),
            }
        )
    return transformed


# --- positions ----------------------------------------------------------


def map_position_data(position_data):
    positions = _unwrap(position_data, "net")
    for position in positions:
        _normalise_row(position)
    return positions


def transform_positions_data(positions_data):
    """Positions -> the OpenAlgo common format.

    InvestRight returns no LTP and no unrealised P&L, so `ltp` is injected by
    api/order_api.get_positions() from a batched /fetch-ltp call before this
    runs; it degrades to 0 when the quote is unavailable.
    """
    transformed = []
    for position in positions_data or []:
        net_quantity = _int(position.get("net_qty"))
        ltp = _float(position.get("ltp"))
        buy_value = _float(position.get("total_buy_value"))
        sell_value = _float(position.get("total_sell_value"))

        # Standard MTM: the realized leg (sell - buy value) plus the open leg
        # marked to the last traded price.
        pnl = (sell_value - buy_value) + (net_quantity * ltp)

        # The average price of the OPEN leg: a long carries the buy average,
        # a short the sell average.
        if net_quantity > 0:
            average_price = _float(position.get("average_buy_price"))
        elif net_quantity < 0:
            average_price = _float(position.get("average_sell_price"))
        else:
            average_price = 0.0

        transformed.append(
            {
                "symbol": position.get("symbol", ""),
                "exchange": position.get("exchange", ""),
                "product": position.get("product", ""),
                "quantity": net_quantity,
                "pnl": round(pnl, 2),
                "average_price": f"{average_price:.2f}",
                "ltp": round(ltp, 2),
            }
        )
    return transformed


# --- holdings -----------------------------------------------------------


def map_portfolio_data(portfolio_data):
    """Normalize demat holdings.

    Holdings rows carry no `instrument_segment` and are always cash equity, so
    the exchange maps straight through.
    """
    holdings = _unwrap(portfolio_data)
    for holding in holdings:
        exchange = to_oa_exchange(holding.get("exchange"), "EQUITY")
        holding["exchange"] = exchange
        holding["symbol"] = _oa_symbol(holding, exchange)
        # Demat holdings are delivery by definition.
        holding["product"] = "CNC"
    return holdings


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data or []:
        quantity = _int(holding.get("quantity"))
        average_price = _float(holding.get("average_price"))
        # InvestRight ships the previous close, not a live LTP; api/order_api
        # overwrites `ltp` from /fetch-ltp when the quote is available.
        ltp = _float(holding.get("ltp"), _float(holding.get("close_price")))
        pnl = (ltp - average_price) * quantity
        pnlpercent = ((ltp - average_price) / average_price * 100) if average_price else 0.0

        transformed.append(
            {
                "symbol": holding.get("symbol", ""),
                "exchange": holding.get("exchange", ""),
                "quantity": quantity,
                "product": holding.get("product", "CNC"),
                "average_price": round(average_price, 2),
                "pnl": round(pnl, 2),
                "pnlpercent": round(pnlpercent, 2),
            }
        )
    return transformed


def calculate_portfolio_statistics(holdings_data):
    def _ltp(holding):
        return _float(holding.get("ltp"), _float(holding.get("close_price")))

    totalholdingvalue = sum(_ltp(h) * _int(h.get("quantity")) for h in holdings_data or [])
    totalinvvalue = sum(
        _float(h.get("average_price")) * _int(h.get("quantity")) for h in holdings_data or []
    )
    totalprofitandloss = totalholdingvalue - totalinvvalue
    totalpnlpercentage = (totalprofitandloss / totalinvvalue * 100) if totalinvvalue else 0.0

    return {
        "totalholdingvalue": round(totalholdingvalue, 2),
        "totalinvvalue": round(totalinvvalue, 2),
        "totalprofitandloss": round(totalprofitandloss, 2),
        "totalpnlpercentage": round(totalpnlpercentage, 2),
    }

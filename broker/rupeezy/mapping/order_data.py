# Normalizes Vortex order/trade/position/holding books to OpenAlgo shapes.
#
# Vortex rows carry `ticker` ("NSE:NIFTY26OCT25000CE") and `exchange`
# ("NSE_FO"). The OpenAlgo symbol is resolved from the ticker's symbol part,
# which is stored as SymToken.brsymbol. MCX quantities come back in lots and
# are converted to units (see mapping/exchange.py).

from broker.rupeezy.mapping.exchange import (
    from_vortex_quantity,
    oa_exchange_for,
    split_ticker,
    trade_value,
)
from broker.rupeezy.mapping.transform_data import reverse_map_product_type, reverse_map_variety
from database.token_db import get_oa_symbol, get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)

# Vortex order status -> OpenAlgo order status.
# OMSXMITTED is "sent to the exchange, not yet acknowledged".
_STATUS_MAP = {
    "EXECUTED": "complete",
    "COMPLETE": "complete",
    "PENDING": "open",
    "OPEN": "open",
    "OMSXMITTED": "open",
    "TRIGGER PENDING": "trigger pending",
    "TRIGGER_PENDING": "trigger pending",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
}

OPEN_STATUSES = {"open", "trigger pending"}


def map_status(status):
    status = str(status or "").strip().upper()
    return _STATUS_MAP.get(status, status.lower())


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _underlying(oa_symbol, oa_exchange):
    """Master-contract `name` (the underlying for derivatives)."""
    info = get_symbol_info(oa_symbol, oa_exchange) if oa_symbol else None
    return info.name if info else None


def lot_size_for(row, oa_symbol, oa_exchange):
    """Lot size for MCX quantity conversion: the row's own if present, else
    the master contract's."""
    lot = row.get("lot_size")
    if lot:
        return lot
    info = get_symbol_info(oa_symbol, oa_exchange) if oa_symbol else None
    return info.lotsize if info and info.lotsize else 1


def _normalize_row(row):
    """Common fields shared by order, trade and position rows (in place)."""
    vortex_exchange = row.get("exchange", "")
    oa_exchange = oa_exchange_for(vortex_exchange)
    brsymbol = split_ticker(row.get("ticker")) or row.get("symbol", "")
    oa_symbol = get_oa_symbol(brsymbol=brsymbol, exchange=oa_exchange) or brsymbol
    row["_vortex_exchange"] = vortex_exchange
    row["_symbol"] = oa_symbol
    row["_exchange"] = oa_exchange
    row["_product"] = reverse_map_product_type(oa_exchange, row.get("product")) or row.get(
        "product", ""
    )
    row["_lot_size"] = lot_size_for(row, oa_symbol, oa_exchange)
    return row


def _units(row, key):
    return from_vortex_quantity(row.get(key), row["_vortex_exchange"], row["_lot_size"])


# --- Orders ---------------------------------------------------------------


def map_order_data(order_data):
    """Raw /trading/orders payload -> list of normalized order rows."""
    if not isinstance(order_data, dict):
        return []
    orders = order_data.get("orders") or order_data.get("data") or []
    return [_normalize_row(o) for o in orders if isinstance(o, dict)]


def calculate_order_statistics(order_data):
    stats = {
        "total_buy_orders": 0,
        "total_sell_orders": 0,
        "total_completed_orders": 0,
        "total_open_orders": 0,
        "total_rejected_orders": 0,
    }
    for order in order_data or []:
        side = str(order.get("transaction_type", "")).upper()
        if side == "BUY":
            stats["total_buy_orders"] += 1
        elif side == "SELL":
            stats["total_sell_orders"] += 1

        status = map_status(order.get("status"))
        if status == "complete":
            stats["total_completed_orders"] += 1
        elif status in OPEN_STATUSES:
            stats["total_open_orders"] += 1
        elif status == "rejected":
            stats["total_rejected_orders"] += 1
    return stats


def transform_order_data(orders):
    if isinstance(orders, dict):
        orders = [orders]
    transformed = []
    for order in orders or []:
        if not isinstance(order, dict):
            logger.warning(f"Expected a dict, found {type(order)}. Skipping.")
            continue
        if "_symbol" not in order:
            _normalize_row(order)
        transformed.append(
            {
                "symbol": order["_symbol"],
                "exchange": order["_exchange"],
                "action": str(order.get("transaction_type", "")).upper(),
                "quantity": _units(order, "total_quantity"),
                "price": _f(order.get("order_price")),
                "trigger_price": _f(order.get("trigger_price")),
                "pricetype": reverse_map_variety(order.get("variety", "")),
                "product": order["_product"],
                "orderid": order.get("order_id", ""),
                "order_status": map_status(order.get("status")),
                "timestamp": order.get("order_created_at", ""),
            }
        )
    return transformed


# --- Trades ---------------------------------------------------------------


def map_trade_data(trade_data):
    """Raw /trading/trades payload -> list of normalized trade rows."""
    if not isinstance(trade_data, dict):
        return []
    trades = trade_data.get("trades") or trade_data.get("data") or []
    return [_normalize_row(t) for t in trades if isinstance(t, dict)]


def transform_tradebook_data(tradebook_data):
    transformed = []
    for trade in tradebook_data or []:
        if "_symbol" not in trade:
            _normalize_row(trade)
        quantity = _units(trade, "trade_quantity")
        price = _f(trade.get("trade_price"))
        transformed.append(
            {
                "symbol": trade["_symbol"],
                "exchange": trade["_exchange"],
                "product": trade["_product"],
                "action": str(trade.get("transaction_type", "")).upper(),
                "quantity": quantity,
                "average_price": price,
                "trade_value": round(
                    trade_value(
                        quantity,
                        price,
                        trade["_exchange"],
                        _underlying(trade["_symbol"], trade["_exchange"]),
                        trade["_lot_size"],
                    ),
                    2,
                ),
                "orderid": trade.get("order_id", ""),
                "timestamp": trade.get("traded_at", ""),
            }
        )
    return transformed


# --- Positions ------------------------------------------------------------


def map_position_data(position_data):
    """Raw /trading/portfolio/positions payload -> normalized `net` rows.

    The `net` array is carried-forward plus today, which is what OpenAlgo's
    position book shows.
    """
    if not isinstance(position_data, dict):
        return []
    data = position_data.get("data") or {}
    rows = data.get("net") if isinstance(data, dict) else data
    return [_normalize_row(p) for p in rows or [] if isinstance(p, dict)]


def position_pnl(position):
    """Booked P&L of a closed position (sell_value - buy_value).

    An open position's P&L needs a live price, and Vortex quotes are outside
    this plugin's scope, so open positions report 0.
    """
    if _f(position.get("quantity")):
        return 0.0
    return _f(position.get("sell_value")) - _f(position.get("buy_value"))


def transform_positions_data(positions_data):
    transformed = []
    for position in positions_data or []:
        if "_symbol" not in position:
            _normalize_row(position)
        transformed.append(
            {
                "symbol": position["_symbol"],
                "exchange": position["_exchange"],
                "product": position["_product"],
                "quantity": str(_units(position, "quantity")),
                "pnl": round(position_pnl(position), 2),
                "average_price": f"{_f(position.get('average_price')):.2f}",
                "ltp": 0.0,
            }
        )
    return transformed


# --- Holdings -------------------------------------------------------------


def holding_quantity(holding):
    # TODO(rupeezy): confirm whether total_free already includes pledged
    # (collateral) quantity; it is free-to-sell DP + pool, plus T1 unsettled.
    return int(_f(holding.get("total_free")) + _f(holding.get("t1_quantity")))


def holding_listing(holding):
    """Pick the NSE listing, else BSE. Returns the {ticker, exchange, ...} dict."""
    for key in ("nse", "bse"):
        listing = holding.get(key) or {}
        if listing.get("ticker"):
            return listing
    return {}


def map_portfolio_data(portfolio_data):
    """Raw /trading/portfolio/holdings payload -> normalized holding rows.
    Each holding carries a `last_price`, which drives the value and P&L
    columns."""
    if not isinstance(portfolio_data, dict):
        return []
    holdings = portfolio_data.get("data") or []
    out = []
    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        listing = holding_listing(holding)
        oa_exchange = oa_exchange_for(listing.get("exchange", ""))
        brsymbol = split_ticker(listing.get("ticker"))
        holding["_symbol"] = (
            get_oa_symbol(brsymbol=brsymbol, exchange=oa_exchange)
            or brsymbol
            or holding.get("isin", "")
        )
        holding["_exchange"] = oa_exchange or ""
        holding["_quantity"] = holding_quantity(holding)
        holding["ltp"] = _f(holding.get("last_price"))
        out.append(holding)
    return out


def _holding_pnl(holding):
    qty = holding.get("_quantity", 0)
    ltp = _f(holding.get("ltp"))
    avg = _f(holding.get("average_price"))
    return (ltp - avg) * qty if ltp else 0.0


def transform_holdings_data(holdings_data):
    transformed = []
    for holding in holdings_data or []:
        avg = _f(holding.get("average_price"))
        ltp = _f(holding.get("ltp"))
        transformed.append(
            {
                "symbol": holding.get("_symbol", ""),
                "exchange": holding.get("_exchange", ""),
                "quantity": holding.get("_quantity", 0),
                "product": "CNC",
                "average_price": avg,
                "ltp": ltp,
                "pnl": round(_holding_pnl(holding), 2),
                "pnlpercent": round((ltp - avg) / avg * 100, 2) if avg and ltp else 0.0,
            }
        )
    return transformed


def calculate_portfolio_statistics(holdings_data):
    total_value = sum(_f(h.get("ltp")) * h.get("_quantity", 0) for h in holdings_data or [])
    total_inv = sum(_f(h.get("average_price")) * h.get("_quantity", 0) for h in holdings_data or [])
    total_pnl = sum(_holding_pnl(h) for h in holdings_data or [])
    return {
        "totalholdingvalue": round(total_value, 2),
        "totalinvvalue": round(total_inv, 2),
        "totalprofitandloss": round(total_pnl, 2),
        "totalpnlpercentage": round(total_pnl / total_inv * 100, 2) if total_inv else 0.0,
    }

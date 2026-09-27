from datetime import datetime

from broker.nubra.mapping.transform_data import (
    brexchange_of,
    candidate_exchanges,
    derivative_type_of,
    map_exchange,
    reverse_map_product_type,
)
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def flatten_order_buckets(response, buckets=None):
    """
    Flatten the bucketed GET /sentinel/orders response into a list of orders.

    V3 returns ``{"orders": {"open": [...], "executed": [...], "cancelled": [...],
    "expired": [...], "rejected": [...], "gtt": [...]}}``. Each order is tagged
    with its bucket under ``_bucket`` so callers can derive status from the
    bucket rather than re-deriving it from mixed fields.

    Args:
        buckets: optional iterable restricting which buckets are returned.
    """
    if not isinstance(response, dict):
        return []

    grouped = response.get("orders")
    if not isinstance(grouped, dict):
        return []

    flattened = []
    for bucket, orders in grouped.items():
        if buckets is not None and bucket not in buckets:
            continue
        for order in orders or []:
            if isinstance(order, dict):
                order = dict(order)
                order["_bucket"] = bucket
                flattened.append(order)
    return flattened


def extract_positions(positions_data):
    """
    Pull the flat positions list out of a V3 /sentinel/portfolio/positions response.
    """
    if isinstance(positions_data, list):
        return positions_data
    if not isinstance(positions_data, dict):
        return []

    portfolio = positions_data.get("portfolio") or {}
    return portfolio.get("positions") or []


def resolve_instrument(brexchange, derivative_type=None, ref_id=None, broker_symbol=None):
    """
    Resolve a Nubra instrument to (OpenAlgo symbol, OpenAlgo exchange).

    The exchange is confirmed rather than inferred: map_exchange() only decides
    which OpenAlgo exchanges are worth probing, and both values returned come
    from the master contract row that actually matched. ``ref_id`` is tried
    first because that is what Nubra stores in ``symtoken.token``; the broker
    symbol is the second key.

    Returns:
        ``(symbol, exchange)``, or ``(None, None)`` when nothing matched, so
        callers can say so instead of substituting a plausible-looking guess.
    """
    ref_id = str(ref_id or "").strip()
    broker_symbol = str(broker_symbol or "").strip()

    for candidate in candidate_exchanges(brexchange, derivative_type):
        if ref_id:
            symbol = get_symbol(ref_id, candidate)
            if symbol:
                return symbol, candidate
        if broker_symbol:
            symbol = get_oa_symbol(broker_symbol, candidate)
            if symbol:
                return symbol, candidate

    return None, None


def _first_present(row, *names):
    """First non-None value among ``names``, or None when the row has none of them."""
    if not isinstance(row, dict):
        return None
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


# The live /sentinel/portfolio/positions payload does NOT use the field names in
# the V3 doc: it returns netQty/buyQty/sellQty/ltp where the doc promises
# netQuantity/buyQuantity/sellQuantity/lastTradedPrice. Read the observed name
# first and keep the documented one as a fallback, so this survives Nubra
# aligning the API to its own documentation later.
def position_net_qty(position):
    """Signed net quantity for a V3 position row, as an int."""
    try:
        return int(_first_present(position, "netQty", "netQuantity") or 0)
    except (TypeError, ValueError):
        return 0


def position_ltp_paise(position):
    """Last traded price for a V3 position row, in paise."""
    return _first_present(position, "ltp", "lastTradedPrice") or 0


def resolve_position(position):
    """
    Resolve (tradingsymbol, exchange) for a V3 position row.

    ``position["symbol"]`` is Nubra's brsymbol, which only coincides with the
    OpenAlgo symbol for cash instruments -- an option is ``NIFTY26AUG24000CE``
    on Nubra and ``NIFTY25AUG2624000CE`` in OpenAlgo.

    An unresolved row keeps Nubra's own symbol and exchange so a live position
    is never dropped from the book, but says so in the log -- silently showing
    broker-native values would be indistinguishable from a correct row while
    every downstream lookup on it fails.
    """
    broker_symbol = position.get("symbol", "")
    nubra_exchange = brexchange_of(position)
    derivative_type = derivative_type_of(position)
    ref_id = str(position.get("refId", "") or "")

    symbol, exchange = resolve_instrument(
        nubra_exchange, derivative_type, ref_id=ref_id, broker_symbol=broker_symbol
    )
    if symbol:
        return symbol, exchange

    logger.warning(
        f"Nubra position not in the master contract: refId={ref_id!r} "
        f"symbol={broker_symbol!r} exchange={nubra_exchange!r} "
        f"derivativeType={derivative_type!r}; reporting broker-native values"
    )
    return broker_symbol, map_exchange(nubra_exchange, derivative_type)


# Nubra V3 lifecycle bucket -> OpenAlgo status vocabulary.
# GET /sentinel/orders groups orders by bucket instead of returning a flat list,
# so the bucket name is the authoritative status. "gtt" holds good-till-triggered
# orders, which are still-armed working orders.
_BUCKET_STATUS = {
    "open": "open",
    "executed": "complete",
    "cancelled": "cancelled",
    "rejected": "rejected",
    "expired": "cancelled",
    "gtt": "open",
}


def _parse_timestamp(value):
    """
    Format a V3 lifecycle timestamp for display.

    V3 ``timestamps`` are RFC3339 strings ("2026-06-22T05:00:45.054721358Z"),
    unlike V2's nanosecond integers. Fractional seconds can carry 9 digits,
    which ``fromisoformat`` rejects before Python 3.11, so truncate to
    microseconds first.
    """
    if not value:
        return ""
    if isinstance(value, (int, float)):
        # Defensive: accept a nanosecond epoch if Nubra ever returns one.
        try:
            return datetime.fromtimestamp(value / 1_000_000_000).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            return str(value)

    text = str(value).strip().replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                tail = tail[len(digits):]
                break
        else:
            tail = ""
        text = f"{head}.{digits[:6]}{tail}"

    try:
        return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def _last_timestamp(order):
    """Best available lifecycle time for an order, newest meaningful first."""
    timestamps = order.get("timestamps") or {}
    for key in ("lastUpdatedAt", "filledAt", "sentToColoAt", "intentCreatedAt"):
        if timestamps.get(key):
            return _parse_timestamp(timestamps[key])
    return ""


def _resolve_symbol(order):
    """
    Resolve (tradingsymbol, exchange, ref_id) for a V3 order or leg.

    The instrument lives on the first leg whenever the row carries no top-level
    refId. That is not just the strategy-order case the docs describe: live
    single orders also come back as ``isMulti: true`` with a populated
    ``legs[]`` and no top-level ``refId``.

    ``exchange`` is folded to the OpenAlgo exchange before any lookup -- Nubra
    reports an NSE option as ``NSE``, so ``get_symbol(ref_id, "NSE")`` would
    miss the ``NFO`` row and leave the caller with Nubra's display name.
    """
    ref_data = order.get("refData") or {}
    ref_id = order.get("refId")

    if not ref_id and order.get("legs"):
        first_leg = (order.get("legs") or [{}])[0] or {}
        ref_data = first_leg.get("refData") or ref_data
        ref_id = first_leg.get("refId")

    nubra_exchange = ref_data.get("exchange") or order.get("exchange", "")
    derivative_type = ref_data.get("derivativeType") or derivative_type_of(order)
    ref_id = str(ref_id or "")
    broker_symbol = ref_data.get("stockName", "")

    tradingsymbol, exchange = resolve_instrument(
        nubra_exchange, derivative_type, ref_id=ref_id, broker_symbol=broker_symbol
    )
    if tradingsymbol:
        return tradingsymbol, exchange, ref_id

    # displayName ("NIFTY 23 JUN 26 24050 CE") is a human label, never an
    # OpenAlgo symbol -- it is the last resort purely so the row still renders,
    # and it is worth a warning because nothing downstream can look it up.
    logger.warning(
        f"Nubra order not in the master contract: refId={ref_id!r} "
        f"stockName={broker_symbol!r} exchange={nubra_exchange!r} "
        f"derivativeType={derivative_type!r}; reporting broker-native values"
    )
    return (
        broker_symbol or ref_data.get("displayName", ""),
        map_exchange(nubra_exchange, derivative_type),
        ref_id,
    )


def _trigger_price_paise(order):
    """
    Extract the entry-trigger price (paise) from a V3 order.

    V3 has no flat trigger_price field -- a stop order carries an LTP trigger
    under entryConfig.triggers.ltp.{atOrAbove,atOrBelow}.value. Nubra may
    normalize entryConfig into a list, so handle both shapes.
    """
    entry_config = order.get("entryConfig")
    if isinstance(entry_config, list):
        entry_config = entry_config[0] if entry_config else None
    if not isinstance(entry_config, dict):
        return 0

    triggers = entry_config.get("triggers")
    if isinstance(triggers, list):
        triggers = triggers[0] if triggers else None
    if not isinstance(triggers, dict):
        return 0

    ltp = triggers.get("ltp")
    if not isinstance(ltp, dict):
        return 0

    for bound in ("atOrAbove", "atOrBelow"):
        node = ltp.get(bound)
        if isinstance(node, dict) and node.get("value"):
            return int(node["value"] or 0)
    return 0


def _order_type(order, trigger_paise):
    """
    Derive the OpenAlgo pricetype for a V3 order.

    V3 drops V2's ORDER_TYPE_STOPLOSS: a stop is an ordinary order carrying an
    entry trigger, so the presence of a trigger promotes MARKET/LIMIT to
    SL-M/SL.
    """
    price_type = str(order.get("priceType", "")).upper()
    if trigger_paise:
        return "SL-M" if price_type == "MARKET" else "SL"
    return price_type if price_type in ("MARKET", "LIMIT") else "MARKET"


def map_order_data(order_data):
    """
    Normalize the bucketed GET /sentinel/orders response to OpenAlgo format.

    Nubra V3 returns
        {"orders": {"open": [...], "executed": [...], "cancelled": [...], ...}}
    where each order is the normalized V3 intent-order model. Prices are in
    paise (divide by 100 for rupees).
    """
    orders = flatten_order_buckets(order_data)

    if not orders:
        logger.info("No Nubra order data available.")
        return []

    normalized_orders = []
    for order in orders:
        tradingsymbol, exchange, ref_id = _resolve_symbol(order)

        bucket = order.get("_bucket", "")
        status = _BUCKET_STATUS.get(bucket, str(order.get("status", "")).lower())

        trigger_paise = _trigger_price_paise(order)
        ordertype = _order_type(order, trigger_paise)

        # A still-working stop order is awaiting its trigger -> surface as
        # OpenAlgo "trigger pending" (matches the zerodha reference vocabulary).
        if ordertype in ("SL", "SL-M") and status == "open":
            status = "trigger pending"

        order_price_paise = order.get("orderPrice", 0) or 0
        filled_price_paise = order.get("filledPrice", 0) or 0

        strat_tags = order.get("stratTags") or []

        normalized_orders.append({
            "orderid": str(order.get("intentOrderId", "")),
            "exchange_order_id": _exchange_order_id(order),
            "tradingsymbol": tradingsymbol,
            "symboltoken": ref_id,
            "exchange": exchange,
            "transactiontype": str(order.get("side", "")).upper(),
            "producttype": reverse_map_product_type(order.get("deliveryType", "")),
            "ordertype": ordertype,
            "quantity": order.get("orderQty", 0) or 0,
            "filledshares": order.get("filledQty", 0) or 0,
            "averageprice": filled_price_paise / 100 if filled_price_paise else 0.0,
            "price": order_price_paise / 100 if order_price_paise else 0.0,
            "triggerprice": trigger_paise / 100 if trigger_paise else 0.0,
            "status": status,
            "ordertag": strat_tags[0] if strat_tags else "",
            "updatetime": _last_timestamp(order),
        })

    return normalized_orders


def _exchange_order_id(order):
    """
    Flatten V3's ``exchangeOrderIds`` map into a display string.

    V3 returns ``{"<refId>": [20]}`` rather than V2's single scalar id.
    """
    mapping = order.get("exchangeOrderIds")
    if not isinstance(mapping, dict):
        return ""
    ids = []
    for values in mapping.values():
        if isinstance(values, list):
            ids.extend(str(v) for v in values)
        elif values is not None:
            ids.append(str(values))
    return ",".join(ids)


def calculate_order_statistics(order_data):
    """
    Calculates statistics from order data, including totals for buy orders, sell orders,
    completed orders, open orders, and rejected orders.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - A dictionary containing counts of different types of orders.
    """
    # Initialize counters
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            # Count buy and sell orders
            if order["transactiontype"] == "BUY":
                total_buy_orders += 1
            elif order["transactiontype"] == "SELL":
                total_sell_orders += 1

            # Count orders based on their status
            if order["status"] == "complete":
                total_completed_orders += 1
            elif order["status"] == "open":
                total_open_orders += 1
            elif order["status"] == "rejected":
                total_rejected_orders += 1

    # Compile and return the statistics
    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    # Directly handling a dictionary assuming it's the structure we expect
    if isinstance(orders, dict):
        # Convert the single dictionary into a list of one dictionary
        orders = [orders]

    transformed_orders = []

    for order in orders:
        # Make sure each item is indeed a dictionary
        if not isinstance(order, dict):
            logger.warning(
                f"Warning: Expected a dict, but found a {type(order)}. Skipping this item."
            )
            continue

        transformed_orders.append({
            "symbol": order.get("tradingsymbol", ""),
            "exchange": order.get("exchange", ""),
            "action": order.get("transactiontype", ""),
            "quantity": order.get("quantity", 0),
            "price": order.get("price", 0.0),
            "trigger_price": order.get("triggerprice", 0.0),
            "pricetype": order.get("ordertype", ""),
            "product": order.get("producttype", ""),
            "orderid": order.get("orderid", ""),
            "order_status": order.get("status", ""),
            "timestamp": order.get("updatetime", ""),
        })

    return transformed_orders


def map_trade_data(trade_data):
    """
    Map Nubra's V3 order response to tradebook format.

    Nubra has no separate tradebook API, so trades are the orders carrying a
    non-zero filled quantity. Partial fills stay in the ``open`` bucket with
    filledQty > 0, so filtering on filledQty captures both full and partial
    fills. Prices are in paise.
    """
    orders = flatten_order_buckets(trade_data)

    if not orders:
        logger.info("No Nubra trade data available.")
        return []

    normalized_trades = []
    for order in orders:
        filled_qty = order.get("filledQty", 0) or 0
        if filled_qty <= 0:
            continue

        tradingsymbol, exchange, _ref_id = _resolve_symbol(order)

        filled_price = (order.get("filledPrice", 0) or 0) / 100
        trade_value = round(filled_price * filled_qty, 2)

        normalized_trades.append({
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "producttype": reverse_map_product_type(order.get("deliveryType", "")),
            "transactiontype": str(order.get("side", "")).upper(),
            "quantity": filled_qty,
            "fillprice": round(filled_price, 2),
            "tradevalue": trade_value,
            "orderid": str(order.get("intentOrderId", "")),
            "filltime": _last_timestamp(order),
        })

    return normalized_trades


def transform_tradebook_data(tradebook_data):
    """
    Transform normalized trade data to final OpenAlgo UI format.
    """
    transformed_data = []
    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get("tradingsymbol", ""),
            "exchange": trade.get("exchange", ""),
            "product": trade.get("producttype", ""),
            "action": trade.get("transactiontype", ""),
            "quantity": trade.get("quantity", 0),
            "average_price": trade.get("fillprice", 0.0),
            "trade_value": trade.get("tradevalue", 0),
            "orderid": trade.get("orderid", ""),
            "timestamp": trade.get("filltime", ""),
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    """
    Map Nubra's V3 positions response to OpenAlgo normalized format.

    V3 returns a single flat ``portfolio.positions`` list carrying a signed
    signed net quantity -- replacing V2's stock/fut/opt/close split that had to
    be merged and sign-corrected by hand.

    Prices are in paise (divide by 100).
    """
    if isinstance(position_data, dict) and (
        position_data.get("error") or position_data.get("status") == "error"
    ):
        logger.warning(f"Nubra positions error: {position_data}")
        return []

    raw_positions = extract_positions(position_data)
    if not raw_positions:
        logger.info("No Nubra position data available.")
        return []

    positions = []
    for pos in raw_positions:
        avg_price_paise = pos.get("avgPrice", 0) or 0
        ltp_paise = position_ltp_paise(pos)
        net_qty = position_net_qty(pos)

        tradingsymbol, exchange = resolve_position(pos)

        positions.append({
            "tradingsymbol": tradingsymbol,
            "symboltoken": str(pos.get("refId", "")),
            "exchange": exchange,
            "producttype": reverse_map_product_type(pos.get("deliveryType", "")),
            "netqty": net_qty,
            "quantity": net_qty,
            "avgnetprice": avg_price_paise / 100 if avg_price_paise else 0.0,
            "avgbuyprice": (pos.get("avgBuyPrice", 0) or 0) / 100,
            "avgsellprice": (pos.get("avgSellPrice", 0) or 0) / 100,
            "ltp": ltp_paise / 100 if ltp_paise else 0.0,
            "pnl": (pos.get("pnl", 0) or 0) / 100,
            "pnlpercentage": pos.get("pnlChg", 0) or 0,
        })

    logger.info(f"Nubra mapped positions: {len(positions)} positions")
    return positions


def transform_positions_data(positions_data):
    """
    Transform normalized position data to final UI format.

    Args:
        positions_data: List of normalized position dictionaries from map_position_data

    Returns:
        List of transformed position dictionaries for UI display
    """
    transformed_data = []
    for position in positions_data:
        transformed_position = {
            "symbol": position.get("tradingsymbol", ""),
            "exchange": position.get("exchange", ""),
            "product": position.get("producttype", ""),
            "quantity": position.get("netqty", 0),
            "average_price": position.get("avgnetprice", 0.0),
            "ltp": position.get("ltp", 0.0),
            "pnl": position.get("pnl", 0.0),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def transform_holdings_data(holdings_data):
    """
    Transform mapped Nubra holdings data to final OpenAlgo UI format.

    Expects the output of map_portfolio_data():
        {"holdings": [...mapped...], "holding_stats": {...}}

    Returns a list of dicts with: symbol, exchange, quantity, product, pnl, pnlpercent.
    """
    transformed_data = []

    holdings_list = holdings_data.get("holdings", []) if isinstance(holdings_data, dict) else []

    for holding in holdings_list:
        transformed_position = {
            "symbol": holding.get("tradingsymbol", ""),
            "exchange": holding.get("exchange", ""),
            "quantity": holding.get("quantity", 0),
            "product": holding.get("product", ""),
            "average_price": holding.get("average_price", 0.0),
            "ltp": holding.get("ltp", 0.0),
            "pnl": holding.get("pnl", 0.0),
            "pnlpercent": holding.get("pnlpercent", 0.0),
            "invested_value": holding.get("invested_value", 0.0),
            "current_value": holding.get("current_value", 0.0),
            "day_pnl": holding.get("day_pnl", 0.0),
            "day_pnl_chg": holding.get("day_pnl_chg", 0.0),
            "ltp_chg": holding.get("ltp_chg", 0.0),
            "ref_id": holding.get("ref_id", ""),
        }
        transformed_data.append(transformed_position)
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Map Nubra's V3 holdings response to a normalized internal format.

    Nubra V3 returns:
        {
            "message": "holdings",
            "portfolio": {
                "clientCode": "...",
                "holdingStats": { investedAmount, currentValue, totalPnl, ... },
                "holdings": [ { refId, symbol, exchange, quantity, avgPrice,
                                lastTradedPrice, netPnl, ... } ]
            }
        }

    Prices are in paise -- this function converts them to rupees (/100).
    Symbols are mapped to OpenAlgo format via get_oa_symbol().

    Returns:
        {"holdings": [...normalized...], "holding_stats": {...converted...}}
    """
    portfolio = None
    if isinstance(portfolio_data, dict):
        portfolio = portfolio_data.get("portfolio")

    if not portfolio or "holdings" not in portfolio:
        logger.info("Nubra Holdings - No portfolio data available.")
        return {"holdings": [], "holding_stats": {}}

    raw_holdings = portfolio.get("holdings") or []
    raw_stats = portfolio.get("holdingStats") or {}

    logger.info(f"Nubra holdings: {len(raw_holdings)} items, stats keys: {list(raw_stats.keys())}")

    mapped_holdings = []
    for h in raw_holdings:
        exchange = h.get("exchange", "NSE")
        broker_symbol = h.get("symbol", "")
        ref_id = str(h.get("refId", ""))

        # Look up OpenAlgo symbol from database using the broker symbol
        oa_symbol = get_oa_symbol(broker_symbol, exchange)
        tradingsymbol = oa_symbol if oa_symbol else broker_symbol

        # Convert paise -> rupees for price fields
        avg_price = (h.get("avgPrice", 0) or 0) / 100
        ltp = (h.get("lastTradedPrice", 0) or 0) / 100
        prev_close = (h.get("prevClose", 0) or 0) / 100
        invested_value = (h.get("investedValue", 0) or 0) / 100
        current_value = (h.get("currentValue", 0) or 0) / 100
        net_pnl = (h.get("netPnl", 0) or 0) / 100
        day_pnl = (h.get("dayPnl", 0) or 0) / 100

        mapped_holdings.append({
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "quantity": h.get("quantity", 0) or 0,
            "product": "CNC",  # Holdings are always delivery
            "average_price": round(avg_price, 2),
            "ltp": round(ltp, 2),
            "prev_close": round(prev_close, 2),
            "invested_value": round(invested_value, 2),
            "current_value": round(current_value, 2),
            "pnl": round(net_pnl, 2),
            "pnlpercent": round(h.get("netPnlChg", 0) or 0, 2),
            "day_pnl": round(day_pnl, 2),
            "day_pnl_chg": round(day_pnl, 2),
            "ltp_chg": round(h.get("netPnlChg", 0) or 0, 2),
            "ref_id": ref_id,
        })

    # Convert holdingStats paise -> rupees
    mapped_stats = {
        "invested_amount": round((raw_stats.get("investedAmount", 0) or 0) / 100, 2),
        "current_value": round((raw_stats.get("currentValue", 0) or 0) / 100, 2),
        "total_pnl": round((raw_stats.get("totalPnl", 0) or 0) / 100, 2),
        "total_pnl_chg": round(raw_stats.get("totalPnlChg", 0) or 0, 2),
        "day_pnl": round((raw_stats.get("dayPnl", 0) or 0) / 100, 2),
        "day_pnl_chg": round(raw_stats.get("dayPnlChg", 0) or 0, 2),
    }

    return {"holdings": mapped_holdings, "holding_stats": mapped_stats}


def calculate_portfolio_statistics(holdings_data):
    """
    Calculate portfolio statistics from Nubra's mapped holdings data.

    Reads from the 'holding_stats' key (already converted to rupees by map_portfolio_data).

    Returns dict with: totalholdingvalue, totalinvvalue, totalprofitandloss, totalpnlpercentage.
    """
    stats = holdings_data.get("holding_stats") if isinstance(holdings_data, dict) else None

    if not stats:
        return {
            "totalholdingvalue": 0,
            "totalinvvalue": 0,
            "totalprofitandloss": 0,
            "totalpnlpercentage": 0,
        }

    return {
        "totalholdingvalue": stats.get("current_value", 0),
        "totalinvvalue": stats.get("invested_amount", 0),
        "totalprofitandloss": stats.get("total_pnl", 0),
        "totalpnlpercentage": stats.get("total_pnl_chg", 0),
    }

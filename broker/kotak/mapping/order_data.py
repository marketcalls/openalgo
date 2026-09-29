from broker.kotak.mapping.transform_data import map_exchange
from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def _openalgo_symbol(row, exchange):
    """Resolve one Kotak row to its OpenAlgo symbol.

    Token first, then the broker trading symbol. The fallback is not
    belt-and-braces: Kotak populates "tok" on orderbook rows but leaves it as
    an empty string on tradebook rows, so a token-only lookup silently leaks
    the raw broker symbol ("YESBANK-EQ") into the UI, which then fails every
    downstream lookup that expects an OpenAlgo symbol. brsymbol in the master
    contract is pTrdSymbol (master_contract_db.py:155), i.e. exactly the value
    Kotak sends as trdSym.
    """
    token = str(row.get("tok") or "").strip()
    if token:
        mapped = get_symbol(token, exchange)
        if mapped:
            return mapped

    broker_symbol = row.get("trdSym") or row.get("sym") or ""
    if broker_symbol:
        mapped = get_oa_symbol(broker_symbol, exchange)
        if mapped:
            return mapped

    logger.debug(
        f"No OpenAlgo symbol for token '{token}' / symbol '{broker_symbol}' on {exchange}. "
        "Keeping the broker trading symbol."
    )
    return None


def map_order_data(order_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    # Check if 'data' is None
    # if order_data has key 'data' and its value is None

    if order_data["stat"] == "Not_Ok":
        logger.debug("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
        return order_data

    if order_data["data"] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.debug("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data["data"]

    if order_data:
        for order in order_data:
            exchange = map_exchange(order["exSeg"])
            order["exSeg"] = exchange

            symbol_from_db = _openalgo_symbol(order, exchange)
            if symbol_from_db:
                order["trdSym"] = symbol_from_db
    return order_data


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
            if order["trnsTp"] == "B":
                order["trnsTp"] = "BUY"
                total_buy_orders += 1
            elif order["trnsTp"] == "S":
                order["trnsTp"] = "SELL"
                total_sell_orders += 1

            # Normalize "trigger pending" to "open" for UI compatibility
            if order["ordSt"] == "trigger pending":
                order["ordSt"] = "open"

            # Count orders based on their status
            if order["ordSt"] == "complete":
                total_completed_orders += 1
            elif order["ordSt"] == "open":
                total_open_orders += 1
            elif order["ordSt"] == "rejected":
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
        if order.get("prcTp") == "MKT":
            order["prcTp"] = "MARKET"
        elif order.get("prcTp") == "L":
            order["prcTp"] = "LIMIT"
        elif order.get("prcTp") == "SL":
            order["prcTp"] = "SL"
        elif order.get("prcTp") == "SL-M":
            order["prcTp"] = "SL-M"

        # For limit orders, show the order price (prc) instead of average price (avgPrc)
        # avgPrc is only relevant for executed orders
        order_price = order.get("avgPrc", 0.0)
        if order.get("prcTp") in ["LIMIT", "SL"]:
            # If order is not executed/complete, use the limit price
            if order.get("ordSt") != "complete":
                order_price = order.get("prc", 0.0)

        transformed_order = {
            "symbol": order.get("trdSym", ""),
            "exchange": order.get("exSeg", ""),
            "action": order.get("trnsTp", ""),
            "quantity": order.get("qty", 0),
            "price": order_price,
            "trigger_price": order.get("trgPrc", 0.0),
            "pricetype": order.get("prcTp", ""),
            "product": order.get("prod", ""),
            "orderid": order.get("nOrdNo", ""),
            "order_status": order.get("ordSt", ""),
            "timestamp": order.get("ordEntTm", ""),
        }

        transformed_orders.append(transformed_order)

    return transformed_orders


def map_trade_data(trade_data):
    """
    Processes and modifies a list of order dictionaries based on specific conditions.

    Parameters:
    - order_data: A list of dictionaries, where each dictionary represents an order.

    Returns:
    - The modified order_data with updated 'tradingsymbol' and 'product' fields.
    """
    if trade_data["stat"] == "Not_Ok":
        logger.debug("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
        return trade_data
        # Check if 'data' is None
    if trade_data["data"] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        logger.debug("No data available.")
        trade_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        trade_data = trade_data["data"]

    if trade_data:
        for order in trade_data:
            exchange = map_exchange(order["exSeg"])
            order["exSeg"] = exchange

            symbol_from_db = _openalgo_symbol(order, exchange)
            if symbol_from_db:
                order["trdSym"] = symbol_from_db

            # Map transaction type regardless of symbol lookup result
            if order["trnsTp"] == "B":
                order["trnsTp"] = "BUY"
            elif order["trnsTp"] == "S":
                order["trnsTp"] = "SELL"
    logger.debug(f"Mapped Kotak tradebook: {trade_data}")
    return trade_data


def transform_tradebook_data(tradebook_data):
    transformed_data = []

    for trade in tradebook_data:
        transformed_trade = {
            "symbol": trade.get("trdSym", ""),
            "exchange": trade.get("exSeg", ""),
            "product": trade.get("prod", ""),
            "action": trade.get("trnsTp", ""),
            "quantity": trade.get("fldQty", 0),
            "average_price": trade.get("avgPrc", 0.0),
            "trade_value": float(trade.get("fldQty", 0.0)) * float(trade.get("avgPrc", 0.0)),
            "orderid": trade.get("nOrdNo", ""),
            # "flId" is Kotak's own per-fill trade ID (Kotak-Neo/kotak-neo-api-v2
            # docs/Trade_report.md - two fills under the same order carry two
            # distinct flId values). Previously dropped entirely, leaving no
            # stable per-fill identity for a consumer to dedup repeated
            # tradebook pulls against - only "orderid", shared by every fill
            # under one order. Emitted under OpenAlgo's own established key
            # "tradeid" (no underscore) - the documented tradebook contract
            # (docs/prompt/flow-import-format.md) and existing consumers
            # (services/telegram_bot_service*.py, broker/groww's own
            # adapter) already expect that exact key.
            "tradeid": trade.get("flId", ""),
            "timestamp": trade.get("exTm", ""),
        }
        transformed_data.append(transformed_trade)
    return transformed_data


def map_position_data(position_data):
    return map_order_data(position_data)


def _number(position, field):
    """One of Kotak's numeric position fields as a float.

    Kotak sends these as strings, and an optional one can arrive as null or
    empty on a row that never had that leg - float() raises on both, which
    would abort the entire position book over a single field on a single row.
    Anything unusable reads as zero, which is what the field's absence already
    meant.

    Args:
        position: One raw Kotak position row.
        field: The field name to read.

    Returns:
        float: The field's value, or 0.0 if it is absent, null or not a number.
    """
    try:
        return float(position.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def _price_factor(position):
    """The price scaling terms of Kotak's documented P&L formula.

    "multiplier * (genNum/genDen) * (prcNum/prcDen)", which scales the
    mark-to-market leg. Every one of them is "1" on the segments reachable
    through OpenAlgo today, so this is a no-op in practice - but they are the
    documented terms, and a field that arrives absent, unparseable or zero must
    not take the whole position book down with a ZeroDivisionError.

    Args:
        position: One raw Kotak position row.

    Returns:
        float: The combined scaling factor, 1.0 when Kotak sends nothing usable.
    """

    def term(field):
        return _number(position, field) or 1.0

    return (
        term("multiplier") * (term("genNum") / term("genDen")) * (term("prcNum") / term("prcDen"))
    )


def _carry_forward_amounts(position, factor):
    """What the carried-forward leg of a position actually cost.

    Kotak's cfBuyAmt/cfSellAmt do not hold that. The back office re-values
    every overnight leg at the previous day's settlement price and carries it
    in at that price, which is exactly what makes Kotak's documented
    "Profit N Loss" formula produce the day's mark-to-market rather than the
    P&L since entry. Dividing those amounts by the carried quantity therefore
    yields the settlement price, not an average - issue #2061, where five
    overnight short option legs each reported a different wrong average, four
    of them equal to the LTP to the paisa because an illiquid option's last
    trade *is* its previous close, and a book the broker's own app showed
    1.42 lakh down read as +13,765.50. The five ratios between the carried
    valuation and the real average were 2.51, 2.31, 3.12, 4.70 and 1.18: no
    scaling term explains that, only a re-valuation does.

    "upldPrc" is the one per-unit price in the payload not derived from that
    valuation. It is Kotak's spelling of Noren's "upldprc", documented there
    as "Average price uploaded with holdings" - the cost basis the back office
    pushes in alongside the carried quantity. On the account in #2061 it reads
    "0.00" on every carried leg, so the fallback below is what runs there;
    it is kept because it costs nothing and is the only field that could ever
    carry the number, on any account or any future version of the API.

    Falling back to cfBuyAmt/cfSellAmt is not a workaround for a missing
    lookup, it is the end of the road: a carried row holds seventeen fields
    and upldPrc is the only price among them, and Kotak's other endpoints are
    all current-day (orders, trades, order history by order number), so the
    cost basis of an overnight leg is not reachable through this API at all.
    The caller says so on the row rather than leaving the number to be read
    as an entry price.

    Args:
        position: One raw Kotak position row.
        factor: The row's price scaling factor, from _price_factor.

    Returns:
        tuple[float, float, bool]: The carried buy amount, the carried sell
        amount, and whether those amounts are Kotak's carry-forward valuation
        rather than what the leg cost.
    """
    cf_buy_qty = _number(position, "cfBuyQty")
    cf_sell_qty = _number(position, "cfSellQty")
    if not (cf_buy_qty or cf_sell_qty):
        return 0.0, 0.0, False

    carried_price = _number(position, "upldPrc")
    if carried_price > 0:
        return (
            cf_buy_qty * carried_price * factor,
            cf_sell_qty * carried_price * factor,
            False,
        )

    # No cost basis for the overnight leg, so Kotak's documented amounts are
    # all there is. They still give the correct *day's* P&L, which is what the
    # formula they belong to computes; what they cannot give is the P&L since
    # entry. Logged at debug rather than warning because the positions book is
    # polled - by the page, by every smart order - and a per-row warning on
    # each poll would bury the log it is meant to help read.
    logger.debug(
        "Kotak sent no upldPrc for the carried-forward leg of "
        f"{position.get('trdSym', '')}: its average price and P&L are Kotak's "
        "carry-forward valuation, i.e. the previous day's settlement price."
    )
    return _number(position, "cfBuyAmt"), _number(position, "cfSellAmt"), True


def transform_positions_data(positions_data):
    transformed_data = []
    for position in positions_data:
        # "_ltp" is a scratch field get_positions() stamps on before this
        # function runs (see order_api.py's _backfill_ltp) - Kotak's own
        # positions endpoint never returns a live price at all, open or closed,
        # unlike Zerodha's (which reads "last_price" directly from Kite here).
        # Kept unrounded for the P&L arithmetic below and rounded only on the
        # way out: CDS prices carry four decimals (USDINR ticks at 0.0025), so
        # marking a position against the display value costs real money on a
        # large one.
        ltp = _number(position, "_ltp")
        transformed_position = {
            "symbol": position.get("trdSym", ""),
            "exchange": position.get("exSeg", ""),
            "product": position.get("prod", ""),
            "quantity": int(
                (_number(position, "flBuyQty") - _number(position, "flSellQty"))
                + (_number(position, "cfBuyQty") - _number(position, "cfSellQty"))
            ),
            "average_price": position.get("avgnetprice", 0.0),
            # Matches Zerodha's "ltp" key/shape exactly so every consumer of
            # transform_positions_data can treat brokers uniformly - always
            # present, defaults to 0.0 if the backfill couldn't resolve a quote.
            "ltp": round(ltp, 2),
        }
        # Totals across the carried-forward leg and today's, which Kotak keeps
        # in separate fields. "quantity" above already sums both, so the average
        # has to as well: dividing today's amount by today's quantity reported
        # 0.00 for a position carried forward with no fills today, because
        # flBuyQty is 0 there and the branch fell through to the zero default.
        # That then also stopped the positions page marking the position to
        # market, since it only computes an unrealized P&L when average_price is
        # above zero - so a carried-forward holding showed no cost and no P&L.
        factor = _price_factor(position)
        cf_buy_amt, cf_sell_amt, carried_valuation = _carry_forward_amounts(position, factor)
        total_buy_amt = cf_buy_amt + _number(position, "buyAmt")
        total_sell_amt = cf_sell_amt + _number(position, "sellAmt")
        buy_qty = _number(position, "flBuyQty") + _number(position, "cfBuyQty")
        sell_qty = _number(position, "flSellQty") + _number(position, "cfSellQty")

        # Kotak's documented denominator is "Total Qty * multiplier *
        # (genNum/genDen) * (prcNum/prcDen)", not the quantity alone. The terms
        # are all "1" on the segments reachable through OpenAlgo today, so this
        # changes no number in practice - but it is what keeps the average and
        # the P&L below on one basis, since the mark-to-market leg scales by the
        # same factor. Without it a row with a multiplier of 2 reported an
        # average that no longer reproduced its own P&L.
        if transformed_position["quantity"] > 0 and buy_qty > 0:
            transformed_position["average_price"] = round(total_buy_amt / (buy_qty * factor), 2)
        elif transformed_position["quantity"] < 0 and sell_qty > 0:
            transformed_position["average_price"] = round(total_sell_amt / (sell_qty * factor), 2)
        elif transformed_position["quantity"] != 0:
            transformed_position["average_price"] = 0.0

        # Kotak's documented "Profit N Loss" formula (Positions.md), in full:
        #
        #   PnL = (Total Sell Amt - Total Buy Amt)
        #         + Net Qty * LTP * multiplier * (genNum/genDen) * (prcNum/prcDen)
        #
        # The amount difference is the realized leg; the Net Qty term marks an
        # open position to market. Kotak's positions endpoint returns no pnl
        # field of its own, so it has to be computed here. Writing the whole
        # formula rather than the two halves separately is deliberate: it
        # collapses to the realized-only form when Net Qty is 0, so a
        # fully-closed leg keeps reporting exactly what #1970's fix gave it.
        # The carried-forward amounts are included so a leg carried forward
        # reports its entire P&L, not just today's slice - which is only true
        # once those amounts are the leg's cost rather than Kotak's overnight
        # re-valuation of it, hence _carry_forward_amounts above (#2061).
        #
        # "pnl" is set on every row, open or closed, because that is the shape
        # the rest of the platform already expects from the other broker
        # adapters: the positions CSV writes a P&L column, and Flow's Position
        # Check reads pos.get("pnl", 0) for its pnl_above/pnl_below guards. With
        # the key absent on open positions those guards read 0 and could never
        # fire - which is the half a closed-position-only fix leaves broken,
        # since a P&L stop is only meaningful while the position is still open.
        realized = total_sell_amt - total_buy_amt
        net_qty = transformed_position["quantity"]

        # "or 0.0" normalizes negative zero. A leg marked at exactly the price
        # it was carried at lands on -0.0 through floating point (26160.0 +
        # -26160.000000000004), which serializes into the API response as
        # "-0.0" and reads as "-0.00" anywhere the value is formatted straight
        # out, such as the positions CSV. Four of the five rows in #2061 are
        # exactly that case.
        if not net_qty:
            transformed_position["pnl"] = round(realized, 2) or 0.0
        elif ltp:
            transformed_position["pnl"] = round(realized + net_qty * ltp * factor, 2) or 0.0
        else:
            # Open, but with no price to mark against - the LTP backfill in
            # order_api.py is best-effort and leaves the row alone when the
            # quotes call fails. The realized leg on its own is not a P&L: for
            # a freshly opened long it is the entire cost of the position and
            # would read as a total loss. Report 0.0, which is what every
            # consumer already fell back to while the key was missing.
            transformed_position["pnl"] = 0.0

        # Say on the row when its money numbers are measured from Kotak's
        # overnight re-valuation rather than from what the position cost, so a
        # caller has something to test instead of having to know that Kotak
        # carried legs behave differently. Present only in that case: absent is
        # the normal reading, on every other broker and on every Kotak row
        # whose average really is an entry price.
        #
        # It qualifies "pnl" as much as "average_price" - both come off the
        # same amounts - and it is set even on a fully-closed row, where
        # average_price is 0.00 by Kotak's own definition but the realized P&L
        # is still only today's slice of a position opened before today.
        #
        # Deliberately not a substitute for the average: reporting 0.00 there
        # would strip the Positions page of its live marking
        # (useLivePrice.ts gates on average_price > 0 and recomputes P&L from
        # it), leave P&L frozen between REST polls and P&L% reading 0.00%, and
        # would still be indistinguishable from a leg that is genuinely closed,
        # which Kotak also reports as 0.
        if carried_valuation:
            transformed_position["average_price_basis"] = "carry_forward_valuation"

        transformed_data.append(transformed_position)

    return transformed_data


def transform_holdings_data(holdings_data):
    transformed_data = []
    logger.debug("Holdings Data")
    logger.debug(f"{holdings_data}")
    for holding in holdings_data:
        transformed_position = {
            "symbol": holding.get("displaySymbol", ""),
            "exchange": holding.get("exchangeSegment", ""),
            "quantity": holding.get("quantity", 0),
            "product": holding.get("instrumentType", ""),
            # Kotak's holdings API does return a per-share averagePrice
            # directly -- unlike LTP (deliberately omitted, see order_api.py's
            # _backfill_ltp), so no workaround is needed here.
            "average_price": round(float(holding.get("averagePrice", 0.0)), 2),
            "pnl": round(
                (float(holding.get("mktValue", 0.0)) - float(holding.get("holdingCost", 0.0))), 2
            ),
            "pnlpercent": round(
                (
                    (float(holding.get("mktValue", 0.0)) - float(holding.get("holdingCost", 0.0)))
                    / float(holding.get("holdingCost", 0.0))
                    * 100
                )
                if float(holding.get("holdingCost", 0.0)) != 0
                else 0,
                2,
            ),
        }

        transformed_data.append(transformed_position)
    logger.debug("Holdings Data")
    logger.debug(f"{transformed_data}")
    return transformed_data


def map_portfolio_data(portfolio_data):
    """
    Processes and modifies a list of Portfolio dictionaries based on specific conditions and
    ensures both holdings and totalholding parts are transmitted in a single response.

    Parameters:
    - portfolio_data: A dictionary, where keys are 'holdings' and 'totalholding',
                      and values are lists/dictionaries representing the portfolio information.

    Returns:
    - The modified portfolio_data with 'product' fields changed for 'holdings' and 'totalholding' included.
    """
    # Check if 'data' is None or doesn't contain 'holdings'
    if portfolio_data.get("data") is None:
        logger.debug("No data available.")
        # Return an empty structure or handle this scenario as needed
        return {}

    # Directly work with 'data' for clarity and simplicity
    holdings = portfolio_data["data"]

    # Modify 'product' field for each holding if applicable

    for portfolio in holdings:
        token = portfolio["instrumentToken"]

        exchange = map_exchange(portfolio["exchangeSegment"])
        portfolio["exchangeSegment"] = exchange
        symbol_from_db = get_symbol(token, exchange)

        # Check if a symbol was found; if so, update the trading_symbol in the current order
        if symbol_from_db:
            portfolio["symbol"] = symbol_from_db
        if portfolio["instrumentType"] == "Equity":
            portfolio["instrumentType"] = "CNC"  # Modify 'product' field
        else:
            logger.debug("Kotak Portfolio - Product Value for Delivery Not Found or Changed.")

    # The function already works with 'data', which includes 'holdings' and 'totalholding',
    # so we can return 'data' directly without additional modifications.

    return holdings


def calculate_portfolio_statistics(holdings_data):
    totalholdingvalue = sum(item["mktValue"] for item in holdings_data)
    totalinvvalue = sum(item["holdingCost"] for item in holdings_data)
    totalprofitandloss = sum(item["mktValue"] - item["holdingCost"] for item in holdings_data)

    totalpnlpercentage = (totalprofitandloss / totalinvvalue) * 100 if totalinvvalue != 0 else 0

    # To avoid division by zero in the case when total_investment_value is 0
    totalpnlpercentage = round(totalpnlpercentage, 2)

    return {
        "totalholdingvalue": totalholdingvalue,
        "totalinvvalue": totalinvvalue,
        "totalprofitandloss": totalprofitandloss,
        "totalpnlpercentage": totalpnlpercentage,
    }

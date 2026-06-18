from database.token_db import get_oa_symbol, get_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def map_order_data(order_data):
    """Normalize raw OrderBook rows: resolve OpenAlgo symbol + product/pricetype."""
    if order_data is None or (isinstance(order_data, dict) and (order_data.get("stat") == "Not_Ok")):
        logger.warning("No order data available.")
        order_data = {}

    if order_data:
        for order in order_data:
            # Capture broker rejection reason for rejected orders
            if str(order.get("status", "")).upper() == "REJECTED":
                logger.debug(
                    f"Rejected order {order.get('norenordno', '')} "
                    f"({order.get('tsym', '')}): {order.get('rejreason', 'no reason provided')}"
                )

            symboltoken = order["token"]
            exchange = order["exch"]
            symbol_from_db = get_symbol(symboltoken, exchange)

            if symbol_from_db:
                order["tsym"] = symbol_from_db
                if (order["exch"] in ("NSE", "BSE")) and order["prd"] == "C":
                    order["prd"] = "CNC"
                elif order["prd"] == "I":
                    order["prd"] = "MIS"
                elif order["exch"] in ["NFO", "MCX", "BFO", "CDS"] and order["prd"] == "M":
                    order["prd"] = "NRML"

                if order["prctyp"] == "MKT":
                    order["prctyp"] = "MARKET"
                elif order["prctyp"] == "LMT":
                    order["prctyp"] = "LIMIT"
                elif order["prctyp"] == "SL-MKT":
                    order["prctyp"] = "SL-M"
                elif order["prctyp"] == "SL-LMT":
                    order["prctyp"] = "SL"

                # Prefer average fill price when present
                if order.get("avgprc") and float(order.get("avgprc", 0)) > 0:
                    order["prc"] = order["avgprc"]
                elif order["prctyp"] in ["MARKET", "SL-M"] and float(order.get("prc", 0)) == 0.0:
                    rprc = order.get("rprc", 0)
                    if rprc and float(rprc) > 0:
                        order["prc"] = rprc
            else:
                logger.warning(
                    f"Symbol not found for token {symboltoken} and exchange {exchange}."
                )

    return order_data


def calculate_order_statistics(order_data):
    """Count buy/sell/completed/open/rejected orders; also expands B/S to BUY/SELL."""
    total_buy_orders = total_sell_orders = 0
    total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            if order["trantype"] == "B":
                order["trantype"] = "BUY"
                total_buy_orders += 1
            elif order["trantype"] == "S":
                order["trantype"] = "SELL"
                total_sell_orders += 1

            if order["status"] == "COMPLETE":
                total_completed_orders += 1
            elif order["status"] == "OPEN":
                total_open_orders += 1
            elif order["status"] == "REJECTED":
                total_rejected_orders += 1

    return {
        "total_buy_orders": total_buy_orders,
        "total_sell_orders": total_sell_orders,
        "total_completed_orders": total_completed_orders,
        "total_open_orders": total_open_orders,
        "total_rejected_orders": total_rejected_orders,
    }


def transform_order_data(orders):
    """Convert normalized OrderBook rows into the OpenAlgo common orderbook shape."""
    if orders is None:
        logger.warning("No order data available - orders is None")
        return []
    if not orders:
        return []

    transformed_orders = []
    for order in orders:
        if not isinstance(order, dict):
            logger.warning(f"Expected dict, found {type(order)}. Skipping.")
            continue

        transformed_orders.append({
            "symbol": order.get("tsym", ""),
            "exchange": order.get("exch", ""),
            "action": order.get("trantype", ""),
            "quantity": order.get("qty", 0),
            "price": order.get("prc", 0.0),
            "trigger_price": order.get("trgprc", 0.0),
            "pricetype": order.get("prctyp", ""),
            "product": order.get("prd", ""),
            "orderid": order.get("norenordno", ""),
            "order_status": order.get("status", "").lower(),
            "timestamp": order.get("norentm", ""),
        })

    return transformed_orders


def map_trade_data(trade_data):
    """Normalize raw TradeBook rows."""
    if trade_data is None or (isinstance(trade_data, dict) and (trade_data.get("stat") == "Not_Ok")):
        logger.warning("No trade data available.")
        trade_data = {}

    if trade_data:
        for order in trade_data:
            symbol = order["tsym"]
            exchange = order["exch"]
            symbol_from_db = get_oa_symbol(symbol, exchange)

            if symbol_from_db:
                order["tsym"] = symbol_from_db
                if (order["exch"] in ("NSE", "BSE")) and order["prd"] == "C":
                    order["prd"] = "CNC"
                elif order["prd"] == "I":
                    order["prd"] = "MIS"
                elif order["exch"] in ["NFO", "MCX", "BFO", "CDS"] and order["prd"] == "M":
                    order["prd"] = "NRML"

                if order["trantype"] == "B":
                    order["trantype"] = "BUY"
                elif order["trantype"] == "S":
                    order["trantype"] = "SELL"
            else:
                logger.warning(f"Unable to find symbol {symbol} on {exchange}.")

    return trade_data


def transform_tradebook_data(tradebook_data):
    """Convert normalized TradeBook rows into the OpenAlgo common tradebook shape."""
    transformed_data = []
    for trade in tradebook_data:
        avg_price = round(float(trade.get("avgprc", 0)), 2)
        quantity = int(float(trade.get("qty", 0)))
        trade_value = round(avg_price * quantity, 2)

        transformed_data.append({
            "symbol": trade.get("tsym", ""),
            "exchange": trade.get("exch", ""),
            "product": trade.get("prd", ""),
            "action": trade.get("trantype", ""),
            "quantity": quantity,
            "average_price": avg_price,
            "trade_value": trade_value,
            "orderid": trade.get("norenordno", ""),
            "timestamp": trade.get("norentm", ""),
        })
    return transformed_data


def map_position_data(position_data):
    """Normalize raw PositionBook rows."""
    if position_data is None or (
        isinstance(position_data, dict) and (position_data.get("stat") == "Not_Ok")
    ):
        logger.warning("No position data available.")
        position_data = {}

    if position_data:
        for order in position_data:
            symbol = order["tsym"]
            exchange = order["exch"]
            symbol_from_db = get_oa_symbol(symbol, exchange)

            if symbol_from_db:
                order["tsym"] = symbol_from_db
                if (order["exch"] in ("NSE", "BSE")) and order["prd"] == "C":
                    order["prd"] = "CNC"
                elif order["prd"] == "I":
                    order["prd"] = "MIS"
                elif order["exch"] in ["NFO", "MCX", "BFO", "CDS"] and order["prd"] == "M":
                    order["prd"] = "NRML"
            else:
                logger.warning(f"Unable to find symbol {symbol} on {exchange}.")

    return position_data


def transform_positions_data(positions_data):
    """Convert normalized PositionBook rows into the OpenAlgo common positions shape."""
    transformed_data = []
    for position in positions_data:
        realized_pnl = float(position.get("rpnl", 0))
        unrealized_pnl = float(position.get("urmtom", 0))

        if unrealized_pnl == 0 and float(position.get("netqty", 0)) != 0:
            price_factor = float(position.get("prcftr", 1))
            ltp = float(position.get("lp", 0))
            avg_price = float(position.get("netavgprc", 0))
            quantity = float(position.get("netqty", 0))
            unrealized_pnl = (ltp - avg_price) * quantity * price_factor

        total_pnl = realized_pnl + unrealized_pnl

        transformed_data.append({
            "symbol": position.get("tsym", ""),
            "exchange": position.get("exch", ""),
            "product": position.get("prd", ""),
            "quantity": position.get("netqty", 0),
            "average_price": position.get("netavgprc", 0.0),
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "ltp": position.get("lp", 0.0),
            "pnl": round(total_pnl, 2),
        })
    return transformed_data


def map_portfolio_data(portfolio_data):
    """Normalize raw Holdings rows (each carries an ``exch_tsym`` list)."""
    if not portfolio_data or not isinstance(portfolio_data, list):
        logger.info("No holdings data available or incorrect format.")
        return []

    for portfolio in portfolio_data:
        if portfolio.get("stat") != "Ok":
            logger.info(f"Holdings error: {portfolio.get('emsg', 'Unknown error')}")
            continue

        for exch_tsym in portfolio.get("exch_tsym", []):
            symbol = exch_tsym.get("tsym", "")
            exchange = exch_tsym.get("exch", "")
            symbol_from_db = get_oa_symbol(symbol, exchange)
            if symbol_from_db:
                exch_tsym["tsym"] = symbol_from_db
            else:
                logger.info(f"Holdings symbol {symbol} on {exchange} not found.")

    return portfolio_data


def calculate_portfolio_statistics(holdings_data):
    """Aggregate holdings totals from the NSE leg of each holding."""
    totalholdingvalue = 0
    totalinvvalue = 0
    totalprofitandloss = 0
    totalpnlpercentage = 0

    if not holdings_data or not isinstance(holdings_data, list):
        return {
            "totalholdingvalue": totalholdingvalue,
            "totalinvvalue": totalinvvalue,
            "totalprofitandloss": totalprofitandloss,
            "totalpnlpercentage": totalpnlpercentage,
        }

    for holding in holdings_data:
        if holding.get("stat") != "Ok":
            continue

        nse_entry = next(
            (exch for exch in holding.get("exch_tsym", []) if exch.get("exch") == "NSE"), None
        )
        if not nse_entry:
            continue

        quantity = float(holding.get("holdqty", 0)) + max(
            float(holding.get("npoadqty", 0)), float(holding.get("dpqty", 0))
        )
        upload_price = float(holding.get("upldprc", 0))

        inv_value = quantity * upload_price
        totalinvvalue += inv_value

        holdqty = float(holding.get("holdqty", 0))
        btstqty = float(holding.get("btstqty", 0))
        brkcolqty = float(holding.get("brkcolqty", 0))
        unplgdqty = float(holding.get("unplgdqty", 0))
        benqty = float(holding.get("benqty", 0))
        npoadqty_val = float(holding.get("npoadqty", 0))
        dpqty = float(holding.get("dpqty", 0))
        usedqty = float(holding.get("usedqty", 0))

        valuation = (
            (btstqty + holdqty + brkcolqty + unplgdqty + benqty + max(npoadqty_val, dpqty))
            - usedqty
        ) * upload_price
        totalholdingvalue += valuation

    totalpnlpercentage = (totalprofitandloss / totalinvvalue) * 100 if totalinvvalue != 0 else 0

    return {
        "totalholdingvalue": totalholdingvalue,
        "totalinvvalue": totalinvvalue,
        "totalprofitandloss": totalprofitandloss,
        "totalpnlpercentage": totalpnlpercentage,
    }


def transform_holdings_data(holdings_data):
    """Convert normalized Holdings into the OpenAlgo common holdings shape (NSE leg)."""
    transformed_data = []
    if isinstance(holdings_data, list):
        for holding in holdings_data:
            nse_entries = [
                exch for exch in holding.get("exch_tsym", []) if exch.get("exch") == "NSE"
            ]
            for exch_tsym in nse_entries:
                transformed_data.append({
                    "symbol": exch_tsym.get("tsym", ""),
                    "exchange": exch_tsym.get("exch", ""),
                    "quantity": int(holding.get("holdqty", 0))
                    + max(int(holding.get("npoadqty", 0)), int(holding.get("dpqty", 0))),
                    "product": exch_tsym.get("product", "CNC"),
                    "average_price": float(holding.get("upldprc", 0.0)),
                    "pnl": 0.0,
                    "pnlpercent": 0.0,
                })
    return transformed_data

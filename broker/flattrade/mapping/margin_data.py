# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Flattrade GetBasketMargin API

from broker.flattrade.mapping.transform_data import map_order_type, map_product_type
from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


class MarginLegUnresolved(ValueError):
    """A basket leg's symbol could not be found or prepared.

    Raised rather than skipped: dropping one leg of a basket would silently
    report the margin of a different basket (issue #2156).
    """


class MarginPriceUnavailable(ValueError):
    """No positive price could be found for a MARKET/SL-M leg.

    GetBasketMargin needs a non-zero prc, so such a leg cannot be priced.
    Raised rather than skipped: dropping one leg of a basket would silently
    report the margin of a different basket.
    """


def _positive(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return number if number > 0 else 0.0


def _apply_mpp(position, auth_token):
    """
    Convert MARKET/SL-M to LMT/SL-LMT with a protected price for basket margin.

    GetBasketMargin rejects MKT/SL-MKT price types and a zero price, so
    MARKET/SL-M legs go out as LMT/SL-LMT with a positive protected price:
      - MARKET -> protected off the LTP; if no LTP, the caller's own price.
      - SL-M   -> protected off the trigger, so the limit stays on the correct
                  side of trgprc (below it for a SELL, above it for a BUY);
                  the LTP is used only when no trigger was given. If the
                  protection cannot be computed, the trigger itself is used.
    The protection is rounded to the quote's tick size, else the SymToken
    tick size; with neither, the base price is sent unprotected.
    Raises MarginPriceUnavailable when none of these is positive.
    """
    pricetype = position.get("pricetype", "MARKET")
    action = position["action"].upper()
    price = str(position.get("price", 0) or 0)
    order_type = map_order_type(pricetype)

    if pricetype not in ("MARKET", "SL-M"):
        return order_type, price

    original_type = pricetype
    converted_order_type = "LMT" if original_type == "MARKET" else "SL-LMT"
    trigger = _positive(position.get("trigger_price"))
    fallback = _positive(position.get("price")) if original_type == "MARKET" else trigger

    logger.info(
        f"Margin MPP: {original_type} detected Symbol={position['symbol']}, "
        f"Exchange={position['exchange']}, Action={action}"
    )

    reference = trigger if original_type == "SL-M" else 0.0
    tick_size = None
    instrument_type = get_instrument_type_from_symbol(position["symbol"])
    try:
        if auth_token:
            from broker.flattrade.api.data import BrokerData

            quote = BrokerData(auth_token).get_quotes(position["symbol"], position["exchange"])
            ltp = _positive(quote.get("ltp"))
            tick_size = quote.get("tick_size")
            logger.info(
                f"Margin MPP Quote: Symbol={position['symbol']}, LTP={ltp}, "
                f"TickSize={tick_size}, InstrumentType={instrument_type}"
            )
            if not reference:
                reference = ltp
        else:
            logger.warning(f"Margin MPP: no auth token for Symbol={position['symbol']}")

        if not tick_size:
            # The quote omits "ti" at times. calculate_protected_price would
            # then round to paise, which is off-tick on a 0.05-tick contract
            # and gets the basket rejected, so read the tick from SymToken.
            info = get_symbol_info(position["symbol"], position["exchange"])
            tick_size = getattr(info, "tick_size", None)

        if reference and not tick_size:
            # No tick size anywhere: send the base price unprotected. An LTP
            # or a caller's trigger is already a valid tick.
            logger.warning(
                f"Margin MPP: no tick size for Symbol={position['symbol']}; "
                f"converting {original_type}->{converted_order_type} at {reference} unprotected"
            )
            return converted_order_type, str(reference)

        if reference:
            protected = calculate_protected_price(
                price=reference,
                action=action,
                symbol=position["symbol"],
                instrument_type=instrument_type,
                tick_size=tick_size,
            )
            if _positive(protected):
                logger.info(
                    f"Margin MPP Converted: {original_type}->{converted_order_type}, "
                    f"Base={reference}, FinalPrice={protected}"
                )
                return converted_order_type, str(protected)
    except Exception as e:
        logger.error(f"Margin MPP Error: Symbol={position['symbol']}, Error={e}")

    if fallback:
        logger.warning(
            f"Margin MPP: no protected price for Symbol={position['symbol']}; "
            f"converting {original_type}->{converted_order_type} at supplied price={fallback}"
        )
        return converted_order_type, str(fallback)

    raise MarginPriceUnavailable(
        f"Could not get a live price for {position['symbol']}. "
        "Enter a price for this leg, or try again in a moment."
    )


def _build_order(position, auth_token):
    oa_symbol = position["symbol"]
    exchange = position["exchange"]
    br_symbol = get_br_symbol(oa_symbol, exchange)
    if not br_symbol:
        logger.warning(f"Symbol not found for: {oa_symbol} on exchange: {exchange}")
        return None
    if "&" in br_symbol:
        br_symbol = br_symbol.replace("&", "%26")

    prctyp, prc = _apply_mpp(position, auth_token)

    return {
        "exch": exchange,
        "tsym": br_symbol,
        "qty": str(int(position["quantity"])),
        "prc": prc,
        "trgprc": str(position.get("trigger_price", 0) or 0),
        "prd": map_product_type(position.get("product", "NRML")),
        "trantype": "B" if position["action"].upper() == "BUY" else "S",
        "prctyp": prctyp,
    }


def transform_margin_positions(positions, userid, auth_token=None):
    orders = []
    unresolved = []
    for position in positions:
        try:
            order = _build_order(position, auth_token)
        except MarginPriceUnavailable:
            raise
        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            order = None
        if order:
            orders.append(order)
        else:
            unresolved.append(f"{position.get('symbol')} ({position.get('exchange')})")
    if unresolved:
        raise MarginLegUnresolved(
            f"Could not prepare these legs for the margin check: {', '.join(unresolved)}. "
            "Check the symbol, exchange and expiry date."
        )
    if not orders:
        return {"uid": userid, "actid": userid, "basketlists": []}

    first = orders[0]
    rest = orders[1:]
    return {
        "uid": userid,
        "actid": userid,
        "exch": first["exch"],
        "tsym": first["tsym"],
        "qty": first["qty"],
        "prc": first["prc"],
        "trgprc": first["trgprc"],
        "prd": first["prd"],
        "trantype": first["trantype"],
        "prctyp": first["prctyp"],
        "basketlists": rest,
    }


def _amount(value):
    """Noren sends amounts as strings; a missing amount reads as 0."""
    if value in (None, ""):
        return 0.0
    return float(value)


def parse_margin_response(response_data, existing_margin_used=0.0):
    """
    Map a GetBasketMargin response to OpenAlgo's margin format.

    Both GetBasketMargin figures are account totals, not the basket alone:
      marginused      -> basket margin before hedge benefit + existing usage
      marginusedtrade -> margin after the trade (hedge benefit applied)
                         + existing usage
    The Noren calculation note (shoonya-api-docs/07-order-and-trade-
    information.md, "calculation") gives the basket's own figure — what
    Flattrade's web basket shows with "Include existing margin" unticked — as
        post trade margin = marginusedtrade(GetBasketMargin) - marginused(Limits)
    so the caller passes Limits.marginused as existing_margin_used (issue #2156).
    Reporting marginusedtrade unadjusted added the margin already blocked by
    open positions and orders to every basket.

    span/exposure stay 0: Flattrade gives no breakdown.
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}
        if response_data.get("stat") != "Ok":
            error_message = (
                response_data.get("emsg")
                or response_data.get("remarks")
                or "Failed to calculate margin"
            )
            return {"status": "error", "message": error_message}
        if response_data.get("marginusedtrade") in (None, ""):
            # marginused is the pre-hedge total; reporting it in its place
            # would quote a calendar spread at naked-leg margin again.
            logger.warning(f"GetBasketMargin returned no marginusedtrade: {response_data}")
            return {"status": "error", "message": "Broker did not return the post-trade margin"}
        post_trade = _amount(response_data["marginusedtrade"]) - existing_margin_used
        return {
            "status": "success",
            "data": {
                "total_margin_required": round(post_trade, 2),
                "span_margin": 0,
                "exposure_margin": 0,
            },
        }
    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}


def parse_limits_margin_used(limits_data):
    """
    Read marginused from a Limits response, or None when the call failed.

    A successful reply without marginused is read as 0, as funds.py already
    reads it. GetBasketMargin is held to a stricter rule (a missing
    marginusedtrade is an error, see parse_margin_response) because it sends
    zero figures explicitly: a live reply on 2026-11-11 carried
    'marginusedprev': '0.00'.
    """
    if not isinstance(limits_data, dict) or limits_data.get("stat") != "Ok":
        return None
    return _amount(limits_data.get("marginused"))

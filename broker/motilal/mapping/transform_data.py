# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Motilal Oswal Parameters - See Motilal_Oswal.md documentation

from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)


def map_exchange(exchange):
    """
    Maps OpenAlgo exchange names to Motilal Oswal exchange names.

    OpenAlgo uses: NSE, BSE, NFO, CDS, MCX, BFO
    Motilal uses: NSE, BSE, NSEFO, NSECD, MCX, BSEFO
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSEFO",
        "CDS": "NSECD",
        "MCX": "MCX",
        "BFO": "BSEFO",
        "NSEFO": "NSEFO",  # Already in Motilal format
        "NSECD": "NSECD",  # Already in Motilal format
        "BSEFO": "BSEFO",  # Already in Motilal format
    }
    return exchange_mapping.get(exchange, exchange)


def reverse_map_exchange(exchange):
    """
    Reverse maps Motilal Oswal exchange names to OpenAlgo exchange names.
    """
    reverse_exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NSEFO": "NFO",
        "NSECD": "CDS",
        "MCX": "MCX",
        "BSEFO": "BFO",
    }
    return reverse_exchange_mapping.get(exchange, exchange)


def transform_data(data, token, auth_token=None):
    """
    Transforms the OpenAlgo API request structure to Motilal Oswal expected structure.

    Motilal blocks MARKET / SL-M orders on vendor (algo) channels with errorcode M01108
    ("Cannot place Market orders for Algo Orders"). To keep order intent intact we apply
    Market Price Protection (MPP) and convert:
        MARKET -> LIMIT  at LTP +/- slab%
        SL-M   -> STOPLOSS (SL) at trigger +/- slab%
    """
    # Note: no get_br_symbol() lookup here. Motilal identifies the instrument by
    # `symboltoken` alone (doc 14), so resolving the broker tradingsymbol was a
    # per-order database round-trip whose result was never sent.
    openalgo_exchange = data["exchange"]
    motilal_exchange = map_exchange(openalgo_exchange)
    action = data["action"].upper()
    pricetype = data["pricetype"]

    price = data.get("price", "0")
    trigger_price = data.get("trigger_price", "0")
    order_type = map_order_type(pricetype)

    # MPP for MARKET orders: fetch LTP, compute protected limit price
    if pricetype == "MARKET":
        logger.info(
            f"MPP: MARKET order detected for Symbol={data['symbol']}, "
            f"Exchange={openalgo_exchange}, Action={action}"
        )
        try:
            if auth_token:
                from broker.motilal.api.data import BrokerData

                broker_data = BrokerData(auth_token)
                quote_data = broker_data.get_quotes(data["symbol"], openalgo_exchange)
                ltp = float(quote_data.get("ltp", 0)) if quote_data else 0

                if ltp > 0:
                    instrument_type = get_instrument_type_from_symbol(data["symbol"])
                    tick_size = None
                    symbol_info = get_symbol_info(data["symbol"], openalgo_exchange)
                    if symbol_info and symbol_info.tick_size:
                        tick_size = symbol_info.tick_size

                    protected_price = calculate_protected_price(
                        price=ltp,
                        action=action,
                        symbol=data["symbol"],
                        instrument_type=instrument_type,
                        tick_size=tick_size,
                    )
                    price = str(protected_price)
                    order_type = "LIMIT"
                    logger.info(
                        f"MPP Conversion Complete: Symbol={data['symbol']}, "
                        f"OrderType=MARKET->LIMIT, FinalPrice={protected_price}"
                    )
                else:
                    logger.warning(
                        f"MPP: LTP unavailable for {data['symbol']}, sending MARKET as-is"
                    )
            else:
                logger.warning(
                    f"MPP: No auth_token for {data['symbol']}, cannot fetch LTP"
                )
        except Exception as e:
            logger.error(
                f"MPP Error for MARKET {data['symbol']}: {e}. Sending MARKET as-is"
            )

    # MPP for SL-M orders: convert to STOPLOSS with protected limit price
    elif pricetype == "SL-M":
        try:
            tp = float(trigger_price)
        except (TypeError, ValueError):
            tp = 0.0
        if tp > 0:
            try:
                instrument_type = get_instrument_type_from_symbol(data["symbol"])
                tick_size = None
                symbol_info = get_symbol_info(data["symbol"], openalgo_exchange)
                if symbol_info and symbol_info.tick_size:
                    tick_size = symbol_info.tick_size

                protected_price = calculate_protected_price(
                    price=tp,
                    action=action,
                    symbol=data["symbol"],
                    instrument_type=instrument_type,
                    tick_size=tick_size,
                )
                price = str(protected_price)
                order_type = "STOPLOSS"
                logger.info(
                    f"MPP Conversion Complete: Symbol={data['symbol']}, "
                    f"OrderType=SL-M->STOPLOSS, Trigger={tp}, LimitPrice={protected_price}"
                )
            except Exception as e:
                logger.error(
                    f"MPP Error for SL-M {data['symbol']}: {e}. Sending SL-M as-is"
                )
        else:
            logger.warning(
                f"MPP: trigger_price=0 for SL-M {data['symbol']}, sending as-is"
            )

    # Basic mapping for Motilal Oswal
    transformed = {
        "apikey": data["apikey"],
        "symboltoken": token,
        "buyorsell": action,  # Motilal uses 'buyorsell' instead of 'transactiontype'
        "exchange": motilal_exchange,
        "ordertype": order_type,
        "producttype": map_product_type(
            data["product"], openalgo_exchange
        ),  # Pass OpenAlgo exchange for context
        "orderduration": "DAY",  # Motilal uses 'orderduration' instead of 'duration'
        "price": price,
        "triggerprice": trigger_price,
        "disclosedquantity": data.get("disclosed_quantity", "0"),
        "quantity": data["quantity"],
        "amoorder": "N",  # AMO-Order (Y or N)
        "algoid": "",  # Algo Id or Blank for Non-Algo Orders
        "goodtilldate": "",  # DD-MMM-YYYY format if GTD
        "tag": "",  # Echo back to identify order (max 10 characters)
        "participantcode": "",  # Participant Code if applicable
    }

    return transformed


def transform_modify_order_data(data, token, lastmodifiedtime, qtytradedtoday):
    """
    Transforms modify order data for Motilal Oswal API.
    Motilal uses different field names compared to Angel Broking.

    Args:
        data: OpenAlgo modify order request data
        token: Symbol token for the instrument
        lastmodifiedtime: Last modified time from order book (dd-MMM-yyyy HH:mm:ss format)
        qtytradedtoday: Quantity traded today from order book

    Returns:
        Dict containing Motilal-formatted modify order request
    """
    return {
        "uniqueorderid": data["orderid"],  # Motilal uses uniqueorderid
        "newordertype": map_order_type(data["pricetype"]),
        "neworderduration": "DAY",  # Motilal uses neworderduration
        "newprice": float(data.get("price", "0")),
        "newtriggerprice": float(data.get("trigger_price", "0")),
        "newquantityinlot": int(data["quantity"]),
        "newdisclosedquantity": int(data.get("disclosed_quantity", "0")),
        "newgoodtilldate": "",
        "lastmodifiedtime": lastmodifiedtime,  # Fetched from order book
        "qtytradedtoday": qtytradedtoday,  # Fetched from order book
    }


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Motilal Oswal order type.
    Motilal supports: LIMIT, MARKET, STOPLOSS
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLOSS",
        "SL-M": "STOPLOSS",
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


# ---------------------------------------------------------------------------
# Product type mapping
#
# Motilal product vocabulary (doc 32-parameters-constants.md):
#     NORMAL, DELIVERY, VALUEPLUS, SELLFROMDP, BTST
# FAQ Q7 confirms the API accepts Normal / Delivery / Value Plus.
# FAQ Q10 defines the semantics:
#     NORMAL    -> "NRML (Normal): You can carry forward positions to the next
#                   trading day" i.e. the CARRY FORWARD product  -> OpenAlgo NRML
#     VALUEPLUS -> "Stands for Margin Intraday Square Off (MIS)"  -> OpenAlgo MIS
#     DELIVERY  -> cash delivery                                  -> OpenAlgo CNC
# SELLFROMDP (sell out of demat holdings) and BTST (buy today, sell tomorrow)
# are delivery-settled cash products with no distinct OpenAlgo equivalent, so
# they read back as CNC. They are never produced by the forward map.
#
# map_product_type() and reverse_map_product_type() are inverses of each other
# per exchange, with ONE documented exception (see the F&O note below).
# ---------------------------------------------------------------------------

_CASH_EXCHANGES = ("NSE", "BSE")
_FO_EXCHANGES = ("NFO", "MCX", "CDS", "BFO", "NCDEX", "NSEFO", "NSECD", "BSEFO")


def map_product_type(product, exchange=None):
    """
    Maps an OpenAlgo product type to the Motilal Oswal product type for `exchange`.

    Cash segment (NSE, BSE) - a true bijection:
        CNC  -> DELIVERY
        MIS  -> VALUEPLUS
        NRML -> NORMAL      (carry forward; doc 17 shows a BSE cash order with
                             producttype "NORMAL", so NORMAL is valid on cash)

    F&O segment (NFO, CDS, MCX, BFO):
        NRML -> NORMAL
        MIS  -> NORMAL      <-- COLLAPSE
        CNC  -> NORMAL      <-- COLLAPSE

        All three OpenAlgo products are placed as NORMAL on derivatives, so the
        reverse direction cannot be unique. reverse_map_product_type() resolves
        NORMAL -> NRML (the carry-forward product per FAQ Q10), which means an
        F&O order sent as MIS or CNC reads back from the order/position book as
        NRML. Only NRML round-trips on F&O; this is a limitation of the forward
        collapse, not of the reverse map.

    Args:
        product: OpenAlgo product type (CNC, MIS, NRML)
        exchange: OpenAlgo exchange name (NSE, BSE, NFO, CDS, MCX, BFO)

    Returns:
        A Motilal product constant from doc 32.
    """
    product = str(product or "").upper()
    exchange = str(exchange or "").upper() or None

    if exchange in _CASH_EXCHANGES:
        cash_mapping = {
            "CNC": "DELIVERY",  # cash delivery
            "MIS": "VALUEPLUS",  # margin intraday square off
            "NRML": "NORMAL",  # carry forward
        }
        return cash_mapping.get(product, "VALUEPLUS")

    if exchange in _FO_EXCHANGES:
        # Derivatives: everything is placed as NORMAL (see COLLAPSE note above).
        fo_mapping = {
            "NRML": "NORMAL",
            "MIS": "NORMAL",
            "CNC": "NORMAL",
        }
        return fo_mapping.get(product, "NORMAL")

    # No / unknown exchange context: map on product semantics alone. This is the
    # exact inverse of the no-exchange branch of reverse_map_product_type().
    default_mapping = {
        "CNC": "DELIVERY",
        "MIS": "VALUEPLUS",
        "NRML": "NORMAL",
    }
    return default_mapping.get(product, "VALUEPLUS")


def reverse_map_product_type(product, exchange=None):
    """
    Reverse maps a Motilal Oswal product type to the OpenAlgo product type.

    This is the single source of truth for reading Motilal products back out of
    the order book, trade book, position book and holdings. Do not inline this
    mapping anywhere else.

    Cash segment (NSE, BSE) - exact inverse of map_product_type():
        DELIVERY   -> CNC
        VALUEPLUS  -> MIS
        NORMAL     -> NRML
        SELLFROMDP -> CNC   (sold out of demat holdings; delivery settled)
        BTST       -> CNC   (buy today sell tomorrow; delivery settled)
        MTF        -> NRML  (margin trading facility; funded carry forward)

    F&O segment (NFO, CDS, MCX, BFO):
        NORMAL     -> NRML  (carry forward product, FAQ Q10)
        VALUEPLUS  -> MIS   (margin intraday square off, FAQ Q10)
        DELIVERY   -> CNC   (defensive; not expected on derivatives)
        SELLFROMDP -> CNC
        BTST       -> CNC
        MTF        -> NRML

    Args:
        product: Motilal product type (NORMAL, DELIVERY, VALUEPLUS, ...)
        exchange: OpenAlgo exchange name (NSE, BSE, NFO, CDS, MCX, BFO)

    Returns:
        An OpenAlgo product type (CNC, MIS, NRML). Unknown Motilal products fall
        back to MIS so the books never carry broker-native vocabulary.
    """
    product = str(product or "").upper()
    # `exchange` is part of the contract (callers pass the OpenAlgo exchange and
    # it keeps the signature symmetric with map_product_type) but the reverse
    # direction is decided by the Motilal product name alone.
    _ = exchange

    common_mapping = {
        "DELIVERY": "CNC",
        "VALUEPLUS": "MIS",
        "NORMAL": "NRML",
        "SELLFROMDP": "CNC",
        "BTST": "CNC",
        "MTF": "NRML",
    }

    # The Motilal product name alone is unambiguous in the reverse direction, so
    # the same table serves cash, F&O and a missing/unknown exchange.
    return common_mapping.get(product, "MIS")

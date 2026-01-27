# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Motilal Oswal Parameters - See Motilal_Oswal.md documentation

from database.token_db import get_br_symbol


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


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Motilal Oswal expected structure.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    openalgo_exchange = data["exchange"]
    motilal_exchange = map_exchange(openalgo_exchange)

    # Basic mapping for Motilal Oswal
    transformed = {
        "apikey": data["apikey"],
        "symboltoken": token,
        "buyorsell": data[
            "action"
        ].upper(),  # Motilal uses 'buyorsell' instead of 'transactiontype'
        "exchange": motilal_exchange,
        "ordertype": map_order_type(data["pricetype"]),
        "producttype": map_product_type(
            data["product"], openalgo_exchange
        ),  # Pass OpenAlgo exchange for context
        "orderduration": "DAY",  # Motilal uses 'orderduration' instead of 'duration'
        "price": data.get("price", "0"),
        "triggerprice": data.get("trigger_price", "0"),
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


def map_product_type(product, exchange=None):
    """
    Maps OpenAlgo product type to Motilal Oswal product type based on exchange.
    Motilal supports: NORMAL, DELIVERY, VALUEPLUS, SELLFROMDP, BTST, MTF

    Product type mapping:
    For Cash Segment (NSE, BSE):
        - CNC (Cash and Carry) → DELIVERY (for delivery/holdings)
        - MIS (Margin Intraday Square off) → VALUEPLUS (for intraday margin trading)
        - NRML → VALUEPLUS (fallback for cash segment with margin)

    For F&O Segment (NFO, MCX, CDS, BFO):
        - NRML (Normal for F&O) → NORMAL
        - MIS → NORMAL (intraday F&O)
        - CNC → NORMAL (fallback for F&O segment)

    Note: VALUEPLUS is Motilal's margin product for intraday trading.
    Accounts may have specific product authorizations based on their configuration.

    Args:
        product: OpenAlgo product type (CNC, MIS, NRML)
        exchange: OpenAlgo exchange name (NSE, BSE, NFO, CDS, MCX, BFO)
    """
    # Determine if this is a cash segment or derivative segment
    # Using OpenAlgo exchange names
    is_cash_segment = exchange in ["NSE", "BSE"]
    is_fo_segment = exchange in ["NFO", "MCX", "CDS", "BFO", "NSEFO", "NSECD", "BSEFO"]

    if is_cash_segment:
        # For cash segment: CNC = DELIVERY, MIS = VALUEPLUS (margin intraday)
        cash_mapping = {
            "CNC": "DELIVERY",  # Delivery for holdings
            "MIS": "VALUEPLUS",  # Margin intraday for MIS
            "NRML": "VALUEPLUS",  # Fallback to margin
        }
        return cash_mapping.get(product, "VALUEPLUS")

    elif is_fo_segment:
        # For F&O segment, use NORMAL
        fo_mapping = {
            "NRML": "NORMAL",
            "MIS": "NORMAL",
            "CNC": "NORMAL",
        }
        return fo_mapping.get(product, "NORMAL")

    else:
        # Default fallback based on product
        default_mapping = {
            "CNC": "DELIVERY",
            "MIS": "VALUEPLUS",
            "NRML": "NORMAL",
        }
        return default_mapping.get(product, "VALUEPLUS")


def reverse_map_product_type(product, exchange=None):
    """
    Reverse maps Motilal Oswal product type to OpenAlgo product type.
    Context:
    - Motilal uses DELIVERY for cash delivery (CNC)
    - Motilal uses VALUEPLUS for margin intraday (MIS)
    - Motilal uses NORMAL for F&O segment

    Without exchange context:
        DELIVERY → CNC (delivery product)
        VALUEPLUS → MIS (margin intraday)
        NORMAL → MIS (F&O intraday)

    With exchange context:
        For NSE/BSE:
            DELIVERY → CNC (delivery)
            VALUEPLUS → MIS (margin intraday)
        For NSEFO/MCX:
            NORMAL → MIS (intraday F&O)
    """
    # Default reverse mapping without exchange context
    if exchange is None:
        reverse_product_type_mapping = {
            "DELIVERY": "CNC",  # Delivery product
            "VALUEPLUS": "MIS",  # Margin intraday
            "NORMAL": "MIS",  # F&O intraday
            "BTST": "MIS",
            "MTF": "NRML",
        }
        return reverse_product_type_mapping.get(product, "MIS")

    # With exchange context, provide accurate mapping
    is_cash_segment = exchange in ["NSE", "BSE"]

    if is_cash_segment:
        # For cash segment: VALUEPLUS = MIS, DELIVERY = CNC
        cash_reverse_mapping = {"DELIVERY": "CNC", "VALUEPLUS": "MIS", "BTST": "MIS"}
        return cash_reverse_mapping.get(product, "MIS")
    else:
        # For F&O segment: NORMAL is used
        reverse_fo_mapping = {
            "NORMAL": "MIS",
            "VALUEPLUS": "NRML",
        }
        return reverse_fo_mapping.get(product, "MIS")

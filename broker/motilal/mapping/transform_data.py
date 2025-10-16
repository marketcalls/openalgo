#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Motilal Oswal Parameters - See Motilal_Oswal.md documentation

from database.token_db import get_br_symbol

def transform_data(data,token):
    """
    Transforms the OpenAlgo API request structure to Motilal Oswal expected structure.
    """
    symbol = get_br_symbol(data["symbol"],data["exchange"])
    exchange = data["exchange"]

    # Basic mapping for Motilal Oswal
    transformed = {
        "apikey": data["apikey"],
        "symboltoken": token,
        "buyorsell": data["action"].upper(),  # Motilal uses 'buyorsell' instead of 'transactiontype'
        "exchange": exchange,
        "ordertype": map_order_type(data["pricetype"]),
        "producttype": map_product_type(data["product"], exchange),  # Pass exchange for context
        "orderduration": "DAY",  # Motilal uses 'orderduration' instead of 'duration'
        "price": data.get("price", "0"),
        "triggerprice": data.get("trigger_price", "0"),
        "disclosedquantity": data.get("disclosed_quantity", "0"),
        "quantity": data["quantity"],
        "amoorder": "N",  # AMO-Order (Y or N)
        "algoid": "",  # Algo Id or Blank for Non-Algo Orders
        "goodtilldate": "",  # DD-MMM-YYYY format if GTD
        "tag": "",  # Echo back to identify order (max 10 characters)
        "participantcode": ""  # Participant Code if applicable
    }

    return transformed


def transform_modify_order_data(data, token):
    """
    Transforms modify order data for Motilal Oswal API.
    Motilal uses different field names compared to Angel Broking.
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
        "lastmodifiedtime": "",  # Format: dd-MMM-yyyy HH:mm:ss - should be fetched from order book
        "qtytradedtoday": 0  # Should be fetched from order book
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
        "SL-M": "STOPLOSS"
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

    For F&O Segment (NSEFO, MCX, NSECD):
        - NRML (Normal for F&O) → NORMAL
        - MIS → NORMAL (intraday F&O)
        - CNC → NORMAL (fallback for F&O segment)

    Note: VALUEPLUS is Motilal's margin product for intraday trading.
    Accounts may have specific product authorizations based on their configuration.
    """
    # Determine if this is a cash segment or derivative segment
    is_cash_segment = exchange in ['NSE', 'BSE']
    is_fo_segment = exchange in ['NSEFO', 'MCX', 'NSECD', 'NSECO', 'BSECO']

    if is_cash_segment:
        # For cash segment: CNC = DELIVERY, MIS = VALUEPLUS (margin intraday)
        cash_mapping = {
            "CNC": "DELIVERY",       # Delivery for holdings
            "MIS": "VALUEPLUS",      # Margin intraday for MIS
            "NRML": "VALUEPLUS",     # Fallback to margin
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
            "DELIVERY": "CNC",      # Delivery product
            "VALUEPLUS": "MIS",     # Margin intraday
            "NORMAL": "MIS",        # F&O intraday
            "BTST": "MIS",
            "MTF": "NRML"
        }
        return reverse_product_type_mapping.get(product, "MIS")

    # With exchange context, provide accurate mapping
    is_cash_segment = exchange in ['NSE', 'BSE']

    if is_cash_segment:
        # For cash segment: VALUEPLUS = MIS, DELIVERY = CNC
        cash_reverse_mapping = {
            "DELIVERY": "CNC",
            "VALUEPLUS": "MIS",
            "BTST": "MIS"
        }
        return cash_reverse_mapping.get(product, "MIS")
    else:
        # For F&O segment: NORMAL is used
        reverse_fo_mapping = {
            "NORMAL": "MIS",
            "VALUEPLUS": "NRML",
        }
        return reverse_fo_mapping.get(product, "MIS")  


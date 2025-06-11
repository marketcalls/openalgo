# flattrade_mapping.py (in broker/flattrade/streaming)

# --- Product Type Mappings ---
# Flattrade API uses 'C', 'I', 'M'. OpenAlgo might use 'CNC', 'MIS', 'NRML'.
# This maps Flattrade product codes from WebSocket to a common format.
FLATTRADE_TO_OPENALGO_PRODUCT = {
    "C": "CNC",  # Cash / Equity
    "I": "MIS",  # Intraday
    "M": "NRML", # Normal (for F&O, MCX)
    # Add more if Flattrade uses others in WebSocket messages
}

OPENALGO_TO_FLATTRADE_PRODUCT = {v: k for k, v in FLATTRADE_TO_OPENALGO_PRODUCT.items()}

# --- Order Type Mappings ---
# Flattrade API uses 'LMT', 'MKT', 'SL-LMT', 'SL-MKT'. OpenAlgo might use 'LIMIT', 'MARKET', etc.
# This maps Flattrade order types from WebSocket to a common format.
FLATTRADE_TO_OPENALGO_ORDER_TYPE = {
    "LMT": "LIMIT",
    "MKT": "MARKET",
    "SL-LMT": "SL",  # Or "STOPLIMIT" depending on OpenAlgo standard
    "SL-MKT": "SL-M", # Or "STOPMARKET"
    # Add others if present
}
OPENALGO_TO_FLATTRADE_ORDER_TYPE = {v: k for k, v in FLATTRADE_TO_OPENALGO_ORDER_TYPE.items()}


# --- Transaction Type Mappings ---
# Flattrade API uses 'B', 'S'. OpenAlgo might use 'BUY', 'SELL'.
FLATTRADE_TO_OPENALGO_TRANSACTION_TYPE = {
    "B": "BUY",
    "S": "SELL",
}
OPENALGO_TO_FLATTRADE_TRANSACTION_TYPE = {v: k for k, v in FLATTRADE_TO_OPENALGO_TRANSACTION_TYPE.items()}

# --- Order Status Mappings ---
# This will be crucial for 'om' (order update) messages.
# We need to see example 'om' messages from Flattrade logs to fill this accurately.
# Example: Flattrade might send "filled", OpenAlgo might expect "COMPLETE".
FLATTRADE_TO_OPENALGO_ORDER_STATUS = {
    "pending": "OPEN", # Example, needs confirmation
    "submitted": "OPEN", # Example
    "open": "OPEN", # Example
    "filled": "COMPLETE", # Example
    "complete": "COMPLETE", # Example
    "traded": "COMPLETE", # Example
    "rejected": "REJECTED", # Example
    "cancelled": "CANCELLED", # Example
    "canceled": "CANCELLED", # Example
    "trigger pending": "TRIGGER_PENDING", # Example for SL orders
    # ... more statuses based on Flattrade WebSocket API documentation or logs
}

# --- Exchange Mappings (if necessary) ---
# Flattrade seems to use standard names like "NSE", "NFO", "MCX" in 'e' field of 'tk' messages.
# If OpenAlgo uses different codes, a mapping would be needed.
# For now, assuming direct use or simple case change if needed.
FLATTRADE_TO_OPENALGO_EXCHANGE = {
    "NSE": "NSE",
    "NFO": "NFO",
    "BSE": "BSE",
    "BFO": "BFO", # BSE F&O
    "MCX": "MCX",
    "CDS": "CDS", # Currency
    # Add more if needed
}


def map_websocket_tick_to_openalgo_tick(ws_tick_data):
    """
    Transforms a Flattrade WebSocket tick message (tk or tf)
    to the OpenAlgo standard tick format.
    Example ws_tick_data ('tk' or 'tf'):
    {
        "t": "tk", "e": "NSE", "tk": "26000", "ts": "Nifty 50", "pp": "2",
        "ls": "1", "ti": "0.05", "lp": "24999.90", "pc": "1.01",
        "o": "24748.70", "h": "25029.50", "l": "24671.45", "c": "24750.90",
        "toi": "54239850"
        # Potentially other fields like 'ap', 'bp', 'aq', 'bq', 'v', 'ltq', 'ltt', 'tbq', 'tsq'
    }
    """
    if not ws_tick_data or not isinstance(ws_tick_data, dict):
        return None

    # This is a placeholder structure. Adjust field names and values
    # based on OpenAlgo's expected tick format.
    openalgo_tick = {
        "type": ws_tick_data.get("t"), # 'tk', 'tf', 'dk', 'df'
        "exchange": FLATTRADE_TO_OPENALGO_EXCHANGE.get(ws_tick_data.get("e"), ws_tick_data.get("e")),
        "token": ws_tick_data.get("tk"), # Instrument token
        "tradingsymbol": ws_tick_data.get("ts"), # Trading symbol
        
        "last_price": float(ws_tick_data.get("lp", 0)),
        "percentage_change": float(ws_tick_data.get("pc", 0)),
        "open": float(ws_tick_data.get("o", 0)),
        "high": float(ws_tick_data.get("h", 0)),
        "low": float(ws_tick_data.get("l", 0)),
        "close": float(ws_tick_data.get("c", 0)),
        "volume": int(ws_tick_data.get("toi", 0)), # Or 'v' if that's total volume
        
        # Potentially from depth messages or more complete tick messages
        "last_traded_quantity": int(ws_tick_data.get("ltq", 0)),
        "average_trade_price": float(ws_tick_data.get("atp", 0)), # If available
        "total_buy_quantity": int(ws_tick_data.get("tbq", 0)), # If available
        "total_sell_quantity": int(ws_tick_data.get("tsq", 0)), # If available
        "last_trade_time": ws_tick_data.get("ltt"), # If available (timestamp object or string)
        
        # Depth information (example, might come from 'df' messages)
        # "depth": {
        #     "buy": [{"quantity": int(item.get("buyqty",0)), "price": float(item.get("buyprice",0)), "orders": int(item.get("buyorders",0))} for item in ws_tick_data.get("buy", [])],
        #     "sell": [{"quantity": int(item.get("sellqty",0)), "price": float(item.get("sellprice",0)), "orders": int(item.get("sellorders",0))} for item in ws_tick_data.get("sell", [])]
        # }

        # Raw message for debugging or further processing
        "raw": ws_tick_data
    }
    return openalgo_tick

def map_websocket_order_update_to_openalgo_order(ws_order_data):
    """
    Transforms a Flattrade WebSocket order update message ('om')
    to the OpenAlgo standard order format.
    Example ws_order_data ('om'):
    {
        "t": "om",
        "norenordno": "23091800000001", # Order ID
        "uid": "FZ00000",
        "actid": "FZ00000",
        "exch": "NSE",
        "tsym": "RELIANCE-EQ",
        "qty": "10", # Ordered quantity
        "ordenttm": "18-Sep-2023 10:00:00", # Order entry time
        "trantype": "B", # B / S
        "prctyp": "LMT", # LMT / MKT / SL-LMT / SL-MKT
        "fillshares": "5", # Filled quantity
        "prc": "2300.00", # Price
        "trgprc": "0.00", # Trigger price
        "status": "partially filled", # Order status text from Flattrade
        "reporttype": "fill", # type of report: New, Modification, Fill, Partial Fill, Cancellation, Rejection
        "remarks": "Order executed partially", # Rejection reason or other remarks
        "token": "2885", # Scrip token
        # ... other fields like avgprc, rejreason, exchordid, cancelqty etc.
    }
    """
    if not ws_order_data or not isinstance(ws_order_data, dict):
        return None

    # This is a placeholder structure. Adjust field names and values
    # based on OpenAlgo's expected order format and Flattrade's actual 'om' message content.
    openalgo_order = {
        "type": ws_order_data.get("t"), # 'om'
        "order_id": ws_order_data.get("norenordno"),
        "exchange_order_id": ws_order_data.get("exchorderid"), # If available
        "parent_order_id": ws_order_data.get("parentorderid"), # For cover/bracket orders

        "status": FLATTRADE_TO_OPENALGO_ORDER_STATUS.get(
            str(ws_order_data.get("status", "")).lower(), # Normalize Flattrade status
            str(ws_order_data.get("status", "")).upper() # Default to uppercase original if no map
        ),
        "tradingsymbol": ws_order_data.get("tsym"),
        "exchange": FLATTRADE_TO_OPENALGO_EXCHANGE.get(ws_order_data.get("exch"), ws_order_data.get("exch")),
        "token": ws_order_data.get("token"),

        "transaction_type": FLATTRADE_TO_OPENALGO_TRANSACTION_TYPE.get(
            ws_order_data.get("trantype"), ws_order_data.get("trantype")
        ),
        "product_type": FLATTRADE_TO_OPENALGO_PRODUCT.get(
            ws_order_data.get("prd"), ws_order_data.get("prd") # 'prd' might not be in 'om', check logs
        ),
        "order_type": FLATTRADE_TO_OPENALGO_ORDER_TYPE.get(
            ws_order_data.get("prctyp"), ws_order_data.get("prctyp")
        ),

        "quantity": int(ws_order_data.get("qty", 0)),
        "disclosed_quantity": int(ws_order_data.get("dscqty", 0)), # If available
        "filled_quantity": int(ws_order_data.get("fillshares", 0)),
        "pending_quantity": int(ws_order_data.get("qty", 0)) - int(ws_order_data.get("fillshares", 0)), # Calculate if not directly provided
        "cancelled_quantity": int(ws_order_data.get("cancelqty", 0)), # If available

        "price": float(ws_order_data.get("prc", 0)),
        "trigger_price": float(ws_order_data.get("trgprc", 0)),
        "average_price": float(ws_order_data.get("avgprc", 0)), # Average execution price

        "order_timestamp": ws_order_data.get("norentm"), # Order entry time from Flattrade
        "exchange_timestamp": ws_order_data.get("exchupddttm"), # Exchange update time, if available
        
        "message": ws_order_data.get("remarks"), # Or 'rejreason'
        "rejection_reason": ws_order_data.get("rejreason"), # If specific field exists

        # For OpenAlgo internal use, might be added by adapter
        # "user_id": ws_order_data.get("uid"),
        # "account_id": ws_order_data.get("actid"),
        
        "report_type": ws_order_data.get("reporttype"), # 'New', 'Modification', 'Fill', etc.

        "raw": ws_order_data
    }
    return openalgo_order

# You might also need functions to map data FOR subscriptions,
# but FlattradeWebSocketClient already handles that formatting.
# The primary role here is mapping RECEIVED data.

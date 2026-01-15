"""
Constants used throughout the application.
Reference: https://docs.openalgo.in/api-documentation/v1/order-constants
"""

# Exchange Types
EXCHANGE_NSE = 'NSE'    # NSE Equity
EXCHANGE_NFO = 'NFO'    # NSE Futures & Options
EXCHANGE_CDS = 'CDS'    # NSE Currency
EXCHANGE_BSE = 'BSE'    # BSE Equity
EXCHANGE_BFO = 'BFO'    # BSE Futures & Options
EXCHANGE_BCD = 'BCD'    # BSE Currency
EXCHANGE_MCX = 'MCX'    # MCX Commodity
EXCHANGE_NCDEX = 'NCDEX'  # NCDEX Commodity
EXCHANGE_NSE_INDEX = 'NSE_INDEX'  # NSE Index
EXCHANGE_BSE_INDEX = 'BSE_INDEX'  # BSE Index

VALID_EXCHANGES = [
    EXCHANGE_NSE,
    EXCHANGE_NFO,
    EXCHANGE_CDS,
    EXCHANGE_BSE,
    EXCHANGE_BFO,
    EXCHANGE_BCD,
    EXCHANGE_MCX,
    EXCHANGE_NCDEX,
    EXCHANGE_NSE_INDEX,
    EXCHANGE_BSE_INDEX
]

# Product Types
PRODUCT_CNC = 'CNC'     # Cash & Carry for equity
PRODUCT_NRML = 'NRML'   # Normal for futures and options
PRODUCT_MIS = 'MIS'     # Intraday Square off

VALID_PRODUCT_TYPES = [
    PRODUCT_CNC,
    PRODUCT_NRML,
    PRODUCT_MIS
]

# Price Types
PRICE_TYPE_MARKET = 'MARKET'  # Market Order
PRICE_TYPE_LIMIT = 'LIMIT'    # Limit Order
PRICE_TYPE_SL = 'SL'         # Stop Loss Limit Order
PRICE_TYPE_SLM = 'SL-M'      # Stop Loss Market Order

VALID_PRICE_TYPES = [
    PRICE_TYPE_MARKET,
    PRICE_TYPE_LIMIT,
    PRICE_TYPE_SL,
    PRICE_TYPE_SLM
]

# Order Actions
ACTION_BUY = 'BUY'    # Buy
ACTION_SELL = 'SELL'  # Sell

VALID_ACTIONS = [
    ACTION_BUY,
    ACTION_SELL
]

# Exchange Badge Colors (for UI)
EXCHANGE_BADGE_COLORS = {
    EXCHANGE_NSE: 'badge-accent',
    EXCHANGE_NFO: 'badge-secondary',
    EXCHANGE_CDS: 'badge-info',
    EXCHANGE_BSE: 'badge-neutral',
    EXCHANGE_BFO: 'badge-warning',
    EXCHANGE_BCD: 'badge-error',
    EXCHANGE_MCX: 'badge-primary',
    EXCHANGE_NCDEX: 'badge-success',
    EXCHANGE_NSE_INDEX: 'badge-accent',
    EXCHANGE_BSE_INDEX: 'badge-neutral'
}

# Required Fields for Order Placement
REQUIRED_ORDER_FIELDS = ['apikey', 'strategy', 'symbol', 'exchange', 'action', 'quantity']

# Required Fields for Smart Order Placement
REQUIRED_SMART_ORDER_FIELDS = ['apikey', 'strategy', 'symbol', 'exchange', 'action', 'quantity', 'position_size']

# Required Fields for Cancel Order
REQUIRED_CANCEL_ORDER_FIELDS = ['apikey', 'strategy', 'orderid']

# Required Fields for Cancel All Orders
REQUIRED_CANCEL_ALL_ORDER_FIELDS = ['apikey', 'strategy']

# Required Fields for Close Position
REQUIRED_CLOSE_POSITION_FIELDS = ['apikey', 'strategy']

# Required Fields for Modify Order
REQUIRED_MODIFY_ORDER_FIELDS = [
    'apikey', 'strategy', 'symbol', 'action', 'exchange', 'orderid',
    'product', 'pricetype', 'price', 'quantity', 'disclosed_quantity', 'trigger_price'
]

# Default Values for Optional Fields
DEFAULT_PRODUCT_TYPE = PRODUCT_MIS
DEFAULT_PRICE_TYPE = PRICE_TYPE_MARKET
DEFAULT_PRICE = "0"
DEFAULT_TRIGGER_PRICE = "0"
DEFAULT_DISCLOSED_QUANTITY = "0"

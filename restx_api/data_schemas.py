from marshmallow import Schema, fields, validate, ValidationError
import re

# Custom validator for date or timestamp string
def validate_date_or_timestamp(data):
    """
    Validates that the input string is either in 'YYYY-MM-DD' format or a numeric timestamp.
    """
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    timestamp_pattern = re.compile(r'^\d{10,13}$') # Allows for seconds or milliseconds
    if not (isinstance(data, str) and (date_pattern.match(data) or timestamp_pattern.match(data))):
        raise ValidationError("Field must be a string in 'YYYY-MM-DD' format or a numeric timestamp.")

# Custom validator for option offset
def validate_option_offset(data):
    """
    Validates option offset: ATM, ITM1-ITM50, OTM1-OTM50
    """
    data_upper = data.upper()
    if data_upper == "ATM":
        return True

    # Check for ITM pattern: ITM followed by 1-50
    itm_pattern = re.compile(r'^ITM([1-9]|[1-4][0-9]|50)$')
    otm_pattern = re.compile(r'^OTM([1-9]|[1-4][0-9]|50)$')

    if not (itm_pattern.match(data_upper) or otm_pattern.match(data_upper)):
        raise ValidationError("Offset must be ATM, ITM1-ITM50, or OTM1-OTM50")

    return True

class QuotesSchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)  # Single symbol
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)

class SymbolExchangePair(Schema):
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)

class MultiQuotesSchema(Schema):
    apikey = fields.Str(required=True)
    symbols = fields.List(fields.Nested(SymbolExchangePair), required=True, validate=validate.Length(min=1))

class HistorySchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)
    interval = fields.Str(required=True, validate=validate.OneOf([
        # Seconds intervals
        "1s", "5s", "10s", "15s", "30s", "45s",
        # Minutes intervals
        "1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m",
        # Hours intervals
        "1h", "2h", "3h", "4h",
        # Daily, Weekly, Monthly intervals
        "D", "W", "M"
    ]))
    start_date = fields.Date(required=True, format='%Y-%m-%d')  # YYYY-MM-DD
    end_date = fields.Date(required=True, format='%Y-%m-%d')    # YYYY-MM-DD
    # OI is now always included by default for F&O exchanges

class DepthSchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)

class IntervalsSchema(Schema):
    apikey = fields.Str(required=True)

class SymbolSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    symbol = fields.Str(required=True)      # Symbol code (e.g., RELIANCE)
    exchange = fields.Str(required=True)    # Exchange (e.g., NSE, BSE)

class TickerSchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)      # Combined exchange:symbol format
    interval = fields.Str(required=True, validate=validate.OneOf(["1m", "5m", "15m", "30m", "1h", "4h", "D", "W", "M"]))    # Supported intervals: 1m, 5m, 15m, 30m, 1h, 4h, D, W, M etc.
    from_ = fields.Str(data_key='from', required=True, validate=validate_date_or_timestamp)  # YYYY-MM-DD or millisecond timestamp
    to = fields.Str(required=True, validate=validate_date_or_timestamp)          # YYYY-MM-DD or millisecond timestamp
    adjusted = fields.Bool(required=False, default=True)  # Adjust for splits
    sort = fields.Str(required=False, default='asc', validate=validate.OneOf(['asc', 'desc']))  # Sort direction

class SearchSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    query = fields.Str(required=True)       # Search query/symbol name
    exchange = fields.Str(required=False)   # Optional exchange filter (e.g., NSE, BSE)

class ExpirySchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    symbol = fields.Str(required=True)      # Underlying symbol (e.g., NIFTY, BANKNIFTY)
    exchange = fields.Str(required=True, validate=validate.OneOf(["NFO", "BFO", "MCX", "CDS"]))    # Exchange (e.g., NFO, BFO, MCX, CDS)
    instrumenttype = fields.Str(required=True, validate=validate.OneOf(["futures", "options"]))  # futures or options

class OptionSymbolSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    strategy = fields.Str(required=False, allow_none=True)    # DEPRECATED: Strategy name (optional, will be removed in future versions)
    underlying = fields.Str(required=True)  # Underlying symbol (NIFTY, RELIANCE, NIFTY28OCT25FUT)
    exchange = fields.Str(required=True)    # Exchange (NSE_INDEX, NSE, NFO)
    expiry_date = fields.Str(required=False)  # Expiry date in DDMMMYY format (e.g., 28OCT25). Optional if underlying includes expiry
    strike_int = fields.Int(required=False, validate=validate.Range(min=1), allow_none=True)  # OPTIONAL: Strike interval. If not provided, actual strikes from database will be used (RECOMMENDED for accuracy)
    offset = fields.Str(required=True, validate=validate_option_offset)      # Strike offset from ATM (ATM, ITM1-ITM50, OTM1-OTM50)
    option_type = fields.Str(required=True, validate=validate.OneOf(["CE", "PE", "ce", "pe"]))  # Call or Put option

class OptionGreeksSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    symbol = fields.Str(required=True)      # Option symbol (e.g., NIFTY28NOV2424000CE)
    exchange = fields.Str(required=True, validate=validate.OneOf(["NFO", "BFO", "CDS", "MCX"]))  # Exchange (NFO, BFO, CDS, MCX)
    interest_rate = fields.Float(required=False, validate=validate.Range(min=0, max=100))  # Risk-free interest rate (annualized %). Optional, defaults per exchange
    forward_price = fields.Float(required=False, validate=validate.Range(min=0))  # Optional: Custom forward/synthetic futures price. If provided, skips underlying price fetch
    underlying_symbol = fields.Str(required=False)   # Optional: Specify underlying symbol (e.g., NIFTY or NIFTY28NOV24FUT)
    underlying_exchange = fields.Str(required=False)  # Optional: Specify underlying exchange (NSE_INDEX, NFO, etc.)
    expiry_time = fields.Str(required=False)  # Optional: Custom expiry time in HH:MM format (e.g., "15:30", "19:00"). If not provided, uses exchange defaults

class InstrumentsSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    exchange = fields.Str(required=False, validate=validate.OneOf([
        "NSE", "BSE", "NFO", "BFO", "BCD", "CDS", "MCX", "NSE_INDEX", "BSE_INDEX"
    ]))  # Optional exchange filter
    format = fields.Str(required=False, validate=validate.OneOf(["json", "csv"]))  # Output format (json or csv), defaults to json

class OptionChainSchema(Schema):
    apikey = fields.Str(required=True)      # API Key for authentication
    underlying = fields.Str(required=True)  # Underlying symbol (e.g., NIFTY, BANKNIFTY, RELIANCE)
    exchange = fields.Str(required=True)    # Exchange (NSE_INDEX, NSE, NFO, BSE_INDEX, BSE, BFO, MCX, CDS)
    expiry_date = fields.Str(required=True)  # Expiry date in DDMMMYY format (e.g., 28NOV25) - MANDATORY
    strike_count = fields.Int(required=False, validate=validate.Range(min=1, max=100), allow_none=True)  # Number of strikes above/below ATM. If not provided, returns entire chain

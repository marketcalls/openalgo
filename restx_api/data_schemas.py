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

class HistorySchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)
    interval = fields.Str(required=True, validate=validate.OneOf(["1m", "5m", "15m", "30m", "1h", "D"]))  # 1m, 5m, 15m, 30m, 1h, D
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
    strategy = fields.Str(required=True)    # Strategy name
    underlying = fields.Str(required=True)  # Underlying symbol (NIFTY, RELIANCE, NIFTY28OCT25FUT)
    exchange = fields.Str(required=True)    # Exchange (NSE_INDEX, NSE, NFO)
    expiry_date = fields.Str(required=False)  # Expiry date in DDMMMYY format (e.g., 28OCT25). Optional if underlying includes expiry
    strike_int = fields.Int(required=True, validate=validate.Range(min=1))  # Strike interval/difference (e.g., 50 for NIFTY, 100 for BANKNIFTY)
    offset = fields.Str(required=True, validate=validate_option_offset)      # Strike offset from ATM (ATM, ITM1-ITM50, OTM1-OTM50)
    option_type = fields.Str(required=True, validate=validate.OneOf(["CE", "PE", "ce", "pe"]))  # Call or Put option

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

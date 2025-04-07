from marshmallow import Schema, fields

class QuotesSchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)  # Single symbol
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)

class HistorySchema(Schema):
    apikey = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)  # Exchange (e.g., NSE, BSE)
    interval = fields.Str(required=True)  # 1m, 5m, 15m, 30m, 1h, 1d
    start_date = fields.Str(required=True)  # YYYY-MM-DD
    end_date = fields.Str(required=True)    # YYYY-MM-DD

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
    interval = fields.Str(required=True)    # Supported intervals: 1m, 5m, 15m, 30m, 1h, 4h, D, W, M etc.
    from_ = fields.Str(data_key='from', required=True)  # YYYY-MM-DD or millisecond timestamp
    to = fields.Str(required=True)          # YYYY-MM-DD or millisecond timestamp
    adjusted = fields.Bool(required=False, default=True)  # Adjust for splits
    sort = fields.Str(required=False, default='asc', validate=lambda x: x in ['asc', 'desc'])  # Sort direction

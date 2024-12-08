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

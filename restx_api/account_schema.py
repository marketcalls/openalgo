from marshmallow import Schema, fields, validate

class FundsSchema(Schema):
    apikey = fields.Str(required=True)

class OrderbookSchema(Schema):
    apikey = fields.Str(required=True)

class TradebookSchema(Schema):
    apikey = fields.Str(required=True)

class PositionbookSchema(Schema):
    apikey = fields.Str(required=True)

class HoldingsSchema(Schema):
    apikey = fields.Str(required=True)

class OrderStatusSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    orderid = fields.Str(required=True)

class OpenPositionSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))

class AnalyzerSchema(Schema):
    apikey = fields.Str(required=True)

class AnalyzerToggleSchema(Schema):
    apikey = fields.Str(required=True)
    mode = fields.Bool(required=True)

class PingSchema(Schema):
    apikey = fields.Str(required=True)

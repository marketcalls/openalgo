from marshmallow import Schema, fields

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

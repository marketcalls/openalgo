from marshmallow import Schema, fields, ValidationError

class OrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True)
    quantity = fields.Int(required=True)
    pricetype = fields.Str(missing='MARKET')
    product = fields.Str(missing='MIS')
    price = fields.Float(missing=0.0)
    trigger_price = fields.Float(missing=0.0)
    disclosed_quantity = fields.Int(missing=0)

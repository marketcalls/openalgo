from marshmallow import Schema, fields

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

class SmartOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True)
    quantity = fields.Int(required=True)
    position_size = fields.Float(required=True)
    pricetype = fields.Str(missing='MARKET')
    product = fields.Str(missing='MIS')
    price = fields.Float(missing=0.0)
    trigger_price = fields.Float(missing=0.0)
    disclosed_quantity = fields.Int(missing=0)

class ModifyOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    orderid = fields.Str(required=True)
    action = fields.Str(required=True)
    product = fields.Str(required=True)
    pricetype = fields.Str(required=True)
    price = fields.Float(required=True)
    quantity = fields.Int(required=True)
    disclosed_quantity = fields.Int(required=True)
    trigger_price = fields.Float(required=True)

class CancelOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    orderid = fields.Str(required=True)

class ClosePositionSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)

class CancelAllOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)

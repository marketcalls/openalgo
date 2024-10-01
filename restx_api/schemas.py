from marshmallow import Schema, fields

class OrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True)
    quantity = fields.Str(required=True)  # Changed from Int to Str
    pricetype = fields.Str(missing='MARKET')
    product = fields.Str(missing='MIS')
    price = fields.Str(missing='0.0')  # Changed from Float to Str
    trigger_price = fields.Str(missing='0.0')  # Changed from Float to Str
    disclosed_quantity = fields.Str(missing='0')  # Changed from Int to Str

class SmartOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True)
    quantity = fields.Str(required=True)  # Changed from Int to Str
    position_size = fields.Str(required=True)  # Changed from Float to Str
    pricetype = fields.Str(missing='MARKET')
    product = fields.Str(missing='MIS')
    price = fields.Str(missing='0.0')  # Changed from Float to Str
    trigger_price = fields.Str(missing='0.0')  # Changed from Float to Str
    disclosed_quantity = fields.Str(missing='0')  # Changed from Int to Str

class ModifyOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    orderid = fields.Str(required=True)
    action = fields.Str(required=True)
    product = fields.Str(required=True)
    pricetype = fields.Str(required=True)
    price = fields.Str(required=True)  # Changed from Float to Str
    quantity = fields.Str(required=True)  # Changed from Int to Str
    disclosed_quantity = fields.Str(required=True)  # Changed from Int to Str
    trigger_price = fields.Str(required=True)  # Changed from Float to Str

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
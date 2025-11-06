from marshmallow import Schema, fields, validate

class OrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Int(required=True, validate=validate.Range(min=1, error="Quantity must be a positive integer."))
    pricetype = fields.Str(missing='MARKET', validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    product = fields.Str(missing='MIS', validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    trigger_price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))
    disclosed_quantity = fields.Int(missing=0, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))

class SmartOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Int(required=True, validate=validate.Range(min=0, error="Quantity must be a non-negative integer."))
    position_size = fields.Int(required=True)
    pricetype = fields.Str(missing='MARKET', validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    product = fields.Str(missing='MIS', validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    trigger_price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))
    disclosed_quantity = fields.Int(missing=0, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))

class ModifyOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    orderid = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    pricetype = fields.Str(required=True, validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    price = fields.Float(required=True, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    quantity = fields.Int(required=True, validate=validate.Range(min=1, error="Quantity must be a positive integer."))
    disclosed_quantity = fields.Int(required=True, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))
    trigger_price = fields.Float(required=True, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))

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

class BasketOrderItemSchema(Schema):
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Int(required=True, validate=validate.Range(min=1, error="Quantity must be a positive integer."))
    pricetype = fields.Str(missing='MARKET', validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    product = fields.Str(missing='MIS', validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    trigger_price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))
    disclosed_quantity = fields.Int(missing=0, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))

class BasketOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    orders = fields.List(fields.Nested(BasketOrderItemSchema), required=True)  # List of order details

class SplitOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    exchange = fields.Str(required=True)
    symbol = fields.Str(required=True)
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Int(required=True, validate=validate.Range(min=1, error="Total quantity must be a positive integer."))  # Total quantity to split
    splitsize = fields.Int(required=True, validate=validate.Range(min=1, error="Split size must be a positive integer."))  # Size of each split
    pricetype = fields.Str(missing='MARKET', validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    product = fields.Str(missing='MIS', validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    trigger_price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))
    disclosed_quantity = fields.Int(missing=0, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))

class OptionsOrderSchema(Schema):
    apikey = fields.Str(required=True)
    strategy = fields.Str(required=True)
    underlying = fields.Str(required=True)  # Underlying symbol (NIFTY, BANKNIFTY, RELIANCE, or NIFTY28NOV24FUT)
    exchange = fields.Str(required=True)  # Exchange (NSE_INDEX, NSE, BSE_INDEX, BSE, NFO, BFO)
    expiry_date = fields.Str(required=False)  # Optional if underlying includes expiry (DDMMMYY format)
    strike_int = fields.Int(required=True, validate=validate.Range(min=1))  # Strike interval
    offset = fields.Str(required=True)  # ATM, ITM1-ITM50, OTM1-OTM50
    option_type = fields.Str(required=True, validate=validate.OneOf(["CE", "PE", "ce", "pe"]))  # Call or Put
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Int(required=True, validate=validate.Range(min=1, error="Quantity must be a positive integer."))
    pricetype = fields.Str(missing='MARKET', validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    product = fields.Str(missing='MIS', validate=validate.OneOf(["MIS", "NRML"]))  # Options only support MIS and NRML
    price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Price must be a non-negative number."))
    trigger_price = fields.Float(missing=0.0, validate=validate.Range(min=0, error="Trigger price must be a non-negative number."))
    disclosed_quantity = fields.Int(missing=0, validate=validate.Range(min=0, error="Disclosed quantity must be a non-negative integer."))

class MarginPositionSchema(Schema):
    """Schema for a single position in margin calculation"""
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=50, error="Symbol must be between 1 and 50 characters."))
    exchange = fields.Str(required=True, validate=validate.OneOf(["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"]))
    action = fields.Str(required=True, validate=validate.OneOf(["BUY", "SELL", "buy", "sell"]))
    quantity = fields.Str(required=True)  # String to match API contract, validated in service layer
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))
    pricetype = fields.Str(required=True, validate=validate.OneOf(["MARKET", "LIMIT", "SL", "SL-M"]))
    price = fields.Str(missing='0')  # String to match API contract
    trigger_price = fields.Str(missing='0')  # String to match API contract

class MarginCalculatorSchema(Schema):
    """Schema for margin calculator request"""
    apikey = fields.Str(required=True, validate=validate.Length(min=1, error="API key is required."))
    positions = fields.List(
        fields.Nested(MarginPositionSchema),
        required=True,
        validate=validate.Length(min=1, max=50, error="Positions must contain 1 to 50 items.")
    )

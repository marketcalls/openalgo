#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Upstox Broking Parameters https://upstox.com/developer/api-documentation/orders

    


def transform_data(data,br_symbol):
    """
    Transforms the new API request structure to the current expected structure.
    """
    br_symbol, product, expiry_date, right, strike_price = map_symbol(data,br_symbol)

    # Printing the values
    # print("br_symbol:", br_symbol)
    # print("Product:", product)
    # print("Expiry Date:", expiry_date)
    # print("Right:", right)
    # print("Strike Price:", strike_price)
    

    # Basic mapping
    transformed = {
        "stock_code": br_symbol,
        "exchange_code": data['exchange'],
        "product":product,
        "action": data['action'].lower(),
        "order_type": map_order_type(data["pricetype"]),
        "stoploss": float(data.get("trigger_price", 0)),
        "quantity": data['quantity'],
        "price": data['price'],
        "validity": 'day',
        "disclosed_quantity": int(data.get("disclosed_quantity", 0)),
        "user_remark": "openalgo" 
    } 



    if(data['exchange']=='NFO'):
        # Extended mapping for fields that might need conditional logic or additional processing
        transformed["expiry_date"] = expiry_date
        transformed["right"] = right
        transformed["strike_price"] = strike_price
   
    
    return transformed


def transform_modify_order_data(data):
    return {
        "quantity": data["quantity"],
        "validity": "DAY",
        "price": data["price"],
        "order_id": data["orderid"],
        "order_type": map_order_type(data["pricetype"]),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "trigger_price": data.get("trigger_price", "0")
    }

def map_symbol(data,br_symbol):
    product = ''
    expiry_date = None
    right = None
    strike_price = None
    

    if data['exchange'] == "NSE":
        if data['product'] == 'CNC':
            product = 'cash'
        elif data['product'] == 'MIS':
            product = 'margin'

    elif data['exchange'] == "NFO":
        if data['symbol'].endswith("FUT"):
            product = 'futures'
            symbol_parts = br_symbol.split(':::')
            br_symbol = symbol_parts[0]
            expiry_date = symbol_parts[1]
            right = 'others'
            strike_price = ''

        elif data['symbol'].endswith("CE"):
            product = 'options'
            symbol_parts = br_symbol.split(':::')
            br_symbol = symbol_parts[0]
            expiry_date = symbol_parts[1]
            right = 'call'
            strike_price = symbol_parts[2]

        elif data['symbol'].endswith("PE"):
            product = 'options'
            symbol_parts = br_symbol.split(':::')
            br_symbol = symbol_parts[0]
            expiry_date = symbol_parts[1]
            right = 'put'
            strike_price = symbol_parts[2]

    return br_symbol, product, expiry_date, right, strike_price




def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "market",
        "LIMIT": "limit",
        "SL": "stoploss",
        "SL-M": "stoploss"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "D",
        "NRML": "D",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to INTRADAY if not found

def reverse_map_product_type(exchange,product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping_for_d = {
        "NSE": "CNC",
        "BSE": "CNC",
        "NFO": "NRML",
        "BFO": "NRML",
        "MCX": "NRML",
        "CDS": "NRML",
    }
    
    # Reverse mapping based on product type and exchange
    if product == 'D':
        return exchange_mapping_for_d.get(exchange)  # Removed default; will return None if not found
    elif product == 'I':
        return "MIS"


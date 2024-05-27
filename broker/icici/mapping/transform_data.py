#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping ICICI Broking Parameters https://api.icicidirect.com/breezeapi/documents/index.html#order

    


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
        "price": float(data.get("price", 0.0)),
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


def transform_modify_order_data(data,br_symbol):


    br_symbol, product, expiry_date, right, strike_price = map_symbol(data,br_symbol)

    return {
        "order_id": data["orderid"],
        "exchange_code": data["exchange"],
        "quantity": data["quantity"],
        "price": data["price"],
        "stoploss": data.get("trigger_price", ""),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "order_type": map_order_type(data['pricetype']),
        "validity": 'day',
        "expiry_date": expiry_date,
        "right": right,
        "strike_price": strike_price
    }

def map_symbol(data,br_symbol):
    product = ''
    expiry_date = None
    right = None
    strike_price = None
    

    if data['exchange'] == "NSE" or data['exchange'] == "BSE":
        if data['product'] == 'CNC':
            product = 'cash'
        elif data['product'] == 'MIS':
            product = 'margin'

    elif data['exchange'] == "NFO":
        if data['symbol'].endswith("FUT"):
            if(data['product']=='NRML'):
                product = 'futures'
            if(data['product']=='MIS'):
                product = 'futures'
            symbol_parts = br_symbol.split(':::')
            br_symbol = symbol_parts[0]
            expiry_date = symbol_parts[1]
            right = 'others'
            strike_price = ''

        elif data['symbol'].endswith("CE"):
            if(data['product']=='NRML'):
                product = 'options'
            if(data['product']=='MIS'):
                product = 'options'
            symbol_parts = br_symbol.split(':::')
            br_symbol = symbol_parts[0]
            expiry_date = symbol_parts[1]
            right = 'call'
            strike_price = symbol_parts[2]

        elif data['symbol'].endswith("PE"):
            if(data['product']=='NRML'):
                product = 'options'
            if(data['product']=='MIS'):
                product = 'optionplus'
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



def reverse_map_product_type(exchange,product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    if(exchange=="NSE" or exchange=="BSE"):
        if product=="Margin":
            return "MIS"
        if product=="Cash":
            return "CNC"
    if(exchange=="NFO"):
        if product=="Futures":
            return "NRML"
        if product=="Options":
            return "NRML"
        if product=="FuturePlus":
            return "MIS"
        if product=="OptionPlus":
            return "MIS"
    
        


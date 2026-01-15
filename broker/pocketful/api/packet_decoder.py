import struct
import json
import ctypes
from utils.logging import get_logger

logger = get_logger(__name__)


# Configure logging
logger = get_logger(__name__)

def decodeSnapquoteData(message):
    """
    Decode snapquote data from binary message or JSON
    Returns a properly formatted snapquote data dictionary
    """
    try:
        logger.debug(f"Decoding snapquote message: {message[:100]}{'...' if len(str(message)) > 100 else ''}")
        
        # For JSON responses (modern API version)
        if isinstance(message, str):
            try:
                data = json.loads(message)
                logger.debug(f"Parsed JSON data: {data}")
                
                # Handle various JSON response formats
                if isinstance(data, dict):
                    # Direct data object
                    if 'instrument_token' in data or 'instrumentToken' in data:
                        # Standardize key names
                        if 'instrumentToken' in data and 'instrument_token' not in data:
                            data['instrument_token'] = data['instrumentToken']
                        if 'exchangeCode' in data and 'exchange_code' not in data:
                            data['exchange_code'] = data['exchangeCode']
                        return data
                    
                    # Nested data in 'd' field (common in some APIs)
                    if 'd' in data and isinstance(data['d'], dict):
                        result = data['d']
                        if 'instrumentToken' in result and 'instrument_token' not in result:
                            result['instrument_token'] = result['instrumentToken']
                        if 'exchangeCode' in result and 'exchange_code' not in result:
                            result['exchange_code'] = result['exchangeCode']
                        return result
                    
                    # Check for 'data' field
                    if 'data' in data and isinstance(data['data'], dict):
                        result = data['data']
                        if 'instrumentToken' in result and 'instrument_token' not in result:
                            result['instrument_token'] = result['instrumentToken']
                        if 'exchangeCode' in result and 'exchange_code' not in result:
                            result['exchange_code'] = result['exchangeCode']
                        return result
                                        
                # Handle array responses
                elif isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    # Return first item in array if it has right fields
                    if 'instrument_token' in data[0] or 'instrumentToken' in data[0]:
                        result = data[0]
                        if 'instrumentToken' in result and 'instrument_token' not in result:
                            result['instrument_token'] = result['instrumentToken']
                        if 'exchangeCode' in result and 'exchange_code' not in result:
                            result['exchange_code'] = result['exchangeCode']
                        return result
                
                logger.debug(f"JSON format not recognized: {data}")
            except Exception as e:
                logger.debug(f"JSON parsing failed: {str(e)}")
                
        # Use the official Pocketful binary decoder for snapquote data
        try:
            # Check minimum message length for snapquote data
            if not message or len(message) < 166:  # Minimum size for snapquote
                logger.warning(f"Message too short for snapquote data: {len(message) if message else 0} bytes")
                return {}
                
            return {
                "mode": struct.unpack('>b', message[0:1])[0],
                "exchange_code": struct.unpack('>b', message[1:2])[0],
                "instrument_token": struct.unpack('>I', message[2:6])[0],
                "buyers": [
                    struct.unpack('>I', message[6:10])[0],
                    struct.unpack('>I', message[10:14])[0],
                    struct.unpack('>I', message[14:18])[0],
                    struct.unpack('>I', message[18:22])[0],
                    struct.unpack('>I', message[22:26])[0]
                ],
                "bidPrices": [
                    struct.unpack('>I', message[26:30])[0],
                    struct.unpack('>I', message[30:34])[0],
                    struct.unpack('>I', message[34:38])[0],
                    struct.unpack('>I', message[38:42])[0],
                    struct.unpack('>I', message[42:46])[0]
                ],
                "bidQtys": [
                    struct.unpack('>I', message[46:50])[0],
                    struct.unpack('>I', message[50:54])[0],
                    struct.unpack('>I', message[54:58])[0],
                    struct.unpack('>I', message[58:62])[0],
                    struct.unpack('>I', message[62:66])[0]
                ],
                "sellers": [
                    struct.unpack('>I', message[66:70])[0],
                    struct.unpack('>I', message[70:74])[0],
                    struct.unpack('>I', message[74:78])[0],
                    struct.unpack('>I', message[78:82])[0],
                    struct.unpack('>I', message[82:86])[0]
                ],
                "askPrices": [
                    struct.unpack('>I', message[86:90])[0],
                    struct.unpack('>I', message[90:94])[0],
                    struct.unpack('>I', message[94:98])[0],
                    struct.unpack('>I', message[98:102])[0],
                    struct.unpack('>I', message[102:106])[0]
                ],
                "askQtys": [
                    struct.unpack('>I', message[106:110])[0],
                    struct.unpack('>I', message[110:114])[0],
                    struct.unpack('>I', message[114:118])[0],
                    struct.unpack('>I', message[118:122])[0],
                    struct.unpack('>I', message[122:126])[0]
                ],
                "averageTradePrice": struct.unpack('>I', message[126:130])[0],
                "open": struct.unpack('>I', message[130:134])[0],
                "high": struct.unpack('>I', message[134:138])[0],
                "low": struct.unpack('>I', message[138:142])[0],
                "close": struct.unpack('>I', message[142:146])[0],
                "totalBuyQty": struct.unpack('>Q', message[146:154])[0],
                "totalSellQty": struct.unpack('>Q', message[154:162])[0],
                "volume": struct.unpack('>I', message[162:166])[0],
            }
                
        except Exception as e:
            logger.error(f"Binary parsing failed: {str(e)}")
            return {}
            
    except Exception as e:
        logger.error(f"Error decoding snapquote data: {str(e)}")
        return {}

def decodeDetailedMarketData(message):
    """
    Decode detailed market data using the official Pocketful implementation
    """
    try:
        # Check if we have enough bytes for detailed market data packet
        if not message or len(message) < 102:  # Minimum size for detailed market data
            logger.warning(f"Message too short for detailed market data: {len(message) if message else 0} bytes")
            return {}
            
        return {
            "mode": struct.unpack('>b', message[0:1])[0],
            "exchange_code": struct.unpack('>b', message[1:2])[0],
            "instrument_token": struct.unpack('>I', message[2:6])[0],
            "last_traded_price": struct.unpack('>I', message[6:10])[0],
            "last_traded_time": struct.unpack('>I', message[10:14])[0],
            "last_traded_quantity": struct.unpack('>I', message[14:18])[0],
            "trade_volume": struct.unpack('>I', message[18:22])[0],
            "best_bid_price": struct.unpack('>I', message[22:26])[0],
            "best_bid_quantity": struct.unpack('>I', message[26:30])[0],
            "best_ask_price": struct.unpack('>I', message[30:34])[0],
            "best_ask_quantity": struct.unpack('>I', message[34:38])[0],
            "total_buy_quantity": struct.unpack('>Q', message[38:46])[0],
            "total_sell_quantity": struct.unpack('>Q', message[46:54])[0],
            "average_trade_price": struct.unpack('>I', message[54:58])[0],
            "exchange_timestamp": struct.unpack('>I', message[58:62])[0],
            "open_price": struct.unpack('>I', message[62:66])[0],
            "high_price": struct.unpack('>I', message[66:70])[0],
            "low_price": struct.unpack('>I', message[70:74])[0],
            "close_price": struct.unpack('>I', message[74:78])[0],
            "yearly_high_price": struct.unpack('>I', message[78:82])[0],
            "yearly_low_price": struct.unpack('>I', message[82:86])[0],
            "lowDPR": struct.unpack('>I', message[86:90])[0],
            "highDPR": struct.unpack('>I', message[90:94])[0],
            "currentOpenInterest": struct.unpack('>I', message[94:98])[0],
            "initialOpenInterest": struct.unpack('>I', message[98:102])[0],
        }
    except Exception as e:
        logger.error(f"Error decoding detailed market data: {str(e)}")
        return {}

def decodeCompactMarketData(message):
    """
    Decode compact market data from binary message or JSON
    Based on Pocketful API format with mode=2
    """
    try:
        logger.debug(f"Decoding compact market data message: {message[:100]}{'...' if len(str(message)) > 100 else ''}")
        
        # Handle JSON format
        if isinstance(message, str):
            try:
                data = json.loads(message)
                logger.debug(f"Parsed JSON data: {data}")
                
                # Standardize field names
                if isinstance(data, dict):
                    # Direct dict with expected fields
                    if 'instrument_token' in data or 'instrumentToken' in data:
                        # Standardize key names
                        if 'instrumentToken' in data and 'instrument_token' not in data:
                            data['instrument_token'] = data['instrumentToken']
                        if 'exchangeCode' in data and 'exchange_code' not in data:
                            data['exchange_code'] = data['exchangeCode']
                        return data
                    
                    # Nested data in 'd' field
                    if 'd' in data and isinstance(data['d'], dict):
                        result = data['d']
                        # Standardize key names
                        if 'instrumentToken' in result and 'instrument_token' not in result:
                            result['instrument_token'] = result['instrumentToken']
                        if 'exchangeCode' in result and 'exchange_code' not in result:
                            result['exchange_code'] = result['exchangeCode']
                        return result
                        
                    # Nested data in 'data' field  
                    if 'data' in data and isinstance(data['data'], dict):
                        result = data['data']
                        # Standardize key names
                        if 'instrumentToken' in result and 'instrument_token' not in result:
                            result['instrument_token'] = result['instrumentToken']
                        if 'exchangeCode' in result and 'exchange_code' not in result:
                            result['exchange_code'] = result['exchangeCode']
                        return result
                
                logger.debug(f"JSON format not recognized: {data}")
            except Exception as e:
                logger.debug(f"JSON parsing failed: {str(e)}")
        
        # Use the official Pocketful binary decoder
        try:
            # Check if we have enough bytes for the basic header
            if not message or len(message) < 42:  # Minimum size for compact market data
                logger.warning(f"Message too short for compact data parsing: {len(message) if message else 0} bytes")
                return {}
            
            result = {
                "mode": struct.unpack('>b', message[0:1])[0],
                "exchange_code": struct.unpack('>b', message[1:2])[0],
                "instrument_token": struct.unpack('>I', message[2:6])[0],
                "last_traded_price": struct.unpack('>I', message[6:10])[0],
                "change": struct.unpack('>I', message[10:14])[0],
                "last_traded_time": struct.unpack('>I', message[14:18])[0],
                "lowDPR": struct.unpack('>I', message[18:22])[0],
                "highDPR": struct.unpack('>I', message[22:26])[0],
                "currentOpenInterest": struct.unpack('>I', message[26:30])[0],
                "initialOpenInterest": struct.unpack('>I', message[30:34])[0],
                "bidPrice": struct.unpack('>I', message[34:38])[0],
                "askPrice": struct.unpack('>I', message[38:42])[0],
            }
            
            logger.debug(f"Decoded compact market data: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Binary parsing failed: {str(e)}")
            return {}
            
    except Exception as e:
        logger.error(f"Error decoding compact market data: {str(e)}")
        return {}

def decodeOrderUpdate(message):
    """
    Decode order update messages according to official Pocketful implementation
    """
    try:
        order_update_packet = message.decode("utf-8")
        order_update_obj = json.loads(order_update_packet[5:])
        return order_update_obj
    except Exception as e:
        logger.error(f"Error decoding order update: {str(e)}")
        return {}

def decodeTradeUpdate(message):
    """
    Decode trade update messages according to official Pocketful implementation
    """
    try:
        trade_update_packet = message.decode("utf-8")
        trade_update_obj = json.loads(trade_update_packet[5:])
        return trade_update_obj
    except Exception as e:
        logger.error(f"Error decoding trade update: {str(e)}")
        return {}

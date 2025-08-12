#!/usr/bin/env python3
"""
Fyers Protobuf Parser Implementation
Based on official Fyers protobuf schema from https://public.fyers.in/tbtproto/1.0.0/msg.proto
"""

import struct
import logging
from typing import Dict, List, Any, Optional


class FyersProtoParser:
    """
    Fyers protobuf parser using manual decoding
    
    This implements the Fyers TBT protobuf schema without requiring
    the protobuf library, making it more lightweight and portable.
    """
    
    def __init__(self):
        self.logger = logging.getLogger("fyers_proto_parser")
    
    def parse_market_data(self, data: bytes) -> Dict[str, Any]:
        """
        Parse Fyers protobuf market data
        
        Args:
            data: Binary protobuf data from Fyers WebSocket
            
        Returns:
            Dict: Parsed market data structure
        """
        try:
            parsed_data = {
                'data_type': 'market_data',
                'raw_length': len(data)
            }
            
            # Parse the protobuf data
            pos = 0
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if field_data:
                    self._process_field(field_data, parsed_data)
                    
                # Safety check to prevent infinite loops
                if pos >= len(data):
                    break
            
            # Always try fallback parsing to improve symbol/token detection
            self.logger.info(f"Before fallback: symbol={parsed_data.get('symbol')}, token={parsed_data.get('token')}")
            self._try_fallback_parsing(data, parsed_data)
            self.logger.info(f"After fallback: symbol={parsed_data.get('symbol')}, token={parsed_data.get('token')}")
            
            return parsed_data
            
        except Exception as e:
            self.logger.error(f"Error parsing protobuf data: {e}")
            return {
                'data_type': 'market_data',
                'raw_length': len(data),
                'error': str(e),
                'raw_preview': data[:100].hex() if data else 'empty'
            }
    
    def _try_fallback_parsing(self, data: bytes, parsed_data: Dict):
        """
        Fallback parsing using simple string search for symbol and token
        """
        try:
            # Try to decode as UTF-8 and look for patterns
            data_str = data.decode('utf-8', errors='ignore')
            self.logger.info(f"Fallback parsing data preview (first 200 chars): {data_str[:200]}")
            
            import re
            
            # Look for symbol patterns - always run this
            symbol_patterns = [
                r'NSE:[A-Z0-9]+-EQ',      # NSE equity format
                r'NSE:[A-Z0-9]+FUT',      # NSE futures format (NFO)
                r'BSE:[A-Z0-9]+-[A-Z]',   # BSE equity format
                r'MCX:[A-Z0-9]+FUT',      # MCX futures format
                r'NSE:[A-Z0-9]+-INDEX',   # NSE index format
            ]
            
            for pattern in symbol_patterns:
                match = re.search(pattern, data_str)
                if match:
                    if not parsed_data.get('symbol') or parsed_data['symbol'] != match.group():
                        parsed_data['symbol'] = match.group()
                        self.logger.info(f"Fallback found symbol: {parsed_data['symbol']}")
                    break
                    
            self.logger.info(f"Symbol search completed, found: {parsed_data.get('symbol')}")
            
            # Look for token patterns (typically 14-15 digits) - always run this
            token_match = re.search(r'\b\d{14,15}\b', data_str)
            if token_match:
                if not parsed_data.get('token') or parsed_data['token'] != token_match.group():
                    parsed_data['token'] = token_match.group()
                    self.logger.info(f"Fallback found token: {parsed_data['token']}")
            
            # Also try shorter tokens (10-13 digits) as fallback
            if not parsed_data.get('token'):
                short_token_match = re.search(r'\b\d{10,13}\b', data_str)
                if short_token_match:
                    parsed_data['token'] = short_token_match.group()
                    self.logger.info(f"Fallback found shorter token: {parsed_data['token']}")
                    
            self.logger.info(f"Token search completed, found: {parsed_data.get('token')}")
                    
        except Exception as e:
            self.logger.debug(f"Fallback parsing error: {e}")
    
    
    def _parse_field(self, data: bytes, pos: int) -> tuple:
        """
        Parse a single protobuf field
        
        Returns:
            Tuple of (field_data, new_position)
        """
        if pos >= len(data):
            return None, pos
            
        try:
            # Read the tag (field number + wire type)
            tag, pos = self._decode_varint(data, pos)
            if tag is None:
                return None, pos
                
            field_number = tag >> 3
            wire_type = tag & 0x07
            
            field_data = {
                'field_number': field_number,
                'wire_type': wire_type
            }
            
            # Parse based on wire type
            if wire_type == 0:  # Varint
                value, pos = self._decode_varint(data, pos)
                field_data['value'] = value
                
            elif wire_type == 1:  # Fixed64
                if pos + 8 <= len(data):
                    value = struct.unpack('<Q', data[pos:pos+8])[0]
                    field_data['value'] = value
                    pos += 8
                else:
                    return None, pos
                    
            elif wire_type == 2:  # Length-delimited
                length, pos = self._decode_varint(data, pos)
                if length is not None and pos + length <= len(data):
                    value = data[pos:pos+length]
                    field_data['value'] = value
                    field_data['length'] = length
                    pos += length
                else:
                    return None, pos
                    
            elif wire_type == 5:  # Fixed32
                if pos + 4 <= len(data):
                    value = struct.unpack('<I', data[pos:pos+4])[0]
                    field_data['value'] = value
                    pos += 4
                else:
                    return None, pos
            else:
                # Unknown wire type - skip
                return None, pos
                
            return field_data, pos
            
        except Exception as e:
            self.logger.debug(f"Error parsing field at position {pos}: {e}")
            return None, pos + 1  # Skip this byte and continue
    
    def _decode_varint(self, data: bytes, pos: int) -> tuple:
        """
        Decode protobuf varint
        
        Returns:
            Tuple of (value, new_position)
        """
        if pos >= len(data):
            return None, pos
            
        try:
            result = 0
            shift = 0
            
            while pos < len(data):
                byte = data[pos]
                result |= (byte & 0x7F) << shift
                pos += 1
                
                if (byte & 0x80) == 0:  # MSB is 0, this is the last byte
                    return result, pos
                    
                shift += 7
                if shift >= 64:  # Prevent infinite loop
                    break
            
            return result, pos
            
        except Exception as e:
            self.logger.debug(f"Varint decode error: {e}")
            return None, pos
    
    def _process_field(self, field_data: Dict, parsed_data: Dict):
        """
        Process a parsed field based on Fyers protobuf schema
        
        Field mapping based on Fyers schema:
        - Field 1: Token
        - Field 2: Symbol/Ticker
        - Field 3: Quote data
        - Field 4: Depth data
        - Field 5: OHLCV data
        """
        field_num = field_data['field_number']
        value = field_data.get('value')
        wire_type = field_data.get('wire_type')
        
        if value is None:
            return
        
        try:
            # Map fields based on Fyers protobuf schema
            if field_num == 1:  # Token
                if isinstance(value, int):
                    parsed_data['token'] = str(value)
                    
            elif field_num == 2:  # Symbol/Ticker
                if wire_type == 2:  # String
                    try:
                        symbol = value.decode('utf-8', errors='ignore')
                        if symbol and len(symbol) > 3:  # Valid symbol
                            parsed_data['symbol'] = symbol
                    except:
                        pass
                        
            elif field_num == 3:  # Quote data (embedded message)
                if wire_type == 2:
                    quote_data = self._parse_quote_data(value)
                    if quote_data:
                        parsed_data.update(quote_data)
                        
            elif field_num == 4:  # Depth data (embedded message)
                if wire_type == 2:
                    depth_data = self._parse_depth_data(value)
                    if depth_data:
                        parsed_data['depth'] = depth_data
                        
            elif field_num == 5:  # OHLCV data
                if wire_type == 2:
                    ohlcv_data = self._parse_ohlcv_data(value)
                    if ohlcv_data:
                        parsed_data.update(ohlcv_data)
            
            # Additional parsing for any string field that might contain symbol
            elif wire_type == 2:  # Length-delimited (string or bytes)
                try:
                    string_val = value.decode('utf-8', errors='ignore')
                    # Look for symbol patterns in any string field
                    import re
                    symbol_patterns = [
                        r'NSE:[A-Z0-9]+-EQ',      # NSE equity format
                        r'NSE:[A-Z0-9]+FUT',      # NSE futures format (NFO)
                        r'BSE:[A-Z0-9]+-[A-Z]',   # BSE equity format
                        r'MCX:[A-Z0-9]+FUT',      # MCX futures format
                        r'NSE:[A-Z0-9]+-INDEX',   # NSE index format
                    ]
                    
                    for pattern in symbol_patterns:
                        match = re.search(pattern, string_val)
                        if match and not parsed_data.get('symbol'):
                            parsed_data['symbol'] = match.group()
                            self.logger.info(f"Found symbol in field {field_num}: {parsed_data['symbol']}")
                            break
                except:
                    pass
                        
            # Look for price-like values in any varint field
            elif wire_type == 0 and isinstance(value, int):
                self.logger.debug(f"Processing varint field {field_num} with value {value}")
                
                # Check if this could be a price (reasonable range)
                if 10000 <= value <= 10000000:  # Price in paise (100 paise = 1 rupee)
                    price = value / 100.0
                    if 'prices' not in parsed_data:
                        parsed_data['prices'] = []
                    parsed_data['prices'].append({
                        'field': field_num,
                        'value': round(price, 2),
                        'format': 'varint/100'
                    })
                    
                    # Use first reasonable price as probable LTP
                    if 'probable_ltp' not in parsed_data:
                        parsed_data['probable_ltp'] = round(price, 2)
                        self.logger.info(f"Found probable LTP in field {field_num}: {parsed_data['probable_ltp']}")
                
                # Also check for smaller price ranges (in case price is not in paise format)
                elif 100 <= value <= 100000:  # Direct rupee values
                    price = float(value)
                    if 'prices' not in parsed_data:
                        parsed_data['prices'] = []
                    parsed_data['prices'].append({
                        'field': field_num,
                        'value': round(price, 2),
                        'format': 'direct_rupee'
                    })
                    
                    # Use as probable LTP if none found yet
                    if 'probable_ltp' not in parsed_data:
                        parsed_data['probable_ltp'] = round(price, 2)
                        self.logger.info(f"Found probable LTP (direct) in field {field_num}: {parsed_data['probable_ltp']}")
                
                # Also check for token patterns in large integers
                elif 10000000000000 <= value <= 99999999999999:  # 14-digit tokens
                    if not parsed_data.get('token'):
                        parsed_data['token'] = str(value)
                        self.logger.info(f"Found token in field {field_num}: {parsed_data['token']}")
                        
        except Exception as e:
            self.logger.debug(f"Error processing field {field_num}: {e}")
    
    def _parse_quote_data(self, data: bytes) -> Optional[Dict]:
        """
        Parse Quote submessage
        
        Quote fields:
        - ltp: Last Traded Price
        - ltt: Last Traded Time  
        - ltq: Last Traded Quantity
        - vtt: Volume Traded Today
        - oi: Open Interest
        """
        try:
            quote_data = {}
            pos = 0
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                
                if value is None:
                    continue
                
                # Map quote fields
                if field_num == 1 and isinstance(value, int):  # LTP
                    quote_data['ltp'] = value / 100.0  # Convert paise to rupees
                elif field_num == 2 and isinstance(value, int):  # Last trade time
                    quote_data['ltt'] = value
                elif field_num == 3 and isinstance(value, int):  # Last trade quantity
                    quote_data['ltq'] = value
                elif field_num == 4 and isinstance(value, int):  # Volume traded today
                    quote_data['volume'] = value
                elif field_num == 5 and isinstance(value, int):  # Open interest
                    quote_data['oi'] = value
            
            return quote_data if quote_data else None
            
        except Exception as e:
            self.logger.debug(f"Error parsing quote data: {e}")
            return None
    
    def _parse_depth_data(self, data: bytes) -> Optional[Dict]:
        """
        Parse Depth submessage
        
        Depth fields:
        - tbq: Total Buy Quantity
        - tsq: Total Sell Quantity  
        - bids: Bid levels
        - asks: Ask levels
        """
        try:
            depth_data = {
                'buy': [],
                'sell': []
            }
            
            pos = 0
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                
                if value is None:
                    continue
                
                # Map depth fields
                if field_num == 1 and isinstance(value, int):  # Total buy quantity
                    depth_data['total_buy_quantity'] = value
                elif field_num == 2 and isinstance(value, int):  # Total sell quantity
                    depth_data['total_sell_quantity'] = value
                elif field_num == 3:  # Bid levels (repeated)
                    if field_data['wire_type'] == 2:
                        level = self._parse_market_level(value)
                        if level:
                            depth_data['buy'].append(level)
                elif field_num == 4:  # Ask levels (repeated)
                    if field_data['wire_type'] == 2:
                        level = self._parse_market_level(value)
                        if level:
                            depth_data['sell'].append(level)
            
            return depth_data if (depth_data['buy'] or depth_data['sell']) else None
            
        except Exception as e:
            self.logger.debug(f"Error parsing depth data: {e}")
            return None
    
    def _parse_market_level(self, data: bytes) -> Optional[Dict]:
        """
        Parse MarketLevel submessage
        
        MarketLevel fields:
        - price: Price
        - qty: Quantity
        - nord: Number of orders
        - num: Level number
        """
        try:
            level = {}
            pos = 0
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                
                if value is None:
                    continue
                
                if field_num == 1 and isinstance(value, int):  # Price
                    level['price'] = value / 100.0  # Convert paise to rupees
                elif field_num == 2 and isinstance(value, int):  # Quantity
                    level['quantity'] = value
                elif field_num == 3 and isinstance(value, int):  # Number of orders
                    level['orders'] = value
                elif field_num == 4 and isinstance(value, int):  # Level number
                    level['num'] = value
            
            return level if level else None
            
        except Exception as e:
            self.logger.debug(f"Error parsing market level: {e}")
            return None
    
    def _parse_ohlcv_data(self, data: bytes) -> Optional[Dict]:
        """
        Parse OHLCV submessage for daily/historical data
        """
        try:
            ohlcv_data = {}
            pos = 0
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                
                if value is None:
                    continue
                
                # Map OHLCV fields
                if field_num == 1 and isinstance(value, int):  # Open
                    ohlcv_data['open'] = value / 100.0
                elif field_num == 2 and isinstance(value, int):  # High
                    ohlcv_data['high'] = value / 100.0
                elif field_num == 3 and isinstance(value, int):  # Low
                    ohlcv_data['low'] = value / 100.0
                elif field_num == 4 and isinstance(value, int):  # Close
                    ohlcv_data['close'] = value / 100.0
                elif field_num == 5 and isinstance(value, int):  # Volume
                    ohlcv_data['volume'] = value
            
            return ohlcv_data if ohlcv_data else None
            
        except Exception as e:
            self.logger.debug(f"Error parsing OHLCV data: {e}")
            return None
"""
Minimal protobuf parser for Groww market data
Parses binary protobuf messages without external protobuf library
"""

import struct
import logging
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Protobuf wire types
VARINT = 0
FIXED64 = 1
LENGTH_DELIMITED = 2
FIXED32 = 5

# Field numbers from Groww's proto definition
FIELD_SYMBOL = 1
FIELD_SEGMENT = 2
FIELD_EXCHANGE = 3
FIELD_STOCK_LIVE_PRICE = 4
FIELD_MARKET_DEPTH = 5
FIELD_LIVE_INDICES = 6

# StocksLivePriceProto field numbers
FIELD_TS_IN_MILLIS = 1
FIELD_OPEN = 2
FIELD_HIGH = 3
FIELD_LOW = 4
FIELD_CLOSE = 5
FIELD_VOLUME = 6
FIELD_VALUE = 7
FIELD_LTP = 13


class MiniProtobufParser:
    """
    Minimal protobuf parser for Groww market data
    """
    
    def __init__(self):
        self.data = b""
        self.position = 0
        
    def parse_market_data(self, data: bytes) -> Dict[str, Any]:
        """
        Parse Groww market data from protobuf
        
        Args:
            data: Binary protobuf data
            
        Returns:
            Parsed market data dictionary
        """
        self.data = data
        self.position = 0
        result = {}
        
        try:
            while self.position < len(self.data):
                field_num, wire_type = self._read_tag()
                if field_num == 0:
                    break
                    
                if field_num == FIELD_SYMBOL:
                    result['symbol'] = self._read_string()
                elif field_num == FIELD_SEGMENT:
                    segment_val = self._read_varint()
                    result['segment'] = self._decode_segment(segment_val)
                elif field_num == FIELD_EXCHANGE:
                    exchange_val = self._read_varint()
                    result['exchange'] = self._decode_exchange(exchange_val)
                elif field_num == FIELD_STOCK_LIVE_PRICE:
                    # Nested message for live price
                    result['ltp_data'] = self._parse_live_price()
                elif field_num == FIELD_MARKET_DEPTH:
                    # Nested message for market depth
                    result['depth_data'] = self._parse_market_depth()
                elif field_num == FIELD_LIVE_INDICES:
                    # Nested message for indices
                    result['index_data'] = self._parse_live_indices()
                else:
                    # Skip unknown fields
                    self._skip_field(wire_type)
                    
        except Exception as e:
            logger.error(f"Error parsing protobuf: {e}")
            # Return what we have so far
            
        return result
    
    def _read_tag(self) -> Tuple[int, int]:
        """Read field tag (field number and wire type)"""
        if self.position >= len(self.data):
            return 0, 0
            
        tag = self._read_varint()
        field_num = tag >> 3
        wire_type = tag & 0x07
        return field_num, wire_type
    
    def _read_varint(self) -> int:
        """Read variable-length integer"""
        result = 0
        shift = 0
        
        while self.position < len(self.data):
            byte = self.data[self.position]
            self.position += 1
            
            result |= (byte & 0x7F) << shift
            shift += 7
            
            if (byte & 0x80) == 0:
                break
                
        return result
    
    def _read_fixed32(self) -> float:
        """Read 32-bit fixed value"""
        if self.position + 4 > len(self.data):
            return 0.0
            
        value = struct.unpack('<f', self.data[self.position:self.position + 4])[0]
        self.position += 4
        return value
    
    def _read_fixed64(self) -> float:
        """Read 64-bit fixed value (double)"""
        if self.position + 8 > len(self.data):
            return 0.0
            
        value = struct.unpack('<d', self.data[self.position:self.position + 8])[0]
        self.position += 8
        return value
    
    def _read_string(self) -> str:
        """Read length-delimited string"""
        length = self._read_varint()
        if self.position + length > len(self.data):
            return ""
            
        value = self.data[self.position:self.position + length].decode('utf-8', errors='ignore')
        self.position += length
        return value
    
    def _read_bytes(self) -> bytes:
        """Read length-delimited bytes"""
        length = self._read_varint()
        if self.position + length > len(self.data):
            return b""
            
        value = self.data[self.position:self.position + length]
        self.position += length
        return value
    
    def _skip_field(self, wire_type: int):
        """Skip unknown field based on wire type"""
        if wire_type == VARINT:
            self._read_varint()
        elif wire_type == FIXED64:
            self.position += 8
        elif wire_type == LENGTH_DELIMITED:
            length = self._read_varint()
            self.position += length
        elif wire_type == FIXED32:
            self.position += 4
    
    def _parse_live_price(self) -> Dict[str, Any]:
        """Parse StocksLivePriceProto message"""
        length = self._read_varint()
        end_pos = self.position + length
        
        result = {}
        
        while self.position < end_pos:
            field_num, wire_type = self._read_tag()
            if field_num == 0:
                break
                
            if field_num == FIELD_TS_IN_MILLIS:
                result['timestamp'] = self._read_fixed64()
            elif field_num == FIELD_OPEN:
                result['open'] = self._read_fixed64()
            elif field_num == FIELD_HIGH:
                result['high'] = self._read_fixed64()
            elif field_num == FIELD_LOW:
                result['low'] = self._read_fixed64()
            elif field_num == FIELD_CLOSE:
                result['close'] = self._read_fixed64()
            elif field_num == FIELD_VOLUME:
                result['volume'] = self._read_fixed64()
            elif field_num == FIELD_VALUE:
                result['value'] = self._read_fixed64()
            elif field_num == FIELD_LTP:
                result['ltp'] = self._read_fixed64()  # Price is already in correct format
            else:
                self._skip_field(wire_type)
                
        self.position = end_pos
        return result
    
    def _parse_market_depth(self) -> Dict[str, Any]:
        """Parse market depth message"""
        length = self._read_varint()
        end_pos = self.position + length

        # Log depth message size for BSE vs NSE debugging
        total_size = len(self.data)
        logger.info(f"📊 Parsing depth message: inner length={length} bytes, total message={total_size} bytes")
        if total_size == 501:
            logger.info("🔴 BSE depth message detected (501 bytes)")
        elif total_size == 499:
            logger.info("✅ NSE depth message detected (499 bytes)")

        result = {
            'timestamp': 0,
            'buy': [],
            'sell': []
        }
        
        # Parse depth data fields
        while self.position < end_pos:
            field_num, wire_type = self._read_tag()
            if field_num == 0:
                break
                
            if field_num == 1:  # tsInMillis
                result['timestamp'] = self._read_fixed64()
            elif field_num == 2:  # Buy levels (repeated)
                # Parse buy depth level
                level_data = self._parse_depth_level()
                if level_data:
                    result['buy'].append(level_data)
                    logger.debug(f"Added buy level: {level_data}")
            elif field_num == 3:  # Sell levels (repeated)
                # Parse sell depth level
                level_data = self._parse_depth_level()
                if level_data:
                    result['sell'].append(level_data)
                    logger.debug(f"Added sell level: {level_data}")
            else:
                logger.debug(f"Unknown field {field_num} in depth message, skipping")
                self._skip_field(wire_type)
                
        self.position = end_pos
        return result
    
    def _parse_depth_level(self) -> Dict[str, Any]:
        """Parse a single depth level"""
        length = self._read_varint()
        end_pos = self.position + length
        
        level = {
            'price': 0.0,
            'quantity': 0,
            'orders': 0
        }
        
        while self.position < end_pos:
            field_num, wire_type = self._read_tag()
            if field_num == 0:
                break
                
            if field_num == 1:  # Order count
                level['orders'] = self._read_varint()
            elif field_num == 2:  # Price and quantity (nested message)
                # Parse price/quantity submessage
                sub_length = self._read_varint()
                sub_end = self.position + sub_length
                
                while self.position < sub_end:
                    sub_field, sub_wire = self._read_tag()
                    if sub_field == 1:  # Price (raw value needs no conversion)
                        level['price'] = self._read_fixed64()
                    elif sub_field == 2:  # Quantity
                        level['quantity'] = int(self._read_fixed64())  # Convert to int
                    else:
                        self._skip_field(sub_wire)
                        
                self.position = sub_end
            else:
                self._skip_field(wire_type)
                
        self.position = end_pos
        return level
    
    def _parse_live_indices(self) -> Dict[str, Any]:
        """Parse live indices message"""
        length = self._read_varint()
        end_pos = self.position + length
        
        result = {}
        
        while self.position < end_pos:
            field_num, wire_type = self._read_tag()
            if field_num == 0:
                break
                
            if field_num == 1:  # tsInMillis
                result['timestamp'] = self._read_fixed64()
            elif field_num == 2:  # value
                result['value'] = self._read_fixed64()
            else:
                self._skip_field(wire_type)
                
        self.position = end_pos
        return result
    
    def _decode_exchange(self, value: int) -> str:
        """Decode exchange enum"""
        exchanges = {
            0: "BSE",
            1: "NSE",
            2: "MCX",
            3: "MCXSX",
            4: "NCDEX",
            5: "GLOBAL",
            6: "US"
        }
        return exchanges.get(value, "UNKNOWN")
    
    def _decode_segment(self, value: int) -> str:
        """Decode segment enum"""
        segments = {
            0: "CASH",
            1: "FNO",
            2: "CURRENCY",
            3: "COMMODITY"
        }
        return segments.get(value, "UNKNOWN")


def parse_groww_market_data(data: bytes) -> Dict[str, Any]:
    """
    Convenience function to parse Groww market data

    Args:
        data: Binary protobuf data

    Returns:
        Parsed market data
    """
    data_len = len(data)
    logger.info(f"Parsing protobuf data: {data_len} bytes")

    # Special logging for BSE data (501 bytes) vs NSE (499 bytes)
    if data_len == 501:
        logger.info("🔴 Potential BSE message detected (501 bytes)")
    elif data_len == 499:
        logger.info("✅ Potential NSE message detected (499 bytes)")

    # For BSE depth messages, check if there's an extra field
    if data_len == 501:
        logger.debug(f"BSE message - Last 10 bytes (hex): {data[-10:].hex()}")

    logger.debug(f"First 50 bytes (hex): {data[:50].hex() if len(data) > 50 else data.hex()}")

    parser = MiniProtobufParser()
    result = parser.parse_market_data(data)

    # Log what was parsed
    if result:
        logger.info(f"Successfully parsed protobuf data: {result.keys()}")
        if 'ltp_data' in result:
            logger.info(f"LTP data found: {result['ltp_data']}")
        if 'index_data' in result:
            logger.info(f"Index data found: {result['index_data']}")
        if 'depth_data' in result:
            logger.info(f"Depth data found: {result['depth_data']}")
    else:
        logger.warning("No data parsed from protobuf")

    return result
#!/usr/bin/env python3
"""
Official Fyers Protobuf Parser
Based on the exact structure from msg.proto file
"""

import struct
import logging
from typing import Dict, List, Any, Optional


class FyersOfficialProtoParser:
    """
    Fyers protobuf parser following the exact official schema from msg.proto
    
    Structure:
    SocketMessage {
        MessageType type = 1;
        map<string, MarketFeed> feeds = 2;
        bool snapshot = 3;
        string msg = 4;
        bool error = 5;
    }
    
    MarketFeed {
        Quote quote = 1;               // Contains LTP!
        ExtendedQuote eq = 2;
        DailyQuote dq = 3;
        OHLCV ohlcv = 4;
        Depth depth = 5;
        UInt64Value feed_time = 6;
        UInt64Value send_time = 7;
        string token = 8;
        uint64 sequence_no = 9;
        bool snapshot = 10;
        string ticker = 11;
        SymDetail symdetail = 12;
    }
    
    Quote {
        Int64Value ltp = 1;            // Last Traded Price (THE REAL LTP!)
        UInt32Value ltt = 2;           // Last Traded Time
        UInt32Value ltq = 3;           // Last Traded Quantity
        UInt64Value vtt = 4;           // Volume Traded Today
        UInt64Value vtt_diff = 5;
        UInt64Value oi = 6;            // Open Interest
        Int64Value ltpc = 7;           // LTP Change
    }
    """
    
    def __init__(self):
        self.logger = logging.getLogger("fyers_official_proto")
    
    def parse_socket_message(self, data: bytes) -> Dict[str, Any]:
        """
        Parse SocketMessage according to official schema
        
        Returns:
            Dict with parsed market data including correct LTP
        """
        try:
            result = {
                'data_type': 'socket_message',
                'raw_length': len(data)
            }
            
            pos = 0
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 0:  # MessageType type
                    result['message_type'] = value
                    self.logger.info(f"Message type: {value}")
                    
                elif field_num == 2 and wire_type == 2:  # map<string, MarketFeed> feeds
                    self.logger.info(f"Parsing feeds map (the important data!)")
                    feeds_data = self._parse_feeds_map(value)
                    if feeds_data:
                        result.update(feeds_data)
                        
                elif field_num == 3 and wire_type == 0:  # bool snapshot
                    result['snapshot'] = bool(value)
                    
                elif field_num == 4 and wire_type == 2:  # string msg
                    try:
                        result['msg'] = value.decode('utf-8', errors='ignore')
                    except:
                        pass
                        
                elif field_num == 5 and wire_type == 0:  # bool error
                    result['error'] = bool(value)
                    
                if pos >= len(data):
                    break
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing SocketMessage: {e}")
            return {'error': str(e), 'raw_length': len(data)}
    
    def _parse_feeds_map(self, data: bytes) -> Optional[Dict]:
        """
        Parse the feeds map which contains the actual market data
        
        Format: map<string, MarketFeed>
        Each entry has: field 1 = key (symbol), field 2 = value (MarketFeed)
        """
        try:
            pos = 0
            result = {}
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 2:  # Map key (symbol/token)
                    try:
                        symbol = value.decode('utf-8', errors='ignore')
                        result['symbol_key'] = symbol
                        self.logger.info(f"Feeds map key: {symbol}")
                    except:
                        pass
                        
                elif field_num == 2 and wire_type == 2:  # Map value (MarketFeed)
                    self.logger.info(f"Parsing MarketFeed (contains Quote with LTP!)")
                    market_feed = self._parse_market_feed(value)
                    if market_feed:
                        result.update(market_feed)
                        
                if pos >= len(data):
                    break
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing feeds map: {e}")
            return None
    
    def _parse_market_feed(self, data: bytes) -> Optional[Dict]:
        """
        Parse MarketFeed message according to official schema
        
        This is where the Quote message (field 1) contains the real LTP!
        """
        try:
            pos = 0
            result = {}
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                # Debug: Log ALL fields found in MarketFeed
                self.logger.info(f"MarketFeed field {field_num} (wire_type {wire_type})")
                
                if field_num == 1 and wire_type == 2:  # Quote message - THE IMPORTANT ONE!
                    self.logger.info(f"🎯 Found Quote message (contains LTP!)")
                    quote_data = self._parse_quote_message(value)
                    if quote_data:
                        result.update(quote_data)
                        
                elif field_num == 2 and wire_type == 2:  # ExtendedQuote
                    self.logger.info(f"Found ExtendedQuote")
                    # Could parse this for additional price data
                    
                elif field_num == 3 and wire_type == 2:  # DailyQuote  
                    self.logger.info(f"Found DailyQuote - parsing OHLC data")
                    daily_quote_data = self._parse_daily_quote_message(value)
                    if daily_quote_data:
                        result.update(daily_quote_data)
                    
                elif field_num == 4 and wire_type == 2:  # OHLCV
                    self.logger.info(f"Found OHLCV")
                    
                elif field_num == 5 and wire_type == 2:  # Depth
                    self.logger.info(f"Found Depth - parsing for potential LTP in bid/ask")
                    depth_data = self._parse_depth_message(value)
                    if depth_data:
                        result.update(depth_data)
                    
                elif field_num == 6 and wire_type == 2:  # feed_time (UInt64Value)
                    feed_time = self._parse_uint64_wrapper(value)
                    if feed_time:
                        result['feed_time'] = feed_time
                        
                elif field_num == 7 and wire_type == 2:  # send_time (UInt64Value)
                    send_time = self._parse_uint64_wrapper(value)
                    if send_time:
                        result['send_time'] = send_time
                        
                elif field_num == 8 and wire_type == 2:  # token (string)
                    try:
                        result['token'] = value.decode('utf-8', errors='ignore')
                        self.logger.info(f"Token: {result['token']}")
                    except:
                        pass
                        
                elif field_num == 9 and wire_type == 0:  # sequence_no (uint64)
                    result['sequence_no'] = value
                    self.logger.info(f"Sequence: {value}")
                    
                elif field_num == 10 and wire_type == 0:  # snapshot (bool)
                    result['snapshot'] = bool(value)
                    
                elif field_num == 11 and wire_type == 2:  # ticker (string)
                    try:
                        result['symbol'] = value.decode('utf-8', errors='ignore')
                        self.logger.info(f"Symbol: {result['symbol']}")
                    except:
                        pass
                        
                elif field_num == 12 and wire_type == 2:  # symdetail
                    self.logger.info(f"Found SymDetail")
                    
                if pos >= len(data):
                    break
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing MarketFeed: {e}")
            return None
    
    def _parse_quote_message(self, data: bytes) -> Optional[Dict]:
        """
        Parse Quote message - THIS CONTAINS THE REAL LTP!
        
        Quote {
            Int64Value ltp = 1;        // THE REAL LTP IS HERE!
            UInt32Value ltt = 2;
            UInt32Value ltq = 3;
            UInt64Value vtt = 4;
            UInt64Value vtt_diff = 5;
            UInt64Value oi = 6;
            Int64Value ltpc = 7;
        }
        """
        try:
            pos = 0
            result = {}
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 2:  # Int64Value ltp - THE REAL LTP!
                    ltp_value = self._parse_int64_wrapper(value)
                    if ltp_value is not None:
                        # Standard Fyers conversion: paise to rupees
                        result['ltp'] = ltp_value / 100.0
                        self.logger.info(f"🎯 REAL LTP FOUND: {result['ltp']} (raw: {ltp_value})")
                        
                elif field_num == 2 and wire_type == 2:  # UInt32Value ltt
                    ltt_value = self._parse_uint32_wrapper(value)
                    if ltt_value:
                        result['ltt'] = ltt_value
                        
                elif field_num == 3 and wire_type == 2:  # UInt32Value ltq
                    ltq_value = self._parse_uint32_wrapper(value)
                    if ltq_value:
                        result['ltq'] = ltq_value
                        
                elif field_num == 4 and wire_type == 2:  # UInt64Value vtt
                    vtt_value = self._parse_uint64_wrapper(value)
                    if vtt_value:
                        result['volume'] = vtt_value
                        
                elif field_num == 6 and wire_type == 2:  # UInt64Value oi
                    oi_value = self._parse_uint64_wrapper(value)
                    if oi_value:
                        result['oi'] = oi_value
                        
                elif field_num == 7 and wire_type == 2:  # Int64Value ltpc
                    ltpc_value = self._parse_int64_wrapper(value)
                    if ltpc_value is not None:
                        result['ltp_change'] = ltpc_value / 100.0
                        
                if pos >= len(data):
                    break
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing Quote: {e}")
            return None
    
    def _parse_depth_message(self, data: bytes) -> Optional[Dict]:
        """
        Parse Depth message to extract LTP from bid/ask prices
        
        Depth {
            UInt64Value tbq = 1;         // Total Buy Quantity  
            UInt64Value tsq = 2;         // Total Sell Quantity
            repeated MarketLevel asks = 3;
            repeated MarketLevel bids = 4;
        }
        
        MarketLevel {
            Int64Value price = 1;        // Price (potential LTP!)
            UInt32Value qty = 2;
            UInt32Value nord = 3;
            UInt32Value num = 4;
        }
        """
        try:
            pos = 0
            result = {}
            best_bid = None
            best_ask = None
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 2:  # UInt64Value tbq
                    tbq_value = self._parse_uint64_wrapper(value)
                    if tbq_value:
                        result['total_buy_qty'] = tbq_value
                        
                elif field_num == 2 and wire_type == 2:  # UInt64Value tsq
                    tsq_value = self._parse_uint64_wrapper(value)
                    if tsq_value:
                        result['total_sell_qty'] = tsq_value
                        
                elif field_num == 3 and wire_type == 2:  # repeated MarketLevel asks
                    ask_price = self._parse_market_level(value)
                    if ask_price and not best_ask:
                        best_ask = ask_price
                        self.logger.info(f"Best Ask: {ask_price}")
                        
                elif field_num == 4 and wire_type == 2:  # repeated MarketLevel bids
                    bid_price = self._parse_market_level(value)
                    if bid_price and not best_bid:
                        best_bid = bid_price
                        self.logger.info(f"Best Bid: {bid_price}")
                        
                if pos >= len(data):
                    break
            
            # Estimate LTP from bid/ask if no Quote available
            if best_bid and best_ask:
                estimated_ltp = (best_bid + best_ask) / 2.0
                result['ltp'] = estimated_ltp
                result['bid'] = best_bid
                result['ask'] = best_ask
                self.logger.info(f"🎯 ESTIMATED LTP from bid/ask: {estimated_ltp} (bid: {best_bid}, ask: {best_ask})")
            elif best_bid:
                result['ltp'] = best_bid
                result['bid'] = best_bid
                self.logger.info(f"🎯 ESTIMATED LTP from bid: {best_bid}")
            elif best_ask:
                result['ltp'] = best_ask
                result['ask'] = best_ask
                self.logger.info(f"🎯 ESTIMATED LTP from ask: {best_ask}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error parsing Depth: {e}")
            return None
    
    def _parse_market_level(self, data: bytes) -> Optional[float]:
        """
        Parse MarketLevel to extract price
        
        MarketLevel {
            Int64Value price = 1;
            UInt32Value qty = 2;
            UInt32Value nord = 3;
            UInt32Value num = 4;
        }
        """
        try:
            pos = 0
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 2:  # Int64Value price
                    price_value = self._parse_int64_wrapper(value)
                    if price_value is not None:
                        price = price_value / 100.0  # Convert paise to rupees
                        return price
                        
                if pos >= len(data):
                    break
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error parsing MarketLevel: {e}")
            return None
    
    def _parse_int64_wrapper(self, data: bytes) -> Optional[int]:
        """Parse google.protobuf.Int64Value wrapper"""
        return self._parse_protobuf_wrapper(data)
    
    def _parse_uint32_wrapper(self, data: bytes) -> Optional[int]:
        """Parse google.protobuf.UInt32Value wrapper"""
        return self._parse_protobuf_wrapper(data)
    
    def _parse_uint64_wrapper(self, data: bytes) -> Optional[int]:
        """Parse google.protobuf.UInt64Value wrapper"""
        return self._parse_protobuf_wrapper(data)
    
    def _parse_protobuf_wrapper(self, data: bytes) -> Optional[int]:
        """
        Parse google.protobuf wrapper messages like Int64Value, UInt32Value, etc.
        
        Wrapper format:
        - Field 1 (wire type 0): The actual value
        """
        try:
            pos = 0
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 0 and isinstance(value, int):
                    return value
                    
                if pos >= len(data):
                    break
                    
            return None
            
        except Exception as e:
            self.logger.debug(f"Error parsing protobuf wrapper: {e}")
            return None
    
    def _parse_field(self, data: bytes, pos: int) -> tuple:
        """Parse a single protobuf field"""
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
        """Decode protobuf varint"""
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
    
    def _parse_daily_quote_message(self, data: bytes) -> Optional[Dict]:
        """
        Parse DailyQuote message to extract OHLC data
        
        DailyQuote {
            Int64Value do = 1;    // Day Open
            Int64Value dh = 2;    // Day High  
            Int64Value dl = 3;    // Day Low
            Int64Value dc = 4;    // Day Close
            UInt64Value dhoi = 5; // Day OI Low
            UInt64Value dloi = 6; // Day OI High
        }
        """
        try:
            pos = 0
            result = {}
            
            while pos < len(data):
                field_data, pos = self._parse_field(data, pos)
                if not field_data:
                    break
                    
                field_num = field_data['field_number']
                value = field_data.get('value')
                wire_type = field_data.get('wire_type')
                
                if field_num == 1 and wire_type == 2:  # Day Open (Int64Value)
                    open_value = self._parse_int64_wrapper(value)
                    if open_value is not None:
                        result['open'] = open_value / 100.0  # Convert paise to rupees
                        self.logger.info(f"Day Open: {result['open']}")
                        
                elif field_num == 2 and wire_type == 2:  # Day High (Int64Value)
                    high_value = self._parse_int64_wrapper(value)
                    if high_value is not None:
                        result['high'] = high_value / 100.0
                        self.logger.info(f"Day High: {result['high']}")
                        
                elif field_num == 3 and wire_type == 2:  # Day Low (Int64Value)
                    low_value = self._parse_int64_wrapper(value)
                    if low_value is not None:
                        result['low'] = low_value / 100.0
                        self.logger.info(f"Day Low: {result['low']}")
                        
                elif field_num == 4 and wire_type == 2:  # Day Close (Int64Value)
                    close_value = self._parse_int64_wrapper(value)
                    if close_value is not None:
                        result['close'] = close_value / 100.0
                        self.logger.info(f"Day Close: {result['close']}")
                        
                elif field_num == 5 and wire_type == 2:  # Day OI Low (UInt64Value)
                    dhoi_value = self._parse_uint64_wrapper(value)
                    if dhoi_value is not None:
                        result['oi_day_low'] = dhoi_value
                        
                elif field_num == 6 and wire_type == 2:  # Day OI High (UInt64Value)
                    dloi_value = self._parse_uint64_wrapper(value)
                    if dloi_value is not None:
                        result['oi_day_high'] = dloi_value
                
                if pos >= len(data):
                    break
            
            if result:
                self.logger.info(f"✅ DailyQuote OHLC extracted: O={result.get('open')}, H={result.get('high')}, L={result.get('low')}, C={result.get('close')}")
            
            return result if result else None
            
        except Exception as e:
            self.logger.error(f"Error parsing DailyQuote: {e}")
            return None
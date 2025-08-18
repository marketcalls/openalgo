"""
Fyers Data Mapping
Maps Fyers HSM data to OpenAlgo format for compatibility
"""

import time
from typing import Dict, Any, Optional
from datetime import datetime

class FyersDataMapper:
    """
    Maps Fyers HSM WebSocket data to OpenAlgo format
    """
    
    def __init__(self):
        """Initialize the data mapper"""
        pass
    
    def map_to_openalgo_ltp(self, fyers_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Map Fyers data to OpenAlgo LTP format
        
        Args:
            fyers_data: Raw data from Fyers HSM WebSocket
            
        Returns:
            OpenAlgo LTP format dict or None if mapping fails
        """
        try:
            if not fyers_data or "ltp" not in fyers_data:
                return None
            
            # Get the symbol - prefer original_symbol if available
            symbol = fyers_data.get("original_symbol") or fyers_data.get("symbol", "")
            
            # Parse exchange and symbol from original_symbol (e.g., "BSE:TCS-A")
            if ":" in symbol:
                exchange, symbol_name = symbol.split(":", 1)
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            # Apply multiplier and precision to LTP
            ltp = fyers_data.get("ltp", 0)
            multiplier = fyers_data.get("multiplier", 100)  # Default 100
            precision = fyers_data.get("precision", 2)     # Default 2
            
            # Convert to actual price
            if multiplier > 0:
                ltp = ltp / multiplier
            
            # Round to precision
            ltp = round(ltp, precision)
            
            # Map to OpenAlgo LTP format
            openalgo_data = {
                "symbol": symbol,
                "exchange": exchange,
                "token": fyers_data.get("exchange_token", ""),
                "ltp": ltp,
                "timestamp": int(time.time()),
                "data_type": "LTP"
            }
            
            return openalgo_data
            
        except Exception as e:
            print(f"Error mapping LTP data: {e}")
            return None
    
    def map_to_openalgo_quote(self, fyers_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Map Fyers data to OpenAlgo Quote format
        
        Args:
            fyers_data: Raw data from Fyers HSM WebSocket
            
        Returns:
            OpenAlgo Quote format dict or None if mapping fails
        """
        try:
            if not fyers_data:
                return None
            
            # Get the symbol
            symbol = fyers_data.get("original_symbol") or fyers_data.get("symbol", "")
            
            # Parse exchange and symbol
            if ":" in symbol:
                exchange, symbol_name = symbol.split(":", 1)
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            # Use the same price conversion logic as LTP
            # Check if this is an index based on symbol or type
            is_index = (
                "-INDEX" in symbol or 
                "-INDEX" in symbol.upper() or
                "INDEX" in symbol.upper() or
                fyers_data.get("type") == "if"  # Index feed type in HSM
            )
            
            def convert_price(value):
                if not value:
                    return 0.0
                    
                if is_index:
                    # Indices: Keep raw values, just round to 2 decimal places
                    return round(float(value), 2)
                else:
                    # Stocks, Futures, Options: Convert paise to rupees (divide by 100)
                    # For NSE, NFO, MCX, BSE, BFO instruments
                    return round(float(value) / 100.0, 2)
            
            # Map to OpenAlgo Quote format
            openalgo_data = {
                "symbol": symbol,
                "exchange": exchange,
                "token": fyers_data.get("exchange_token", ""),
                "ltp": convert_price(fyers_data.get("ltp", 0)),
                "open": convert_price(fyers_data.get("open_price", 0)),
                "high": convert_price(fyers_data.get("high_price", 0)),
                "low": convert_price(fyers_data.get("low_price", 0)),
                "close": convert_price(fyers_data.get("prev_close_price", 0)),
                "bid_price": convert_price(fyers_data.get("bid_price", 0)),
                "ask_price": convert_price(fyers_data.get("ask_price", 0)),
                "bid_size": fyers_data.get("bid_size", 0),
                "ask_size": fyers_data.get("ask_size", 0),
                "volume": fyers_data.get("vol_traded_today", 0),
                "oi": fyers_data.get("OI", 0),
                "upper_circuit": convert_price(fyers_data.get("upper_ckt", 0)),
                "lower_circuit": convert_price(fyers_data.get("lower_ckt", 0)),
                "last_traded_time": fyers_data.get("last_traded_time", 0),
                "exchange_time": fyers_data.get("exch_feed_time", 0),
                "timestamp": int(time.time()),
                "data_type": "Quote"
            }
            
            return openalgo_data
            
        except Exception as e:
            print(f"Error mapping Quote data: {e}")
            return None
    
    def map_to_openalgo_depth(self, fyers_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Map Fyers depth data to OpenAlgo Depth format
        
        Args:
            fyers_data: Raw depth data from Fyers HSM WebSocket
            
        Returns:
            OpenAlgo Depth format dict or None if mapping fails
        """
        try:
            if not fyers_data or fyers_data.get("type") != "dp":
                return None
            
            # Get the symbol
            symbol = fyers_data.get("original_symbol") or fyers_data.get("symbol", "")
            
            # Parse exchange and symbol
            if ":" in symbol:
                exchange, symbol_name = symbol.split(":", 1)
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            # Apply multiplier and precision
            multiplier = fyers_data.get("multiplier", 100)
            precision = fyers_data.get("precision", 2)
            
            def convert_price(value):
                if value and multiplier > 0:
                    return round(value / multiplier, precision)
                return 0.0
            
            # Build bid and ask arrays
            bids = []
            asks = []
            
            for i in range(1, 6):  # 5 levels
                bid_price = convert_price(fyers_data.get(f"bid_price{i}", 0))
                bid_size = fyers_data.get(f"bid_size{i}", 0)
                bid_orders = fyers_data.get(f"bid_order{i}", 0)
                
                ask_price = convert_price(fyers_data.get(f"ask_price{i}", 0))
                ask_size = fyers_data.get(f"ask_size{i}", 0)
                ask_orders = fyers_data.get(f"ask_order{i}", 0)
                
                if bid_price > 0:
                    bids.append({
                        "price": bid_price,
                        "size": bid_size,
                        "orders": bid_orders
                    })
                
                if ask_price > 0:
                    asks.append({
                        "price": ask_price,
                        "size": ask_size,
                        "orders": ask_orders
                    })
            
            # Map to OpenAlgo Depth format
            openalgo_data = {
                "symbol": symbol,
                "exchange": exchange,
                "token": fyers_data.get("exchange_token", ""),
                "bids": bids,
                "asks": asks,
                "timestamp": int(time.time()),
                "data_type": "Depth"
            }
            
            return openalgo_data
            
        except Exception as e:
            print(f"Error mapping Depth data: {e}")
            return None
    
    def map_fyers_data(self, fyers_data: Dict[str, Any], requested_type: str = "Quote") -> Optional[Dict[str, Any]]:
        """
        Map Fyers data to appropriate OpenAlgo format based on requested type
        
        Args:
            fyers_data: Raw data from Fyers HSM WebSocket
            requested_type: Requested data type ("LTP", "Quote", or "Depth")
            
        Returns:
            Mapped OpenAlgo data or None if mapping fails
        """
        if not fyers_data:
            return None
        
        # Determine data type from Fyers data if not specified
        fyers_type = fyers_data.get("type", "sf")
        
        if requested_type == "LTP":
            return self.map_to_openalgo_ltp(fyers_data)
        elif requested_type == "Quote":
            return self.map_to_openalgo_quote(fyers_data)
        elif requested_type == "Depth" and fyers_type == "dp":
            return self.map_to_openalgo_depth(fyers_data)
        elif fyers_type == "sf":
            # Default to Quote for symbol feed
            return self.map_to_openalgo_quote(fyers_data)
        elif fyers_type == "if":
            # Index data - treat as Quote
            return self.map_to_openalgo_quote(fyers_data)
        elif fyers_type == "dp":
            # Depth data
            return self.map_to_openalgo_depth(fyers_data)
        
        return None
    
    def extract_symbol_info(self, symbol: str) -> Dict[str, str]:
        """
        Extract exchange and symbol from OpenAlgo format
        
        Args:
            symbol: Symbol in format "EXCHANGE:SYMBOL" or just "SYMBOL"
            
        Returns:
            Dict with exchange and symbol keys
        """
        if ":" in symbol:
            exchange, symbol_name = symbol.split(":", 1)
        else:
            # Default to NSE if no exchange specified
            exchange = "NSE"
            symbol_name = symbol
        
        return {
            "exchange": exchange,
            "symbol": symbol_name,
            "full_symbol": f"{exchange}:{symbol_name}"
        }
    
    def is_valid_data(self, data: Dict[str, Any]) -> bool:
        """
        Check if the data contains valid market data
        
        Args:
            data: Market data dictionary
            
        Returns:
            True if data is valid, False otherwise
        """
        if not data:
            return False
        
        # Check for required fields
        required_fields = ["symbol", "exchange"]
        for field in required_fields:
            if field not in data or not data[field]:
                return False
        
        # Check for at least one price field
        price_fields = ["ltp", "open", "high", "low", "close", "bid_price", "ask_price"]
        has_price = any(field in data and data[field] is not None for field in price_fields)
        
        return has_price
    
    def format_timestamp(self, timestamp: int) -> str:
        """
        Format timestamp to readable string
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            Formatted timestamp string
        """
        try:
            if timestamp > 0:
                return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            return ""
        except:
            return ""
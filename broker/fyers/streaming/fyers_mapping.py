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
                # Clean symbol name for consistent display (remove suffixes like -EQ, -A, etc.)
                if "-" in symbol_name:
                    symbol_name = symbol_name.split("-")[0]
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            print(f"LTP Mapping: original_symbol={symbol}, parsed exchange={exchange}, symbol_name={symbol_name}")
            
            # Apply multiplier and precision to LTP
            ltp = fyers_data.get("ltp", 0)
            multiplier = fyers_data.get("multiplier", 100)  # Default 100
            precision = fyers_data.get("precision", 2)     # Default 2
            
            # Apply segment-specific conversion
            segment_divisor = 1
            if exchange in ["BSE", "MCX", "NSE", "NFO"]:
                segment_divisor = 100  # These exchanges send prices in paisa/paise format
            
            # Convert to actual price
            if multiplier > 0:
                ltp = ltp / multiplier / segment_divisor
            
            # Round to precision
            ltp = round(ltp, precision)
            
            # Map to OpenAlgo LTP format
            openalgo_data = {
                "symbol": f"{exchange}:{symbol_name}",
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
                # Clean symbol name for consistent display (remove suffixes like -EQ, -A, etc.)
                if "-" in symbol_name:
                    symbol_name = symbol_name.split("-")[0]
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            
            # Get multiplier and precision from data
            multiplier = fyers_data.get("multiplier", 100)
            precision = fyers_data.get("precision", 2)
            
            # Check if this is an index based on symbol or type
            is_index = (
                "-INDEX" in symbol or 
                "-INDEX" in symbol.upper() or
                "INDEX" in symbol.upper() or
                fyers_data.get("type") == "if"  # Index feed type in HSM
            )
            
            # Apply segment-specific conversion
            segment_divisor = 1
            if not is_index and exchange in ["BSE", "MCX", "NSE", "NFO"]:
                segment_divisor = 100  # These exchanges send prices in paisa/paise format
            
            def convert_price(value):
                if not value or multiplier <= 0:
                    return 0.0
                # Apply multiplier and segment conversion
                return round(value / multiplier / segment_divisor, precision)
            
            # Map to OpenAlgo Quote format
            openalgo_data = {
                "symbol": f"{exchange}:{symbol_name}",
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
                "average_price": convert_price(fyers_data.get("avg_trade_price", 0)),
                "total_buy_quantity": fyers_data.get("tot_buy_qty", 0),
                "total_sell_quantity": fyers_data.get("tot_sell_qty", 0),
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
                # Clean symbol name for consistent display (remove suffixes like -EQ, -A, etc.)
                if "-" in symbol_name:
                    symbol_name = symbol_name.split("-")[0]
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            # Apply multiplier and precision
            multiplier = fyers_data.get("multiplier", 100)
            precision = fyers_data.get("precision", 2)
            
            # Apply segment-specific conversion based on exchange
            segment_divisor = 1
            if exchange == "BSE":
                segment_divisor = 100  # BSE prices are in paisa
            elif exchange == "MCX":
                segment_divisor = 100  # MCX also needs division by 100
            elif exchange == "NSE":
                segment_divisor = 100  # NSE prices also in paisa format
            elif exchange == "NFO":
                segment_divisor = 100  # NFO prices also in paisa format
            
            def convert_price(value):
                if value and multiplier > 0:
                    # First apply the multiplier conversion, then segment-specific conversion
                    price = value / multiplier / segment_divisor
                    return round(price, precision)
                return 0.0
            
            # Build buy and sell arrays (matching other brokers' format)
            buy_levels = []
            sell_levels = []
            
            for i in range(1, 6):  # 5 levels
                bid_price = convert_price(fyers_data.get(f"bid_price{i}", 0))
                bid_size = fyers_data.get(f"bid_size{i}", 0)
                bid_orders = fyers_data.get(f"bid_order{i}", 0)
                
                ask_price = convert_price(fyers_data.get(f"ask_price{i}", 0))
                ask_size = fyers_data.get(f"ask_size{i}", 0)
                ask_orders = fyers_data.get(f"ask_order{i}", 0)
                
                if bid_price > 0:
                    buy_levels.append({
                        "price": bid_price,
                        "quantity": bid_size,  # Changed from "size" to "quantity"
                        "orders": bid_orders
                    })
                
                if ask_price > 0:
                    sell_levels.append({
                        "price": ask_price,
                        "quantity": ask_size,  # Changed from "size" to "quantity"
                        "orders": ask_orders
                    })
            
            # Calculate LTP (average of best bid and ask if available)
            ltp = 0
            if buy_levels and sell_levels:
                ltp = (buy_levels[0]["price"] + sell_levels[0]["price"]) / 2
            
            # Map to OpenAlgo Depth format (matching other brokers)
            openalgo_data = {
                "symbol": f"{exchange}:{symbol_name}",
                "exchange": exchange,
                "token": fyers_data.get("exchange_token", ""),
                "ltp": ltp,
                "depth": {
                    "buy": buy_levels,
                    "sell": sell_levels
                },
                "timestamp": int(time.time()),
                "data_type": "Depth"
            }
            
            return openalgo_data
            
        except Exception as e:
            print(f"Error mapping Depth data: {e}")
            return None
    
    def map_index_to_synthetic_depth(self, fyers_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Map Fyers index data to synthetic OpenAlgo Depth format
        Since indices don't have real depth, create synthetic depth from quote data
        
        Args:
            fyers_data: Raw index data from Fyers HSM WebSocket
            
        Returns:
            OpenAlgo Depth format dict or None if mapping fails
        """
        try:
            if not fyers_data or fyers_data.get("type") != "if":
                return None
            
            # Get the symbol
            symbol = fyers_data.get("original_symbol") or fyers_data.get("symbol", "")
            
            # Parse exchange and symbol
            if ":" in symbol:
                exchange, symbol_name = symbol.split(":", 1)
                # Clean symbol name for consistent display (remove suffixes like -EQ, -A, etc.)
                if "-" in symbol_name:
                    symbol_name = symbol_name.split("-")[0]
            else:
                exchange = fyers_data.get("exchange", "")
                symbol_name = symbol
            
            print(f"Index Depth Mapping: original_symbol={symbol}, parsed exchange={exchange}, symbol_name={symbol_name}")
            
            # Get LTP from index data and apply proper conversion
            raw_ltp = fyers_data.get("ltp", 0)
            if not raw_ltp:
                return None
            
            # Apply multiplier and precision conversion for index data
            multiplier = fyers_data.get("multiplier", 100)
            precision = fyers_data.get("precision", 2)
            
            # For indices, apply proper price conversion
            if multiplier > 0:
                ltp = round(raw_ltp / multiplier, precision)
            else:
                ltp = raw_ltp
            
            # Create synthetic depth levels around LTP
            # For indices, we'll create small bid-ask spreads around the LTP
            spread_bps = 5  # 0.05% spread on each side
            spread = ltp * spread_bps / 10000
            
            # Create 5 synthetic bid levels (decreasing prices)
            buy_levels = []
            for i in range(5):
                level_spread = spread * (i + 1)
                buy_price = round(ltp - level_spread, 2)
                buy_levels.append({
                    "price": buy_price,
                    "quantity": 1000 * (6 - i),  # Higher quantity at better prices
                    "orders": 1
                })
            
            # Create 5 synthetic ask levels (increasing prices)
            sell_levels = []
            for i in range(5):
                level_spread = spread * (i + 1)
                ask_price = round(ltp + level_spread, 2)
                sell_levels.append({
                    "price": ask_price,
                    "quantity": 1000 * (6 - i),  # Higher quantity at better prices
                    "orders": 1
                })
            
            # Map to OpenAlgo Depth format
            openalgo_data = {
                "symbol": f"{exchange}:{symbol_name}",
                "exchange": exchange,
                "token": fyers_data.get("exchange_token", ""),
                "ltp": ltp,
                "depth": {
                    "buy": buy_levels,
                    "sell": sell_levels
                },
                "timestamp": int(time.time()),
                "data_type": "Depth"
            }
            
            return openalgo_data
            
        except Exception as e:
            print(f"Error mapping Index to synthetic Depth data: {e}")
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
        elif requested_type == "Depth" and fyers_type == "if":
            # Index depth request - create synthetic depth from index data
            return self.map_index_to_synthetic_depth(fyers_data)
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
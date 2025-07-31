import sys
import os
import time
import json
import threading
import websocket
from typing import List, Dict, Any, Callable, Optional
from queue import Queue

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class SimpleFeed:
    """A simplified wrapper around the OpenAlgo WebSocket client for Market Depth data"""
    
    def __init__(self, host: str = "localhost", port: int = 8765, api_key: Optional[str] = None):
        """
        Initialize the SimpleFeed
        
        Args:
            host: WebSocket server host
            port: WebSocket server port
            api_key: API key for authentication (loads from .env if not provided)
        """
        self.ws_url = f"ws://{host}:{port}"
        self.api_key = api_key
        
        if not self.api_key:
            # Try to load from .env file
            try:
                from dotenv import load_dotenv
                load_dotenv()
                self.api_key = os.getenv("API_KEY")
            except ImportError:
                print("python-dotenv not installed. Please provide API key explicitly.")
                
        self.ws = None
        self.connected = False
        self.authenticated = False
        self.pending_auth = False
        self.message_queue = Queue()
        
        # Storage for market data
        self.market_data = {}
        self.lock = threading.Lock()
        
        # Callbacks
        self.on_data_callback = None
        
    def connect(self) -> bool:
        """Connect to the WebSocket server"""
        try:
            def on_message(ws, message):
                self.message_queue.put(message)
                self._process_message(message)
                
            def on_error(ws, error):
                print(f"WebSocket error: {error}")
                
            def on_open(ws):
                print(f"Connected to {self.ws_url}")
                self.connected = True
                
            def on_close(ws, close_status_code, close_reason):
                print(f"Disconnected from {self.ws_url}")
                self.connected = False
                self.authenticated = False
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=on_message,
                on_error=on_error,
                on_open=on_open,
                on_close=on_close
            )
            
            # Start WebSocket connection in a separate thread
            self.ws_thread = threading.Thread(target=self.ws.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            
            # Wait for connection to establish
            timeout = 5
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if not self.connected:
                print("Failed to connect to the WebSocket server")
                return False
                
            # Now authenticate
            return self._authenticate()
        except Exception as e:
            print(f"Error connecting to WebSocket: {e}")
            return False
            
    def disconnect(self) -> None:
        """Disconnect from the WebSocket server"""
        if self.ws:
            self.ws.close()
            # Wait for websocket to close
            timeout = 2
            start_time = time.time()
            while self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            self.ws = None
            
    def _authenticate(self) -> bool:
        """Authenticate with the WebSocket server"""
        if not self.connected or not self.api_key:
            print("Cannot authenticate: not connected or no API key")
            return False
            
        auth_msg = {
            "action": "authenticate",
            "api_key": self.api_key
        }
        
        print(f"Authenticating with API key: {self.api_key[:8]}...{self.api_key[-8:]}")
        self.ws.send(json.dumps(auth_msg))
        self.pending_auth = True
        
        # Wait for authentication response synchronously
        timeout = 5
        start_time = time.time()
        while not self.authenticated and time.time() - start_time < timeout:
            # Process any messages in the queue
            try:
                if not self.message_queue.empty():
                    message = self.message_queue.get(block=False)
                    self._process_message(message)
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"Error processing message: {e}")
                time.sleep(0.1)
                
        if self.authenticated:
            print("Authentication successful!")
            return True
        else:
            print("Authentication failed or timed out")
            return False
        
    def _process_message(self, message_str: str) -> None:
        """Process incoming WebSocket messages"""
        try:
            message = json.loads(message_str)
            
            # Handle authentication response
            if message.get("type") == "auth":
                if message.get("status") == "success":
                    print(f"Authentication response: {message}")
                    self.authenticated = True
                    self.pending_auth = False
                else:
                    print(f"Authentication failed: {message}")
                    self.pending_auth = False
                return
                
            # Handle subscription response
            if message.get("type") == "subscribe":
                print(f"Subscription response: {message}")
                return
                
            # Handle market data for market depth
            if message.get("type") == "market_data":
                exchange = message.get("exchange")
                symbol = message.get("symbol")
                if exchange and symbol:
                    symbol_key = f"{exchange}:{symbol}"
                    mode = message.get("mode")
                    market_data = message.get("data", {})
                    
                    if mode == 3 and "depth" in market_data:  # Depth mode
                        # Extract depth data
                        depth_data = {
                            'ltp': market_data.get("ltp", 0),
                            'open': market_data.get("open", 0),
                            'high': market_data.get("high", 0),
                            'low': market_data.get("low", 0),
                            'close': market_data.get("close", 0),
                            'depth': market_data.get("depth", {"buy": [], "sell": []})
                        }
                        
                        # Store the depth data in our cache
                        with self.lock:
                            self.market_data[symbol_key] = depth_data
                        
                        # Print when depth data is received
                        self._print_depth(symbol_key, depth_data)
                        
                        # Invoke callback if set
                        if self.on_data_callback:
                            self.on_data_callback(message)
        except json.JSONDecodeError:
            print(f"Invalid JSON message: {message_str}")
        except Exception as e:
            print(f"Error handling message: {e}")
    
    def _print_depth(self, symbol_key: str, depth_data: Dict[str, Any]) -> None:
        """Print market depth data in formatted form"""
        buy_depth = depth_data.get('depth', {}).get('buy', [])
        sell_depth = depth_data.get('depth', {}).get('sell', [])
        
        print(f"\nDepth {symbol_key} - LTP: {depth_data.get('ltp')}")
        
        # Print all buy depth levels
        print("\nBUY DEPTH:")
        print("-" * 40)
        print(f"{'Level':<6} {'Price':<10} {'Quantity':<10} {'Orders':<10}")
        print("-" * 40)
        
        if buy_depth:
            for i, level in enumerate(buy_depth):
                print(f"{i+1:<6} {level.get('price', 'N/A'):<10} {level.get('quantity', 'N/A'):<10} {level.get('orders', 'N/A'):<10}")
        else:
            print("No buy depth data available")
            
        # Print all sell depth levels
        print("\nSELL DEPTH:")
        print("-" * 40)
        print(f"{'Level':<6} {'Price':<10} {'Quantity':<10} {'Orders':<10}")
        print("-" * 40)
        
        if sell_depth:
            for i, level in enumerate(sell_depth):
                print(f"{i+1:<6} {level.get('price', 'N/A'):<10} {level.get('quantity', 'N/A'):<10} {level.get('orders', 'N/A'):<10}")
        else:
            print("No sell depth data available")
            
        print("-" * 40)
            
    def subscribe_depth(self, instruments: List[Dict[str, str]], on_data_received: Optional[Callable] = None) -> bool:
        """
        Subscribe to Market Depth updates for instruments
        
        Args:
            instruments: List of instrument dictionaries with keys exchange, symbol/exchange_token
            on_data_received: Callback function for data updates
        """
        if not self.connected:
            print("Not connected to WebSocket server")
            return False
            
        if not self.authenticated:
            print("Not authenticated with WebSocket server")
            return False
            
        self.on_data_callback = on_data_received
        
        for instrument in instruments:
            exchange = instrument.get("exchange")
            symbol = instrument.get("symbol")
            exchange_token = instrument.get("exchange_token")
            
            # If only exchange_token is provided, we need to map it to a symbol
            if not symbol and exchange_token:
                symbol = exchange_token
                
            if not exchange or not symbol:
                print(f"Invalid instrument: {instrument}")
                continue
                
            subscription_msg = {
                "action": "subscribe",
                "symbol": symbol,
                "exchange": exchange,
                "mode": 3,  # 3 for Depth
                "depth": 5  # Default depth level
            }
            
            print(f"Subscribing to {exchange}:{symbol} Market Depth")
            self.ws.send(json.dumps(subscription_msg))
            
            # Small delay to ensure the message is processed separately
            time.sleep(0.1)
            
        return True
        
    def unsubscribe_depth(self, instruments: List[Dict[str, str]]) -> bool:
        """Unsubscribe from Market Depth updates for instruments"""
        if not self.connected or not self.authenticated:
            print("Not connected or authenticated")
            return False
            
        for instrument in instruments:
            exchange = instrument.get("exchange")
            symbol = instrument.get("symbol")
            exchange_token = instrument.get("exchange_token")
            
            # If only exchange_token is provided, we need to map it to a symbol
            if not symbol and exchange_token:
                symbol = exchange_token
                
            if not exchange or not symbol:
                print(f"Invalid instrument: {instrument}")
                continue
                
            unsubscription_msg = {
                "action": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "mode": 3  # 3 for Depth
            }
            
            print(f"Unsubscribing from {exchange}:{symbol}")
            self.ws.send(json.dumps(unsubscription_msg))
            
        return True
        
    def get_depth(self, symbol: str = None, exchange: str = None) -> Dict[str, Any]:
        """
        Get the latest market depth data for a symbol or all symbols
        
        Args:
            symbol: Symbol to get data for, or None for all symbols
            exchange: Exchange to get data for
            
        Returns:
            Dict: Market depth data
        """
        depth_data = {}
        with self.lock:
            if symbol and exchange:
                symbol_key = f"{exchange}:{symbol}"
                return self.market_data.get(symbol_key, {})
            else:
                # Return all market data
                depth_data = self.market_data.copy()
        return depth_data
    
    def print_current_depth(self, symbol: str = None, exchange: str = None) -> None:
        """
        Print the current market depth for a symbol or all symbols
        
        Args:
            symbol: Symbol to print depth for, or None for all symbols
            exchange: Exchange to print depth for
        """
        if symbol and exchange:
            symbol_key = f"{exchange}:{symbol}"
            depth_data = self.get_depth(symbol, exchange)
            if depth_data:
                self._print_depth(symbol_key, depth_data)
            else:
                print(f"No depth data available for {symbol_key}")
        else:
            # Print all symbols
            depth_data = self.get_depth()
            if depth_data:
                for symbol_key, data in depth_data.items():
                    self._print_depth(symbol_key, data)
            else:
                print("No depth data available")

# Example usage
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    print("OpenAlgo Simple Market Depth Feed Test")
    
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("API_KEY not found in .env file")
        api_key = input("Enter your API key: ")
    
    # Create the feed
    feed = SimpleFeed(api_key=api_key)
    
    # Connect to the WebSocket server (includes authentication)
    print("Connecting to WebSocket server...")
    if not feed.connect():
        print("Failed to connect or authenticate with WebSocket server")
        sys.exit(1)
    
    # Define a callback function for data updates
    def on_data_received(meta):
        # Using the print_current_depth inside the callback is redundant as 
        # we already print the depth when a message is received
        pass
    
    # List of instruments to subscribe to
    instruments_list = [
        {"exchange": "MCX", "symbol": "GOLDPETAL30MAY25FUT"}
    ]
    
    print("\n===== TESTING DEPTH SUBSCRIPTION =====")
    feed.subscribe_depth(instruments_list, on_data_received=on_data_received)
    
    # Live data can also be continuously polled using this method
    print("\nReceiving market data for 10 seconds...")
    for i in range(10):
        # Sleep to allow depth data to be received and printed by the callback
        time.sleep(1)
        
        # Optionally, we can poll and print the current depth again
        # but this is redundant as we already print the depth when a message is received
        # feed.print_current_depth()
    
    print("Unsubscribing...")
    feed.unsubscribe_depth(instruments_list)
    time.sleep(1)
    feed.disconnect()
    print("Test completed")

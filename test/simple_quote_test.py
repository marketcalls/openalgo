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
    """A simplified wrapper around the OpenAlgo WebSocket client for Quote data"""
    
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
                
            # Handle market data for quotes
            if message.get("type") == "market_data":
                exchange = message.get("exchange")
                symbol = message.get("symbol")
                if exchange and symbol:
                    symbol_key = f"{exchange}:{symbol}"
                    mode = message.get("mode")
                    market_data = message.get("data", {})
                    
                    if mode == 2:  # Quote mode
                        # Extract quote data
                        quote_data = {
                            'ltp': market_data.get("ltp", 0),
                            'open': market_data.get("open", 0),
                            'high': market_data.get("high", 0),
                            'low': market_data.get("low", 0),
                            'close': market_data.get("close", 0),
                            'volume': market_data.get("volume", 0),
                            'timestamp': market_data.get("timestamp", 0)
                        }
                        
                        # Store the quote data in our cache
                        with self.lock:
                            self.market_data[symbol_key] = quote_data
                        
                        # Print when quote data is received
                        print(f"Quote {symbol_key}: Open: {quote_data['open']} | High: {quote_data['high']} | "
                              f"Low: {quote_data['low']} | Close: {quote_data['close']} | "
                              f"LTP: {quote_data['ltp']}")
                        
                        # Invoke callback if set
                        if self.on_data_callback:
                            self.on_data_callback(message)
        except json.JSONDecodeError:
            print(f"Invalid JSON message: {message_str}")
        except Exception as e:
            print(f"Error handling message: {e}")
            
    def subscribe_quote(self, instruments: List[Dict[str, str]], on_data_received: Optional[Callable] = None) -> bool:
        """
        Subscribe to Quote updates for instruments
        
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
                "mode": 2,  # 2 for Quote
                "depth": 5  # Default depth level
            }
            
            print(f"Subscribing to {exchange}:{symbol} Quote")
            self.ws.send(json.dumps(subscription_msg))
            
            # Small delay to ensure the message is processed separately
            time.sleep(0.1)
            
        return True
        
    def unsubscribe_quote(self, instruments: List[Dict[str, str]]) -> bool:
        """Unsubscribe from Quote updates for instruments"""
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
                "mode": 2  # 2 for Quote
            }
            
            print(f"Unsubscribing from {exchange}:{symbol}")
            self.ws.send(json.dumps(unsubscription_msg))
            
        return True
        
    def get_quotes(self) -> Dict[str, Any]:
        """Get the latest quote data for all symbols"""
        quote_data = {}
        with self.lock:
            # Return all the quote data
            quote_data = self.market_data.copy()
        return quote_data

# Example usage
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    print("OpenAlgo Simple Quote Feed Test")
    
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
        print("Data received from callback!")
    
    # You can fetch exchange_token from instruments.csv file
    instruments_list = [
        {"exchange": "NSE", "symbol": "TCS"},
        {"exchange": "NSE", "symbol": "SBIN"}
    ]
    
    print("\n===== TESTING QUOTE SUBSCRIPTION =====")
    feed.subscribe_quote(instruments_list, on_data_received=on_data_received)
    
    # Live data can also be continuously polled using this method
    print("\nReceiving market data for 10 seconds...")
    for i in range(10):
        quotes = feed.get_quotes()
        if quotes:
            print(f"\nPoll {i+1} - Current Quotes:")
            for symbol, quote in quotes.items():
                print(f"{symbol}: Open: {quote.get('open')} | High: {quote.get('high')} | "
                      f"Low: {quote.get('low')} | Close: {quote.get('close')} | "
                      f"LTP: {quote.get('ltp')} | Volume: {quote.get('volume')} ")
        time.sleep(1)
    
    print("Unsubscribing...")
    feed.unsubscribe_quote(instruments_list)
    time.sleep(1)
    feed.disconnect()
    print("Test completed")

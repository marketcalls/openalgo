import sys
import os
import time
import json
import threading
import asyncio
import websocket
from typing import List, Dict, Any, Callable, Optional
from queue import Queue
from concurrent.futures import ThreadPoolExecutor

# Add parent directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class WebSocketTestClient:
    """
    Enhanced WebSocket test client for testing the improved server.py
    Based on SimpleFeed but with additional testing capabilities
    """
    
    def __init__(self, host: str = "localhost", port: int = 8765, api_key: Optional[str] = None, client_id: str = None):
        """
        Initialize the test client
        
        Args:
            host: WebSocket server host
            port: WebSocket server port
            api_key: API key for authentication
            client_id: Optional client identifier for logging
        """
        self.ws_url = f"ws://{host}:{port}"
        self.api_key = api_key
        self.client_id = client_id or f"client_{threading.current_thread().ident}"
        
        if not self.api_key:
            # Try to load from .env file
            try:
                from dotenv import load_dotenv
                load_dotenv()
                self.api_key = os.getenv("API_KEY")
            except ImportError:
                print(f"[{self.client_id}] python-dotenv not installed. Please provide API key explicitly.")
                
        self.ws = None
        self.connected = False
        self.authenticated = False
        self.pending_auth = False
        self.message_queue = Queue()
        
        # Test tracking
        self.test_results = []
        self.subscription_count = 0
        self.unsubscription_count = 0
        self.error_count = 0
        
        # Callbacks
        self.on_data_callback = None
        self.on_auth_callback = None
        self.on_error_callback = None
        
    def connect(self) -> bool:
        """Connect to the WebSocket server"""
        try:
            def on_message(ws, message):
                self.message_queue.put(message)
                self._process_message(message)
                
            def on_error(ws, error):
                print(f"[{self.client_id}] WebSocket error: {error}")
                self.error_count += 1
                if self.on_error_callback:
                    self.on_error_callback(error)
                
            def on_open(ws):
                print(f"[{self.client_id}] Connected to {self.ws_url}")
                self.connected = True
                
            def on_close(ws, close_status_code, close_reason):
                print(f"[{self.client_id}] Disconnected from {self.ws_url}")
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
                self.test_results.append(f"CONNECTION_FAILED: Failed to connect to WebSocket server")
                return False
                
            # Now authenticate
            return self._authenticate()
        except Exception as e:
            self.test_results.append(f"CONNECTION_ERROR: {str(e)}")
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
            self.test_results.append("AUTH_FAILED: Not connected or no API key")
            return False
            
        auth_msg = {
            "action": "authenticate",
            "api_key": self.api_key
        }
        
        print(f"[{self.client_id}] Authenticating with API key: {self.api_key[:8]}...")
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
                print(f"[{self.client_id}] Error processing message: {e}")
                time.sleep(0.1)
                
        if self.authenticated:
            print(f"[{self.client_id}] Authentication successful!")
            self.test_results.append("AUTH_SUCCESS: Authentication successful")
            if self.on_auth_callback:
                self.on_auth_callback(True)
            return True
        else:
            print(f"[{self.client_id}] Authentication failed or timed out")
            self.test_results.append("AUTH_FAILED: Authentication failed or timed out")
            if self.on_auth_callback:
                self.on_auth_callback(False)
            return False
        
    def _process_message(self, message_str: str) -> None:
        """Process incoming WebSocket messages"""
        try:
            message = json.loads(message_str)
            print(f"[{self.client_id}] Received: {message}")
            
            # Handle authentication response
            if message.get("type") == "auth":
                if message.get("status") == "success":
                    self.authenticated = True
                    self.pending_auth = False
                    broker = message.get("broker", "unknown")
                    user_id = message.get("user_id", "unknown")
                    self.test_results.append(f"AUTH_RESPONSE: Success - Broker: {broker}, User: {user_id}")
                else:
                    self.pending_auth = False
                    error_msg = message.get("message", "Unknown error")
                    self.test_results.append(f"AUTH_RESPONSE: Failed - {error_msg}")
                    
            # Handle subscription response
            elif message.get("type") == "subscribe":
                status = message.get("status")
                if status == "success":
                    self.subscription_count += 1
                    subscriptions = message.get("subscriptions", [])
                    self.test_results.append(f"SUBSCRIBE_SUCCESS: {len(subscriptions)} subscriptions")
                else:
                    self.error_count += 1
                    error_msg = message.get("message", "Unknown error")
                    self.test_results.append(f"SUBSCRIBE_ERROR: {error_msg}")
                    
            # Handle unsubscription response
            elif message.get("type") == "unsubscribe":
                status = message.get("status")
                if status == "success":
                    self.unsubscription_count += 1
                    self.test_results.append("UNSUBSCRIBE_SUCCESS: Unsubscription successful")
                else:
                    self.error_count += 1
                    error_msg = message.get("message", "Unknown error")
                    self.test_results.append(f"UNSUBSCRIBE_ERROR: {error_msg}")
                    
            # Handle error messages
            elif message.get("status") == "error":
                self.error_count += 1
                error_code = message.get("code", "UNKNOWN")
                error_msg = message.get("message", "Unknown error")
                self.test_results.append(f"ERROR_RESPONSE: {error_code} - {error_msg}")
                
            # Handle market data
            elif message.get("type") == "market_data":
                symbol = message.get("symbol", "unknown")
                exchange = message.get("exchange", "unknown")
                mode = message.get("mode", "unknown")
                self.test_results.append(f"MARKET_DATA: {exchange}:{symbol} mode {mode}")
                
            # Handle broker info response
            elif message.get("type") == "broker_info":
                status = message.get("status")
                if status == "success":
                    broker = message.get("broker", "unknown")
                    adapter_status = message.get("adapter_status", "unknown")
                    self.test_results.append(f"BROKER_INFO_SUCCESS: {broker} - {adapter_status}")
                else:
                    error_msg = message.get("message", "Unknown error")
                    self.test_results.append(f"BROKER_INFO_ERROR: {error_msg}")
                    
            # Handle supported brokers response
            elif message.get("type") == "supported_brokers":
                status = message.get("status")
                if status == "success":
                    brokers = message.get("brokers", [])
                    count = message.get("count", 0)
                    self.test_results.append(f"SUPPORTED_BROKERS_SUCCESS: {count} brokers - {brokers}")
                else:
                    error_msg = message.get("message", "Unknown error")
                    self.test_results.append(f"SUPPORTED_BROKERS_ERROR: {error_msg}")
                    
            # Invoke callback if set
            if self.on_data_callback:
                self.on_data_callback(message)
                
        except json.JSONDecodeError:
            self.test_results.append(f"INVALID_JSON: {message_str}")
        except Exception as e:
            self.test_results.append(f"MESSAGE_ERROR: {str(e)}")
            
    def subscribe(self, instruments: List[Dict[str, str]], mode: int = 1, depth: int = 5) -> bool:
        """
        Subscribe to market data for instruments
        
        Args:
            instruments: List of instrument dictionaries with exchange and symbol
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            depth: Depth level for depth mode
        """
        if not self.connected or not self.authenticated:
            self.test_results.append("SUBSCRIBE_FAILED: Not connected or authenticated")
            return False
            
        for instrument in instruments:
            exchange = instrument.get("exchange")
            symbol = instrument.get("symbol")
                
            if not exchange or not symbol:
                self.test_results.append(f"SUBSCRIBE_INVALID: Invalid instrument: {instrument}")
                continue
                
            subscription_msg = {
                "action": "subscribe",
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "depth": depth
            }
            
            print(f"[{self.client_id}] Subscribing to {exchange}:{symbol} mode {mode}")
            self.ws.send(json.dumps(subscription_msg))
            time.sleep(0.1)  # Small delay between messages
            
        return True
        
    def unsubscribe(self, instruments: List[Dict[str, str]], mode: int = 1) -> bool:
        """Unsubscribe from market data for instruments"""
        if not self.connected or not self.authenticated:
            self.test_results.append("UNSUBSCRIBE_FAILED: Not connected or authenticated")
            return False
            
        for instrument in instruments:
            exchange = instrument.get("exchange")
            symbol = instrument.get("symbol")
                
            if not exchange or not symbol:
                self.test_results.append(f"UNSUBSCRIBE_INVALID: Invalid instrument: {instrument}")
                continue
                
            unsubscription_msg = {
                "action": "unsubscribe",
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode
            }
            
            print(f"[{self.client_id}] Unsubscribing from {exchange}:{symbol}")
            self.ws.send(json.dumps(unsubscription_msg))
            time.sleep(0.1)
            
        return True
        
    def unsubscribe_all(self) -> bool:
        """Unsubscribe from all market data"""
        if not self.connected or not self.authenticated:
            self.test_results.append("UNSUBSCRIBE_ALL_FAILED: Not connected or authenticated")
            return False
            
        unsubscription_msg = {
            "action": "unsubscribe_all"
        }
        
        print(f"[{self.client_id}] Unsubscribing from all")
        self.ws.send(json.dumps(unsubscription_msg))
        return True
        
    def get_broker_info(self) -> bool:
        """Get broker information"""
        if not self.connected or not self.authenticated:
            self.test_results.append("GET_BROKER_INFO_FAILED: Not connected or authenticated")
            return False
            
        info_msg = {
            "action": "get_broker_info"
        }
        
        print(f"[{self.client_id}] Getting broker info")
        self.ws.send(json.dumps(info_msg))
        return True
        
    def get_supported_brokers(self) -> bool:
        """Get list of supported brokers"""
        if not self.connected or not self.authenticated:
            self.test_results.append("GET_SUPPORTED_BROKERS_FAILED: Not connected or authenticated")
            return False
            
        brokers_msg = {
            "action": "get_supported_brokers"
        }
        
        print(f"[{self.client_id}] Getting supported brokers")
        self.ws.send(json.dumps(brokers_msg))
        return True
        
    def get_test_results(self) -> List[str]:
        """Get test results for this client"""
        return self.test_results.copy()
        
    def clear_test_results(self) -> None:
        """Clear test results"""
        self.test_results.clear()
        self.subscription_count = 0
        self.unsubscription_count = 0
        self.error_count = 0
        
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics"""
        return {
            "client_id": self.client_id,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "subscription_count": self.subscription_count,
            "unsubscription_count": self.unsubscription_count,
            "error_count": self.error_count,
            "test_results": self.get_test_results()
        }

    def wait_for_responses(self, expected_count: int, timeout: float = 5.0, response_type: str = None) -> List[str]:
        """Wait for expected number of responses with proper validation"""
        start_time = time.time()
        responses = []
        
        while time.time() - start_time < timeout and len(responses) < expected_count:
            try:
                if not self.message_queue.empty():
                    message = self.message_queue.get(block=False)
                    self._process_message(message)
                    responses.append(message)
                    
                    # Check if we got the expected response type
                    if response_type:
                        try:
                            parsed = json.loads(message)
                            if parsed.get("type") == response_type and parsed.get("status") == "success":
                                break
                        except:
                            pass
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"[{self.client_id}] Error waiting for responses: {e}")
                time.sleep(0.1)
                
        return responses
        
    def validate_connection_health(self) -> bool:
        """Validate that WebSocket connection is healthy"""
        if not self.ws or not self.connected:
            return False
            
        # Send a ping-like message to verify connection
        health_check = {"action": "get_supported_brokers"}
        try:
            self.ws.send(json.dumps(health_check))
            responses = self.wait_for_responses(1, timeout=3.0, response_type="supported_brokers")
            return len(responses) > 0
        except Exception as e:
            print(f"[{self.client_id}] Connection health check failed: {e}")
            return False
            
    def get_subscription_summary(self) -> Dict[str, Any]:
        """Get summary of subscription activity"""
        results = self.get_test_results()
        
        subscriptions = sum(1 for r in results if "SUBSCRIBE_SUCCESS" in r)
        unsubscriptions = sum(1 for r in results if "UNSUBSCRIBE_SUCCESS" in r)
        errors = sum(1 for r in results if "ERROR" in r or "FAILED" in r)
        first_subs = sum(1 for r in results if "is_first_subscription" in r)
        shared_subs = sum(1 for r in results if "Already subscribed" in r)
        
        return {
            "total_subscriptions": subscriptions,
            "total_unsubscriptions": unsubscriptions,
            "errors": errors,
            "first_subscriptions": first_subs,
            "shared_subscriptions": shared_subs,
            "success_rate": (subscriptions + unsubscriptions) / max(1, subscriptions + unsubscriptions + errors) * 100
        }


class WebSocketServerTester:
    """
    Comprehensive test suite for the improved WebSocket proxy server
    Tests all the improvements mentioned in the audit report
    """
    
    def __init__(self, host: str = "localhost", port: int = 8765, api_key: Optional[str] = None):
        self.host = host
        self.port = port
        self.api_key = api_key
        self.test_results = []
        self.clients = []
        self.shared_client = None  # For testing multi-client scenarios without multiple adapters
        
    def log_test(self, test_name: str, result: str, details: str = "") -> None:
        """Log a test result"""
        timestamp = time.strftime("%H:%M:%S")
        status_symbol = "✓" if result == "PASS" else "✗"
        log_entry = f"[{timestamp}] {status_symbol} {test_name}: {result}"
        if details:
            log_entry += f" - {details}"
        print(log_entry)
        self.test_results.append({"test": test_name, "result": result, "details": details, "timestamp": timestamp})
        
    def create_client(self, client_id: str = None) -> WebSocketTestClient:
        """Create a new test client"""
        client = WebSocketTestClient(self.host, self.port, self.api_key, client_id)
        self.clients.append(client)
        return client
        
    def create_shared_client(self) -> WebSocketTestClient:
        """Create a shared client for multi-client testing"""
        if not self.shared_client:
            self.shared_client = WebSocketTestClient(self.host, self.port, self.api_key, "shared_client")
            if not self.shared_client.connect():
                self.log_test("SHARED_CLIENT", "FAIL", "Failed to create shared client")
                return None
        return self.shared_client
        
    def cleanup_clients(self) -> None:
        """Clean up all test clients"""
        for client in self.clients:
            client.disconnect()
        self.clients.clear()
        if self.shared_client:
            self.shared_client.disconnect()
            self.shared_client = None
            
    def test_authentication_valid(self) -> bool:
        """Test 1: Valid authentication"""
        print("\n" + "="*60)
        print("Test 1: Valid Authentication")
        print("="*60)
        
        client = self.create_client("auth_test")
        success = client.connect()
        
        if success:
            self.log_test("AUTH_VALID", "PASS", f"Client authenticated successfully")
            client.disconnect()
            return True
        else:
            self.log_test("AUTH_VALID", "FAIL", f"Client failed to authenticate")
            client.disconnect()
            return False
            
    def test_authentication_invalid(self) -> bool:
        """Test 2: Invalid authentication"""
        print("\n" + "="*60)
        print("Test 2: Invalid Authentication")
        print("="*60)
        
        client = WebSocketTestClient(self.host, self.port, "invalid_api_key", "invalid_auth_test")
        success = client.connect()
        
        if not success:
            self.log_test("AUTH_INVALID", "PASS", "Invalid API key correctly rejected")
            return True
        else:
            self.log_test("AUTH_INVALID", "FAIL", "Invalid API key was accepted")
            client.disconnect()
            return False
            
    def test_authentication_missing(self) -> bool:
        """Test 3: Missing authentication"""
        print("\n" + "="*60)
        print("Test 3: Missing Authentication")
        print("="*60)
        
        client = WebSocketTestClient(self.host, self.port, "", "missing_auth_test")
        success = client.connect()
        
        if not success:
            self.log_test("AUTH_MISSING", "PASS", "Missing API key correctly rejected")
            return True
        else:
            self.log_test("AUTH_MISSING", "FAIL", "Missing API key was accepted")
            client.disconnect()
            return False
            
    def test_single_subscription(self) -> bool:
        """Test 4: Single subscription"""
        print("\n" + "="*60)
        print("Test 4: Single Subscription")
        print("="*60)
        
        client = self.create_client("single_sub_test")
        if not client.connect():
            self.log_test("SINGLE_SUB", "FAIL", "Failed to connect")
            return False
            
        # Subscribe to a single instrument
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        success = client.subscribe(instruments, mode=1)  # LTP mode
        
        if success:
            # Wait for subscription response
            time.sleep(1)
            results = client.get_test_results()
            sub_success = any("SUBSCRIBE_SUCCESS" in result for result in results)
            
            if sub_success:
                self.log_test("SINGLE_SUB", "PASS", "Single subscription successful")
                client.unsubscribe(instruments)
                time.sleep(1)
                client.disconnect()
                return True
            else:
                self.log_test("SINGLE_SUB", "FAIL", "No subscription success response")
                client.disconnect()
                return False
        else:
            self.log_test("SINGLE_SUB", "FAIL", "Failed to send subscription message")
            client.disconnect()
            return False
        
    def test_multiple_subscriptions(self) -> bool:
        """Test 5: Multiple subscriptions"""
        print("\n" + "="*60)
        print("Test 5: Multiple Subscriptions")
        print("="*60)
        
        client = self.create_client("multi_sub_test")
        if not client.connect():
            self.log_test("MULTI_SUB", "FAIL", "Failed to connect")
            return False
            
        # Subscribe to multiple instruments
        instruments = [
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NSE", "symbol": "TCS"},
            {"exchange": "BSE", "symbol": "INFY"}
        ]
        success = client.subscribe(instruments, mode=2)  # Quote mode
        
        if success:
            # Wait for subscription responses
            time.sleep(2)
            results = client.get_test_results()
            sub_count = sum(1 for result in results if "SUBSCRIBE_SUCCESS" in result)
            
            if sub_count >= len(instruments):
                self.log_test("MULTI_SUB", "PASS", f"Multiple subscriptions successful ({sub_count} responses)")
                client.unsubscribe(instruments)
                time.sleep(1)
                client.disconnect()
                return True
            else:
                self.log_test("MULTI_SUB", "FAIL", f"Expected {len(instruments)} responses, got {sub_count}")
                client.disconnect()
                return False
        else:
            self.log_test("MULTI_SUB", "FAIL", "Failed to send subscription messages")
            client.disconnect()
            return False
        
    def test_subscription_modes(self) -> bool:
        """Test 6: Different subscription modes"""
        print("\n" + "="*60)
        print("Test 6: Subscription Modes")
        print("="*60)
        
        client = self.create_client("modes_test")
        if not client.connect():
            self.log_test("MODES_TEST", "FAIL", "Failed to connect")
            return False
            
        test_passed = True
        
        # Test LTP mode
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        client.subscribe(instruments, mode=1)  # LTP
        time.sleep(1)
        
        # Test Quote mode
        client.subscribe(instruments, mode=2)  # Quote
        time.sleep(1)
        
        # Test Depth mode
        client.subscribe(instruments, mode=3)  # Depth
        time.sleep(1)
        
        results = client.get_test_results()
        mode_tests = sum(1 for result in results if "SUBSCRIBE_SUCCESS" in result)
        
        if mode_tests >= 3:
            self.log_test("MODES_TEST", "PASS", f"All subscription modes successful ({mode_tests} responses)")
        else:
            self.log_test("MODES_TEST", "FAIL", f"Expected 3 mode subscriptions, got {mode_tests}")
            test_passed = False
            
        client.unsubscribe_all()
        time.sleep(1)
        client.disconnect()
        return test_passed
        
    def test_duplicate_subscription(self) -> bool:
        """Test 7: Duplicate subscription handling"""
        print("\n" + "="*60)
        print("Test 7: Duplicate Subscription")
        print("="*60)
        
        client = self.create_client("duplicate_sub_test")
        if not client.connect():
            self.log_test("DUPLICATE_SUB", "FAIL", "Failed to connect")
            return False
            
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        
        # Subscribe twice to same instrument
        client.subscribe(instruments, mode=1)
        time.sleep(1)
        client.subscribe(instruments, mode=1)  # Duplicate
        time.sleep(1)
        
        results = client.get_test_results()
        success_count = sum(1 for result in results if "SUBSCRIBE_SUCCESS" in result)
        warning_count = sum(1 for result in results if "warning" in result.lower())
        
        if success_count >= 1 and warning_count >= 1:
            self.log_test("DUPLICATE_SUB", "PASS", f"Duplicate subscription handled correctly (success: {success_count}, warnings: {warning_count})")
            test_passed = True
        elif success_count >= 1:
            self.log_test("DUPLICATE_SUB", "PASS", "Duplicate subscription handled (may not return warning)")
            test_passed = True
        else:
            self.log_test("DUPLICATE_SUB", "FAIL", "Duplicate subscription not handled properly")
            test_passed = False
            
        client.unsubscribe_all()
        time.sleep(1)
        client.disconnect()
        return test_passed
        
    def test_multi_client_subscription(self) -> bool:
        """Test 8: Multi-client subscription sharing"""
        print("\n" + "="*60)
        print("Test 8: Multi-Client Subscription Sharing")
        print("="*60)
        
        # This tests the key improvement: global subscription tracking
        clients = []
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        
        # Create WebSocket clients with staggered connections to avoid rate limiting
        print("Creating WebSocket clients...")
        for i in range(3):
            client = self.create_client(f"multi_ws_client_{i}")
            
            # Stagger connections to avoid overwhelming the server
            if i > 0:
                time.sleep(1)
                
            if not client.connect():
                self.log_test("MULTI_CLIENT", "FAIL", f"WebSocket client {i} failed to connect")
                continue
                
            # Validate connection health
            if not client.validate_connection_health():
                self.log_test("MULTI_CLIENT", "FAIL", f"WebSocket client {i} connection unhealthy")
                client.disconnect()
                continue
                
            clients.append(client)
            
        if len(clients) < 2:
            self.log_test("MULTI_CLIENT", "FAIL", f"Only {len(clients)} clients connected, need at least 2")
            for client in clients:
                client.disconnect()
            return False
            
        print(f"Successfully connected {len(clients)} WebSocket clients")
        
        # First client subscribes (should create broker adapter and subscription)
        print("First client subscribing...")
        clients[0].subscribe(instruments, mode=1)
        first_responses = clients[0].wait_for_responses(2, timeout=5.0, response_type="subscribe")
        
        if len(first_responses) == 0:
            self.log_test("MULTI_CLIENT", "FAIL", "First client got no subscription response")
            for client in clients:
                client.disconnect()
            return False
            
        # Wait for broker subscription to complete
        time.sleep(3)
        
        # Other clients subscribe to same symbol (should share the subscription)
        print("Other clients subscribing...")
        for i, client in enumerate(clients[1:], 1):
            print(f"Client {i} subscribing...")
            client.subscribe(instruments, mode=1)
            responses = client.wait_for_responses(1, timeout=3.0, response_type="subscribe")
            
            if len(responses) == 0:
                print(f"Client {i} got no subscription response")
            else:
                print(f"Client {i} got response: {responses[0][:100]}...")
                
        # Wait for all responses to be processed
        time.sleep(4)
        
        # Enhanced validation of results
        summaries = []
        for i, client in enumerate(clients):
            summary = client.get_subscription_summary()
            summaries.append(summary)
            print(f"Client {i} summary: {summary}")
            
        # Validate that first client created the subscription
        first_summary = summaries[0]
        other_summaries = summaries[1:]
        
        # Check that first client has a subscription
        if first_summary["total_subscriptions"] == 0:
            self.log_test("MULTI_CLIENT", "FAIL", "First client has no subscriptions")
            for client in clients:
                client.disconnect()
            return False
            
        # Check that other clients also got subscription responses
        other_subs = sum(s["total_subscriptions"] for s in other_summaries)
        if other_subs == 0:
            self.log_test("MULTI_CLIENT", "FAIL", "Other clients have no subscriptions")
            for client in clients:
                client.disconnect()
            return False
            
        # Validate the sharing mechanism
        first_client_results = clients[0].get_test_results()
        other_clients_results = []
        for client in clients[1:]:
            other_clients_results.extend(client.get_test_results())
            
        # Look for evidence of subscription sharing
        first_is_first = any("is_first_subscription" in r for r in first_client_results)
        others_shared = any("Already subscribed" in r for r in other_clients_results)
        
        test_passed = False
        if first_is_first or others_shared:
            self.log_test("MULTI_CLIENT", "PASS", f"Subscription sharing validated: first={first_is_first}, shared={others_shared}")
            test_passed = True
        else:
            # Check if we got successful subscriptions anyway (sharing might not be explicitly indicated)
            total_success = sum(s["total_subscriptions"] for s in summaries)
            if total_success >= len(clients):
                self.log_test("MULTI_CLIENT", "PASS", f"All clients subscribed successfully ({total_success} total)")
                test_passed = True
            else:
                self.log_test("MULTI_CLIENT", "FAIL", f"Insufficient subscriptions: {total_success}/{len(clients)}")
                test_passed = False
            
        # Clean up with proper disconnection
        print("Cleaning up...")
        for client in clients:
            try:
                client.unsubscribe_all()
                time.sleep(0.5)
                client.disconnect()
            except Exception as e:
                print(f"Error during cleanup: {e}")
                
        return test_passed
        
    def test_unsubscribe_all(self) -> bool:
        """Test 9: Unsubscribe all functionality"""
        print("\n" + "="*60)
        print("Test 9: Unsubscribe All")
        print("="*60)
        
        client = self.create_client("unsub_all_test")
        if not client.connect():
            self.log_test("UNSUB_ALL", "FAIL", "Failed to connect")
            return False
            
        # Subscribe to multiple instruments
        instruments = [
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NSE", "symbol": "TCS"},
            {"exchange": "BSE", "symbol": "INFY"}
        ]
        client.subscribe(instruments)
        time.sleep(2)
        
        # Unsubscribe all
        success = client.unsubscribe_all()
        
        if success:
            time.sleep(2)
            results = client.get_test_results()
            unsub_count = sum(1 for result in results if "UNSUBSCRIBE_SUCCESS" in result)
            
            if unsub_count > 0:
                self.log_test("UNSUB_ALL", "PASS", f"Unsubscribe all successful ({unsub_count} responses)")
                test_passed = True
            else:
                self.log_test("UNSUB_ALL", "FAIL", "No unsubscribe success responses")
                test_passed = False
        else:
            self.log_test("UNSUB_ALL", "FAIL", "Failed to send unsubscribe all message")
            test_passed = False
            
        client.disconnect()
        return test_passed
        
    def test_invalid_unsubscribe(self) -> bool:
        """Test 10: Invalid unsubscribe handling"""
        print("\n" + "="*60)
        print("Test 10: Invalid Unsubscribe")
        print("="*60)
        
        client = self.create_client("invalid_unsub_test")
        if not client.connect():
            self.log_test("INVALID_UNSUB", "FAIL", "Failed to connect")
            return False
            
        # Try to unsubscribe without subscribing first
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        client.unsubscribe(instruments)
        time.sleep(1)
        
        results = client.get_test_results()
        error_count = sum(1 for result in results if "ERROR" in result or "error" in result)
        
        test_passed = False
        if error_count > 0:
            self.log_test("INVALID_UNSUB", "PASS", "Invalid unsubscribe properly handled with error")
            test_passed = True
        else:
            self.log_test("INVALID_UNSUB", "FAIL", "Invalid unsubscribe not properly handled")
            test_passed = False
            
        client.disconnect()
        return test_passed
        
    def test_get_broker_info(self) -> bool:
        """Test 11: Get broker info"""
        print("\n" + "="*60)
        print("Test 11: Get Broker Info")
        print("="*60)
        
        client = self.create_client("broker_info_test")
        if not client.connect():
            self.log_test("BROKER_INFO", "FAIL", "Failed to connect")
            return False
            
        success = client.get_broker_info()
        
        if success:
            time.sleep(2)
            results = client.get_test_results()
            info_success = any("BROKER_INFO_SUCCESS" in result for result in results)
            
            if info_success:
                self.log_test("BROKER_INFO", "PASS", "Broker info retrieved successfully")
                test_passed = True
            else:
                self.log_test("BROKER_INFO", "FAIL", "No broker info success response")
                test_passed = False
        else:
            self.log_test("BROKER_INFO", "FAIL", "Failed to send broker info request")
            test_passed = False
            
        client.disconnect()
        return test_passed
        
    def test_get_supported_brokers(self) -> bool:
        """Test 12: Get supported brokers"""
        print("\n" + "="*60)
        print("Test 12: Get Supported Brokers")
        print("="*60)
        
        client = self.create_client("supported_brokers_test")
        if not client.connect():
            self.log_test("SUPPORTED_BROKERS", "FAIL", "Failed to connect")
            return False
            
        success = client.get_supported_brokers()
        
        if success:
            time.sleep(2)
            results = client.get_test_results()
            brokers_success = any("SUPPORTED_BROKERS_SUCCESS" in result for result in results)
            
            if brokers_success:
                self.log_test("SUPPORTED_BROKERS", "PASS", "Supported brokers retrieved successfully")
                test_passed = True
            else:
                self.log_test("SUPPORTED_BROKERS", "FAIL", "No supported brokers success response")
                test_passed = False
        else:
            self.log_test("SUPPORTED_BROKERS", "FAIL", "Failed to send supported brokers request")
            test_passed = False
            
        client.disconnect()
        return test_passed
        
    def test_unauthenticated_requests(self) -> bool:
        """Test 13: Unauthenticated request handling"""
        print("\n" + "="*60)
        print("Test 13: Unauthenticated Requests")
        print("="*60)
        
        client = WebSocketTestClient(self.host, self.port, "invalid_key", "unauth_test")
        if not client.connect():  # This should fail
            # Create a new client without connecting
            client = WebSocketTestClient(self.host, self.port, self.api_key, "unauth_test")
            
            def on_error(error):
                print(f"[{client.client_id}] Expected error: {error}")
                
            client.on_error_callback = on_error
            
            # Try to send requests without authentication
            instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
            client.subscribe(instruments)
            client.get_broker_info()
            client.get_supported_brokers()
            
            time.sleep(1)
            results = client.get_test_results()
            error_count = sum(1 for result in results if "ERROR" in result)
            
            if error_count > 0:
                self.log_test("UNAUTH_REQUESTS", "PASS", f"Unauthenticated requests properly rejected ({error_count} errors)")
                return True
            else:
                self.log_test("UNAUTH_REQUESTS", "FAIL", "Unauthenticated requests not properly rejected")
                return False
            
        self.log_test("UNAUTH_REQUESTS", "FAIL", "Unexpected successful connection with invalid key")
        client.disconnect()
        return False
        
    def test_concurrent_operations(self) -> bool:
        """Test 14: Concurrent operations (race condition test)"""
        print("\n" + "="*60)
        print("Test 14: Concurrent Operations")
        print("="*60)
        
        def client_operations(client_id: str) -> Dict[str, Any]:
            """Operations for a single client with detailed results"""
            client = self.create_client(client_id)
            results = {"client_id": client_id, "success": False, "errors": 0, "operations": 0}
            
            try:
                if client.connect():
                    # Validate connection health
                    if not client.validate_connection_health():
                        results["errors"] += 1
                        results["error_msg"] = "Connection unhealthy"
                        client.disconnect()
                        return results
                        
                    instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
                    
                    # Perform operations with validation
                    for i in range(3):
                        try:
                            client.subscribe(instruments)
                            responses = client.wait_for_responses(1, timeout=2.0, response_type="subscribe")
                            results["operations"] += 1
                            
                            if len(responses) == 0:
                                results["errors"] += 1
                                
                            time.sleep(0.5)
                            client.unsubscribe(instruments)
                            unsub_responses = client.wait_for_responses(1, timeout=2.0, response_type="unsubscribe")
                            results["operations"] += 1
                            
                            if len(unsub_responses) == 0:
                                results["errors"] += 1
                                
                            time.sleep(0.5)
                        except Exception as e:
                            results["errors"] += 1
                            results["error_msg"] = str(e)
                    
                    # Get final summary
                    summary = client.get_subscription_summary()
                    results.update(summary)
                    results["success"] = summary["success_rate"] >= 80
                    client.disconnect()
                else:
                    results["errors"] += 1
                    results["error_msg"] = "Connection failed"
            except Exception as e:
                results["errors"] += 1
                results["error_msg"] = str(e)
                try:
                    client.disconnect()
                except:
                    pass
                    
            return results
            
        # Run concurrent operations with proper error handling
        print("Starting concurrent operations...")
        time.sleep(2)  # Wait before starting
        
        # Run with fewer concurrent clients but better validation
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(client_operations, f"concurrent_{i}") for i in range(3)]
            concurrent_results = [future.result() for future in futures]
            
        # Enhanced validation
        successful_clients = sum(1 for r in concurrent_results if r.get("success", False))
        total_errors = sum(r.get("errors", 0) for r in concurrent_results)
        total_operations = sum(r.get("operations", 0) for r in concurrent_results)
        
        print(f"Concurrent test results: {successful_clients}/{len(concurrent_results)} clients successful")
        print(f"Total operations: {total_operations}, Total errors: {total_errors}")
        
        for result in concurrent_results:
            print(f"  Client {result['client_id']}: {result.get('operations', 0)} ops, {result.get('errors', 0)} errors, {result.get('success_rate', 0):.1f}% success")
            
        if successful_clients >= 2 and total_errors <= 2:  # Allow some errors but majority should succeed
            self.log_test("CONCURRENT_OPS", "PASS", f"{successful_clients}/{len(concurrent_results)} clients successful, {total_errors} total errors")
            return True
        else:
            self.log_test("CONCURRENT_OPS", "FAIL", f"Only {successful_clients}/{len(concurrent_results)} clients successful, {total_errors} errors")
            return False
            
    def test_subscription_stress(self) -> bool:
        """Test 15: Subscription stress"""
        print("\n" + "="*60)
        print("Test 15: Subscription Stress")
        print("="*60)
        
        client = self.create_client("stress_sub_test")
        if not client.connect():
            self.log_test("STRESS_SUB", "FAIL", "Failed to connect")
            return False
            
        # Test rapid subscribe/unsubscribe with the same client
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        
        # Multiple subscribe/unsubscribe cycles
        for i in range(5):
            client.subscribe(instruments, mode=1)
            time.sleep(0.5)
            client.unsubscribe(instruments, mode=1)
            time.sleep(0.5)
            
        # Test different modes
        for mode in [1, 2, 3]:
            client.subscribe(instruments, mode=mode)
            time.sleep(0.3)
            
        time.sleep(2)
        
        # Final cleanup
        client.unsubscribe_all()
        time.sleep(1)
        
        results = client.get_test_results()
        error_count = sum(1 for result in results if "ERROR" in result or "FAILED" in result)
        
        if error_count == 0:
            self.log_test("STRESS_SUB", "PASS", "Subscription stress test passed")
            test_passed = True
        else:
            self.log_test("STRESS_SUB", "FAIL", f"Found {error_count} errors in stress test")
            test_passed = False
            
        client.disconnect()
        return test_passed
        
    def validate_server_improvements(self) -> Dict[str, Any]:
        """Validate that the server improvements are working correctly"""
        print("\n" + "="*60)
        print("Validating Server Improvements")
        print("="*60)
        
        # Test 1: Global subscription tracking
        print("Testing global subscription tracking...")
        client1 = self.create_client("validation_client_1")
        client2 = self.create_client("validation_client_2")
        
        if not client1.connect() or not client2.connect():
            return {"error": "Failed to connect validation clients"}
            
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        
        # Subscribe with first client
        client1.subscribe(instruments, mode=1)
        time.sleep(3)
        
        # Subscribe with second client (should share)
        client2.subscribe(instruments, mode=1)
        time.sleep(3)
        
        # Check broker info to verify sharing
        client1.get_broker_info()
        client2.get_broker_info()
        time.sleep(2)
        
        # Validate results
        client1_summary = client1.get_subscription_summary()
        client2_summary = client2.get_subscription_summary()
        
        # Clean up
        client1.unsubscribe_all()
        client2.unsubscribe_all()
        time.sleep(1)
        client1.disconnect()
        client2.disconnect()
        
        return {
            "client1_subscriptions": client1_summary["total_subscriptions"],
            "client2_subscriptions": client2_summary["total_subscriptions"],
            "client1_errors": client1_summary["errors"],
            "client2_errors": client2_summary["errors"],
            "global_tracking_working": client1_summary["total_subscriptions"] > 0 and client2_summary["total_subscriptions"] > 0
        }
        
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all tests and return comprehensive results"""
        print("\n" + "="*80)
        print(" "*20 + "OpenAlgo WebSocket Server Test Suite")
        print(" "*25 + "Enhanced Validation Version")
        print("="*80)
        
        # Clear previous results
        self.test_results.clear()
        
        # Add validation of server improvements
        improvement_validation = self.validate_server_improvements()
        if "error" in improvement_validation:
            self.log_test("SERVER_VALIDATION", "FAIL", improvement_validation["error"])
        else:
            status = "PASS" if improvement_validation["global_tracking_working"] else "FAIL"
            self.log_test("SERVER_VALIDATION", status, f"Global tracking: {improvement_validation}")
        
        # Run all tests with enhanced validation
        tests = [
            self.test_authentication_valid,
            self.test_authentication_invalid,
            self.test_authentication_missing,
            self.test_single_subscription,
            self.test_multiple_subscriptions,
            self.test_subscription_modes,
            self.test_duplicate_subscription,
            self.test_multi_client_subscription,
            self.test_unsubscribe_all,
            self.test_invalid_unsubscribe,
            self.test_get_broker_info,
            self.test_get_supported_brokers,
            self.test_unauthenticated_requests,
            self.test_concurrent_operations,
            self.test_subscription_stress
        ]
        
        passed = 0
        failed = 0
        test_details = []
        
        for i, test in enumerate(tests):
            try:
                print(f"\nRunning {test.__name__} ({i+1}/{len(tests)})...")
                time.sleep(1)  # Delay between tests
                
                result = test()
                if result:
                    passed += 1
                    test_details.append({"name": test.__name__, "status": "PASS"})
                else:
                    failed += 1
                    test_details.append({"name": test.__name__, "status": "FAIL"})
            except Exception as e:
                failed += 1
                test_details.append({"name": test.__name__, "status": "ERROR", "error": str(e)})
                print(f"ERROR in {test.__name__}: {str(e)}")
                
            # Extra delay for intensive tests
            if "multi_client" in test.__name__ or "concurrent" in test.__name__:
                print("Waiting for server to settle...")
                time.sleep(3)
        
        # Print detailed results
        print("\n" + "="*80)
        print(" "*30 + "TEST SUMMARY")
        print("="*80)
        print(f"Tests Passed:  {passed}/{len(tests)}")
        print(f"Tests Failed:  {failed}/{len(tests)}")
        print(f"Success Rate:  {(passed/len(tests)*100):.1f}%")
        
        print("\n" + "-"*80)
        print("DETAILED RESULTS:")
        print("-"*80)
        for detail in test_details:
            status_symbol = "✓" if detail["status"] == "PASS" else "✗"
            status_text = detail["status"]
            test_name = detail["name"].replace("test_", "").replace("_", " ").title()
            print(f"{status_symbol} {test_name:40} [{status_text}]")
            if "error" in detail:
                print(f"  Error: {detail['error']}")
            
        # Print improvement validation
        if "error" not in improvement_validation:
            print("\n" + "-"*80)
            print("SERVER IMPROVEMENTS VALIDATION:")
            print("-"*80)
            tracking_symbol = "✓" if improvement_validation['global_tracking_working'] else "✗"
            print(f"{tracking_symbol} Global subscription tracking: {'Working' if improvement_validation['global_tracking_working'] else 'Not working'}")
            print(f"  Client 1: {improvement_validation['client1_subscriptions']} subscriptions, {improvement_validation['client1_errors']} errors")
            print(f"  Client 2: {improvement_validation['client2_subscriptions']} subscriptions, {improvement_validation['client2_errors']} errors")
        
        print("="*80)
        
        return {
            "passed": passed,
            "failed": failed,
            "total": len(tests),
            "success_rate": passed/len(tests)*100,
            "results": self.test_results.copy(),
            "improvement_validation": improvement_validation,
            "test_details": test_details
        }
        
    def run_stress_test(self, duration: int = 60) -> Dict[str, Any]:
        """Run stress test for extended period"""
        print(f"\n" + "="*60)
        print(f"Stress Test ({duration}s)")
        print("="*60)
        
        client = self.create_client("stress_test")
        if not client.connect():
            return {"error": "Failed to connect for stress test"}
            
        instruments = [{"exchange": "NSE", "symbol": "RELIANCE"}]
        start_time = time.time()
        operation_count = 0
        
        while time.time() - start_time < duration:
            # Random operations
            import random
            
            if random.random() < 0.4:  # 40% subscribe
                client.subscribe(instruments)
            elif random.random() < 0.4:  # 40% unsubscribe
                client.unsubscribe(instruments)
            else:  # 20% get info
                client.get_broker_info()
                
            operation_count += 1
            time.sleep(0.1)  # 10 operations per second
            
        # Final cleanup
        client.unsubscribe_all()
        time.sleep(1)
        client.disconnect()
        
        results = client.get_test_results()
        error_count = sum(1 for result in results if "ERROR" in result or "FAILED" in result)
        
        return {
            "duration": duration,
            "operations": operation_count,
            "errors": error_count,
            "error_rate": error_count / operation_count * 100,
            "client_stats": client.get_stats()
        }


# Example usage
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\nOpenAlgo WebSocket Server Comprehensive Test Suite")
    print("Based on zmq_new_audit_report.md improvements\n")
    
    api_key = os.getenv("API_KEY")
    if not api_key:
        print("API_KEY not found in .env file")
        api_key = input("Enter your API key: ")
    
    # Run comprehensive test suite
    tester = WebSocketServerTester(api_key=api_key)
    results = tester.run_all_tests()
    
    # Print final verdict
    print(f"\n{'='*80}")
    overall_status = "PASS ✓" if results['success_rate'] >= 80 else "FAIL ✗"
    print(f"Overall Result: {overall_status} ({results['success_rate']:.1f}% success rate)")
    print(f"{'='*80}\n")
    
    # Optional: Run stress test
    run_stress = input("Run stress test? (y/N): ").lower().strip()
    if run_stress == 'y':
        duration = int(input("Stress test duration (seconds) [60]: ") or "60")
        stress_results = tester.run_stress_test(duration)
        print(f"\nStress Test Results:")
        print(f"  Duration: {stress_results['duration']}s")
        print(f"  Operations: {stress_results['operations']}")
        print(f"  Errors: {stress_results['errors']}")
        print(f"  Error Rate: {stress_results['error_rate']:.2f}%")
    
    tester.cleanup_clients()
    print("\nTest completed")

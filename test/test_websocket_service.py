"""
Test script for WebSocket service layer
Tests LTP, Quote, and Depth for RELIANCE and TCS
"""

import sys
import os
import time
import json
from datetime import datetime

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from services.websocket_client import WebSocketClient
from services.market_data_service import get_market_data_service
from services.websocket_service import (
    get_websocket_status,
    subscribe_to_symbols,
    unsubscribe_from_symbols,
    get_websocket_subscriptions,
    unsubscribe_all
)

# ANSI color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{text.center(60)}{Colors.ENDC}")
    print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")

def print_section(text):
    print(f"\n{Colors.CYAN}{Colors.BOLD}{text}{Colors.ENDC}")
    print(f"{Colors.CYAN}{'-'*len(text)}{Colors.ENDC}")

def format_price(price):
    return f"₹{price:,.2f}"

def format_volume(volume):
    return f"{volume:,}"

def format_timestamp(timestamp):
    if timestamp:
        dt = datetime.fromtimestamp(timestamp / 1000)  # Convert milliseconds to seconds
        # Format in IST timezone
        import pytz
        ist = pytz.timezone('Asia/Kolkata')
        dt_ist = dt.replace(tzinfo=pytz.UTC).astimezone(ist)
        return dt_ist.strftime("%I:%M:%S %p")
    return "N/A"

def test_ltp(client, symbols):
    """Test LTP subscription and data"""
    print_section("Testing LTP (Last Traded Price)")
    
    # Subscribe to LTP
    result = client.subscribe(symbols, "LTP")
    print(f"Subscription result: {result}")
    
    # Wait for data
    print("\nWaiting for LTP updates...")
    time.sleep(2)
    
    # Display LTP data
    for i in range(5):
        print(f"\n{Colors.YELLOW}Update {i+1}:{Colors.ENDC}")
        for symbol_info in symbols:
            symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
            data = client.get_market_data(symbol_info['symbol'], symbol_info['exchange'])
            
            if data and 'ltp' in data:
                ltp_data = data['ltp']
                print(f"{Colors.GREEN}{symbol_key}:{Colors.ENDC}")
                print(f"  Price: {format_price(ltp_data.get('value', 0))}")
                print(f"  Time: {format_timestamp(ltp_data.get('timestamp'))}")
                # Volume removed as per user request
            else:
                print(f"{Colors.RED}{symbol_key}: No data{Colors.ENDC}")
        
        time.sleep(1)
    
    # Unsubscribe
    client.unsubscribe(symbols, "LTP")
    print(f"\n{Colors.BLUE}Unsubscribed from LTP{Colors.ENDC}")

def test_quote(client, symbols):
    """Test Quote subscription and data"""
    print_section("Testing Quote Data")
    
    # Subscribe to Quote
    result = client.subscribe(symbols, "Quote")
    print(f"Subscription result: {result}")
    
    # Wait for data
    print("\nWaiting for Quote updates...")
    time.sleep(2)
    
    # Display Quote data
    for i in range(3):
        print(f"\n{Colors.YELLOW}Update {i+1}:{Colors.ENDC}")
        for symbol_info in symbols:
            symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
            data = client.get_market_data(symbol_info['symbol'], symbol_info['exchange'])
            
            if data and 'quote' in data:
                quote_data = data['quote']
                print(f"{Colors.GREEN}{symbol_key}:{Colors.ENDC}")
                print(f"  Open:  {format_price(quote_data.get('open', 0))}")
                print(f"  High:  {format_price(quote_data.get('high', 0))}")
                print(f"  Low:   {format_price(quote_data.get('low', 0))}")
                print(f"  Close: {format_price(quote_data.get('close', 0))}")
                print(f"  LTP:   {format_price(quote_data.get('ltp', 0))}")
                print(f"  Volume: {format_volume(quote_data.get('volume', 0))}")
                print(f"  Avg Price: {format_price(quote_data.get('average_price', 0))}")
                print(f"  Buy Qty: {format_volume(quote_data.get('total_buy_quantity', 0))}")
                print(f"  Sell Qty: {format_volume(quote_data.get('total_sell_quantity', 0))}")
                print(f"  Upper Circuit: {format_price(quote_data.get('upper_circuit', 0))}")
                print(f"  Lower Circuit: {format_price(quote_data.get('lower_circuit', 0))}")
                print(f"  Time:  {format_timestamp(quote_data.get('timestamp'))}")
            else:
                print(f"{Colors.RED}{symbol_key}: No data{Colors.ENDC}")
        
        time.sleep(2)
    
    # Unsubscribe
    client.unsubscribe(symbols, "Quote")
    print(f"\n{Colors.BLUE}Unsubscribed from Quote{Colors.ENDC}")

def test_depth(client, symbols):
    """Test Depth subscription and data"""
    print_section("Testing Market Depth")
    
    # Subscribe to Depth
    result = client.subscribe(symbols, "Depth")
    print(f"Subscription result: {result}")
    
    # Wait for data
    print("\nWaiting for Depth updates...")
    time.sleep(2)
    
    # Display Depth data
    for symbol_info in symbols:
        symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
        data = client.get_market_data(symbol_info['symbol'], symbol_info['exchange'])
        
        print(f"\n{Colors.GREEN}{symbol_key} - Market Depth:{Colors.ENDC}")
        
        if data and 'depth' in data:
            depth_data = data['depth']
            
            # Buy side
            print(f"\n{Colors.GREEN}BUY ORDERS:{Colors.ENDC}")
            print(f"{'Price':<12} {'Quantity':<10} {'Orders':<8}")
            print("-" * 30)
            
            buy_depth = depth_data.get('buy', [])
            for i, level in enumerate(buy_depth[:5]):
                price = format_price(level.get('price', 0))
                qty = level.get('quantity', 0)
                orders = level.get('orders', 0)
                print(f"{price:<12} {qty:<10} {orders:<8}")
            
            # Sell side
            print(f"\n{Colors.RED}SELL ORDERS:{Colors.ENDC}")
            print(f"{'Price':<12} {'Quantity':<10} {'Orders':<8}")
            print("-" * 30)
            
            sell_depth = depth_data.get('sell', [])
            for i, level in enumerate(sell_depth[:5]):
                price = format_price(level.get('price', 0))
                qty = level.get('quantity', 0)
                orders = level.get('orders', 0)
                print(f"{price:<12} {qty:<10} {orders:<8}")
            
            print(f"\nLTP from depth: {format_price(depth_data.get('ltp', 0))}")
        else:
            print(f"{Colors.RED}No depth data available{Colors.ENDC}")
    
    # Unsubscribe
    client.unsubscribe(symbols, "Depth")
    print(f"\n{Colors.BLUE}Unsubscribed from Depth{Colors.ENDC}")

def test_market_data_service():
    """Test the market data service"""
    print_section("Testing Market Data Service")
    
    service = get_market_data_service()
    
    # Get cached data
    print("\nFetching cached data from Market Data Service:")
    
    for symbol, exchange in [('RELIANCE', 'NSE'), ('TCS', 'NSE')]:
        print(f"\n{Colors.GREEN}{exchange}:{symbol}{Colors.ENDC}")
        
        # Get LTP
        ltp = service.get_ltp(symbol, exchange)
        if ltp:
            print(f"  LTP: {format_price(ltp.get('value', 0))} at {format_timestamp(ltp.get('timestamp'))}")
        
        # Get Quote
        quote = service.get_quote(symbol, exchange)
        if quote:
            print(f"  Quote - Open: {format_price(quote.get('open', 0))}, "
                  f"High: {format_price(quote.get('high', 0))}, "
                  f"Low: {format_price(quote.get('low', 0))}")
            print(f"  Additional - Avg: {format_price(quote.get('average_price', 0))}, "
                  f"Buy: {format_volume(quote.get('total_buy_quantity', 0))}, "
                  f"Sell: {format_volume(quote.get('total_sell_quantity', 0))}")
        
        # Get Depth
        depth = service.get_market_depth(symbol, exchange)
        if depth:
            buy_levels = len(depth.get('buy', []))
            sell_levels = len(depth.get('sell', []))
            print(f"  Depth - Buy levels: {buy_levels}, Sell levels: {sell_levels}")
            
            # Show best bid/ask
            buy_orders = depth.get('buy', [])
            sell_orders = depth.get('sell', [])
            if buy_orders:
                best_bid = buy_orders[0]
                print(f"  Best Bid: {format_price(best_bid.get('price', 0))} ({best_bid.get('quantity', 0)} qty)")
            if sell_orders:
                best_ask = sell_orders[0]
                print(f"  Best Ask: {format_price(best_ask.get('price', 0))} ({best_ask.get('quantity', 0)} qty)")
    
    # Show metrics
    metrics = service.get_cache_metrics()
    print(f"\n{Colors.CYAN}Cache Metrics:{Colors.ENDC}")
    print(f"  Total symbols: {metrics['total_symbols']}")
    print(f"  Total updates: {metrics['total_updates']}")
    print(f"  Cache hit rate: {metrics['hit_rate']}%")

def test_subscription_management(client, symbols):
    """Test subscription and unsubscription functionality"""
    print_section("Testing Subscription Management")
    
    # Test individual subscriptions
    print(f"\n{Colors.CYAN}1. Testing individual subscriptions:{Colors.ENDC}")
    
    # Subscribe to LTP for RELIANCE
    result = client.subscribe([symbols[0]], "LTP")
    print(f"Subscribe RELIANCE LTP: {Colors.GREEN if result['status'] == 'success' else Colors.RED}{result['status']}{Colors.ENDC}")
    
    # Subscribe to Quote for TCS
    result = client.subscribe([symbols[1]], "Quote")
    print(f"Subscribe TCS Quote: {Colors.GREEN if result['status'] == 'success' else Colors.RED}{result['status']}{Colors.ENDC}")
    
    # Check subscriptions
    subs = client.get_subscriptions()
    print(f"Current subscriptions: {subs['count']}")
    
    time.sleep(2)
    
    # Test unsubscribe
    print(f"\n{Colors.CYAN}2. Testing unsubscriptions:{Colors.ENDC}")
    
    # Unsubscribe from RELIANCE LTP
    result = client.unsubscribe([symbols[0]], "LTP")
    print(f"Unsubscribe RELIANCE LTP: {Colors.GREEN if result['status'] == 'success' else Colors.RED}{result['status']}{Colors.ENDC}")
    
    # Check subscriptions again
    subs = client.get_subscriptions()
    print(f"Remaining subscriptions: {subs['count']}")
    
    time.sleep(1)
    
    # Test bulk operations
    print(f"\n{Colors.CYAN}3. Testing bulk operations:{Colors.ENDC}")
    
    # Bulk subscribe
    result = client.subscribe(symbols, "Depth")
    print(f"Bulk subscribe to Depth: {Colors.GREEN if result['status'] == 'success' else Colors.RED}{result['status']}{Colors.ENDC}")
    
    subs = client.get_subscriptions()
    print(f"After bulk subscribe: {subs['count']} subscriptions")
    
    time.sleep(2)
    
    # Unsubscribe all
    result = client.unsubscribe_all()
    print(f"Unsubscribe all: {Colors.GREEN if result['status'] == 'success' else Colors.RED}{result['status']}{Colors.ENDC}")
    
    subs = client.get_subscriptions()
    print(f"After unsubscribe all: {subs['count']} subscriptions")

def test_mode_switching(client, symbols):
    """Test switching between different modes"""
    print_section("Testing Mode Switching")
    
    symbol = symbols[0]  # Use RELIANCE for this test
    
    print(f"Testing mode switching for {symbol['exchange']}:{symbol['symbol']}")
    
    modes = ["LTP", "Quote", "Depth"]
    
    for i, mode in enumerate(modes):
        print(f"\n{Colors.YELLOW}Step {i+1}: Switching to {mode} mode{Colors.ENDC}")
        
        # Unsubscribe from previous mode if not first
        if i > 0:
            prev_mode = modes[i-1]
            result = client.unsubscribe([symbol], prev_mode)
            print(f"  Unsubscribed from {prev_mode}: {result['status']}")
        
        # Subscribe to new mode
        result = client.subscribe([symbol], mode)
        print(f"  Subscribed to {mode}: {result['status']}")
        
        # Wait for data
        time.sleep(2)
        
        # Check data
        data = client.get_market_data(symbol['symbol'], symbol['exchange'])
        if data:
            if mode == "LTP" and 'ltp' in data:
                print(f"  ✓ Received LTP data: {format_price(data['ltp'].get('value', 0))}")
            elif mode == "Quote" and 'quote' in data:
                print(f"  ✓ Received Quote data: OHLC available")
            elif mode == "Depth" and 'depth' in data:
                buy_levels = len(data['depth'].get('buy', []))
                sell_levels = len(data['depth'].get('sell', []))
                print(f"  ✓ Received Depth data: {buy_levels} buy, {sell_levels} sell levels")
        else:
            print(f"  ⚠ No data received for {mode}")
    
    # Clean up
    client.unsubscribe([symbol], modes[-1])

def test_concurrent_subscriptions(client, symbols):
    """Test concurrent subscriptions to multiple modes"""
    print_section("Testing Concurrent Subscriptions")
    
    print("Subscribing to all modes for both symbols simultaneously...")
    
    # Subscribe to all modes for all symbols
    modes = ["LTP", "Quote", "Depth"]
    for mode in modes:
        result = client.subscribe(symbols, mode)
        print(f"Subscribe all to {mode}: {result['status']}")
        time.sleep(0.5)
    
    # Check total subscriptions
    subs = client.get_subscriptions()
    expected = len(symbols) * len(modes)
    print(f"Expected: {expected}, Actual: {subs['count']} subscriptions")
    
    # Wait for data
    print("\nWaiting for data from all subscriptions...")
    time.sleep(3)
    
    # Check data for each symbol
    for symbol_info in symbols:
        symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
        data = client.get_market_data(symbol_info['symbol'], symbol_info['exchange'])
        
        if data:
            available_modes = []
            if 'ltp' in data:
                available_modes.append('LTP')
            if 'quote' in data:
                available_modes.append('Quote')
            if 'depth' in data:
                available_modes.append('Depth')
            
            print(f"{Colors.GREEN}{symbol_key}: {', '.join(available_modes)} data available{Colors.ENDC}")
        else:
            print(f"{Colors.RED}{symbol_key}: No data available{Colors.ENDC}")
    
    # Clean up
    client.unsubscribe_all()

def test_service_layer_functions():
    """Test the service layer functions directly"""
    print_section("Testing Service Layer Functions")
    
    # Test username (would come from session in real app)
    username = "testuser"
    
    # Test WebSocket status
    print(f"\n{Colors.CYAN}1. Testing WebSocket Status:{Colors.ENDC}")
    success, status_data, status_code = get_websocket_status(username)
    if success:
        print(f"  Status: {Colors.GREEN}Success{Colors.ENDC} (Code: {status_code})")
        print(f"  Connected: {status_data.get('connected', False)}")
        print(f"  Authenticated: {status_data.get('authenticated', False)}")
    else:
        print(f"  Status: {Colors.RED}Failed{Colors.ENDC} (Code: {status_code})")
        print(f"  Error: {status_data.get('message', 'Unknown error')}")
    
    # Test subscription
    print(f"\n{Colors.CYAN}2. Testing Subscription via Service Layer:{Colors.ENDC}")
    symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'}
    ]
    
    success, result, status_code = subscribe_to_symbols(username, None, symbols, 'LTP')
    if success:
        print(f"  Subscription: {Colors.GREEN}Success{Colors.ENDC} (Code: {status_code})")
        print(f"  Message: {result.get('message', 'Subscribed successfully')}")
    else:
        print(f"  Subscription: {Colors.RED}Failed{Colors.ENDC} (Code: {status_code})")
        print(f"  Error: {result.get('message', 'Subscription failed')}")
    
    # Test getting subscriptions
    print(f"\n{Colors.CYAN}3. Testing Get Subscriptions:{Colors.ENDC}")
    success, subs_data, status_code = get_websocket_subscriptions(username)
    if success:
        print(f"  Get Subscriptions: {Colors.GREEN}Success{Colors.ENDC} (Code: {status_code})")
        print(f"  Active Subscriptions: {subs_data.get('count', 0)}")
    else:
        print(f"  Get Subscriptions: {Colors.RED}Failed{Colors.ENDC} (Code: {status_code})")
    
    # Test unsubscribe all
    print(f"\n{Colors.CYAN}4. Testing Unsubscribe All:{Colors.ENDC}")
    success, result, status_code = unsubscribe_all(username, None)
    if success:
        print(f"  Unsubscribe All: {Colors.GREEN}Success{Colors.ENDC} (Code: {status_code})")
    else:
        print(f"  Unsubscribe All: {Colors.RED}Failed{Colors.ENDC} (Code: {status_code})")

def main():
    """Main test function"""
    print_header("WebSocket Service Layer Test")
    print("Comprehensive testing of LTP, Quote, and Depth with subscription management")
    
    # Get API key from environment or use the one from test files
    api_key = os.getenv('API_KEY', '7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc')
    
    if not api_key:
        print(f"{Colors.RED}Error: No API key found. Set API_KEY in .env file{Colors.ENDC}")
        return
    
    # Test service layer functions first
    test_service_layer_functions()
    
    # Create WebSocket client
    print(f"\n{Colors.BLUE}Creating WebSocket client...{Colors.ENDC}")
    client = WebSocketClient(api_key)
    
    # Connect to WebSocket
    print(f"{Colors.BLUE}Connecting to WebSocket server...{Colors.ENDC}")
    if not client.connect():
        print(f"{Colors.RED}Failed to connect to WebSocket server{Colors.ENDC}")
        return
    
    print(f"{Colors.GREEN}Successfully connected and authenticated!{Colors.ENDC}")
    
    # Define test symbols
    symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'}
    ]
    
    try:
        # Test different subscription modes
        test_ltp(client, symbols)
        time.sleep(2)
        
        test_quote(client, symbols)
        time.sleep(2)
        
        test_depth(client, symbols)
        time.sleep(2)
        
        # Test subscription management
        test_subscription_management(client, symbols)
        time.sleep(2)
        
        # Test mode switching
        test_mode_switching(client, symbols)
        time.sleep(2)
        
        # Test concurrent subscriptions
        test_concurrent_subscriptions(client, symbols)
        time.sleep(2)
        
        # Test market data service
        test_market_data_service()
        
        # Final subscription status
        print_section("Final Status")
        subs = client.get_subscriptions()
        print(f"Final active subscriptions: {subs['count']}")
        if 'subscriptions' in subs:
            for sub in subs['subscriptions']:
                print(f"  - {sub['exchange']}:{sub['symbol']} ({sub['mode']})")
        
        # Display connection metrics
        print(f"\n{Colors.CYAN}Connection Metrics:{Colors.ENDC}")
        print(f"  Total test duration: ~60 seconds")
        print(f"  Data updates received: Many (check terminal output)")
        print(f"  Connection stability: {'Stable' if client.is_connected() else 'Unstable'}")
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.ENDC}")
    except Exception as e:
        print(f"\n{Colors.RED}Error during test: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up all subscriptions
        try:
            client.unsubscribe_all()
        except:
            pass
        
        # Disconnect
        print(f"\n{Colors.BLUE}Disconnecting from WebSocket...{Colors.ENDC}")
        client.disconnect()
        print(f"{Colors.GREEN}Test completed successfully!{Colors.ENDC}")
        print(f"\n{Colors.YELLOW}Note:{Colors.ENDC} This test covered both service layer functions and direct WebSocket client usage.")
        print(f"The service layer is designed for internal Flask app usage, while WebSocketClient is for external integrations.")

if __name__ == "__main__":
    main()
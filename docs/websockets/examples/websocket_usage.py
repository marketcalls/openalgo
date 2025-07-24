"""
Example script showing how to use the WebSocket service layer
for different use cases in the OpenAlgo application.
"""

import time
from services.websocket_service import (
    get_websocket_status,
    subscribe_to_symbols,
    unsubscribe_from_symbols,
    get_market_data
)
from services.market_data_service import (
    get_market_data_service,
    get_ltp,
    get_quote,
    subscribe_to_market_updates
)

# Example 1: Basic usage in a Flask route or background task
def monitor_portfolio_positions(username):
    """
    Monitor real-time prices for user's portfolio positions
    """
    # Get user's positions from database (pseudo code)
    positions = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE', 'quantity': 100},
        {'symbol': 'TCS', 'exchange': 'NSE', 'quantity': 50},
        {'symbol': 'INFY', 'exchange': 'NSE', 'quantity': 200}
    ]
    
    # Convert to WebSocket format
    symbols = [{'symbol': pos['symbol'], 'exchange': pos['exchange']} for pos in positions]
    
    # Subscribe to real-time quotes
    success, result, status = subscribe_to_symbols(username, None, symbols, 'Quote')
    
    if success:
        print(f"Successfully subscribed to {len(symbols)} symbols")
        
        # Monitor for 30 seconds
        for i in range(30):
            print(f"\n--- Update {i+1} ---")
            
            # Get latest prices
            for pos in positions:
                ltp_data = get_ltp(pos['symbol'], pos['exchange'])
                if ltp_data:
                    current_value = ltp_data['value'] * pos['quantity']
                    print(f"{pos['symbol']}: ₹{ltp_data['value']:.2f} | Qty: {pos['quantity']} | Value: ₹{current_value:.2f}")
            
            time.sleep(1)
        
        # Unsubscribe when done
        unsubscribe_from_symbols(username, None, symbols, 'Quote')

# Example 2: Using callbacks for real-time updates
def setup_price_alerts(username):
    """
    Set up price alerts using callbacks
    """
    # Define alerts
    alerts = {
        'NSE:RELIANCE': {'above': 2600, 'below': 2400},
        'NSE:TCS': {'above': 3500, 'below': 3300}
    }
    
    # Subscribe to symbols
    symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'}
    ]
    subscribe_to_symbols(username, None, symbols, 'LTP')
    
    # Define alert callback
    def check_alerts(data):
        if data.get('type') != 'market_data':
            return
            
        symbol = data.get('symbol')
        exchange = data.get('exchange')
        symbol_key = f"{exchange}:{symbol}"
        
        market_data = data.get('data', {})
        ltp = market_data.get('ltp')
        
        if symbol_key in alerts and ltp:
            alert_config = alerts[symbol_key]
            
            if ltp > alert_config['above']:
                print(f"🔴 ALERT: {symbol_key} crossed above ₹{alert_config['above']:.2f} - Current: ₹{ltp:.2f}")
            elif ltp < alert_config['below']:
                print(f"🔵 ALERT: {symbol_key} crossed below ₹{alert_config['below']:.2f} - Current: ₹{ltp:.2f}")
    
    # Subscribe to updates
    filter_symbols = set(alerts.keys())
    subscriber_id = subscribe_to_market_updates('ltp', check_alerts, filter_symbols)
    
    # Register user callback to start receiving data
    market_service = get_market_data_service()
    market_service.register_user_callback(username)
    
    print("Price alerts set up. Monitoring...")
    
    # Return subscriber ID for cleanup
    return subscriber_id

# Example 3: Market data aggregation
def calculate_market_metrics():
    """
    Calculate market-wide metrics using cached data
    """
    market_service = get_market_data_service()
    
    # Get data for multiple symbols
    symbols = [
        ('RELIANCE', 'NSE'),
        ('TCS', 'NSE'),
        ('HDFCBANK', 'NSE'),
        ('INFY', 'NSE'),
        ('ICICIBANK', 'NSE')
    ]
    
    total_volume = 0
    price_changes = []
    
    for symbol, exchange in symbols:
        quote = market_service.get_quote(symbol, exchange)
        if quote:
            volume = quote.get('volume', 0)
            total_volume += volume
            
            open_price = quote.get('open', 0)
            ltp = quote.get('ltp', 0)
            
            if open_price > 0:
                change_pct = ((ltp - open_price) / open_price) * 100
                price_changes.append(change_pct)
                print(f"{symbol}: Open: ₹{open_price:.2f}, LTP: ₹{ltp:.2f}, Change: {change_pct:.2f}%")
                
                # Display additional market data from Angel broker feed
                avg_price = quote.get('average_price', 0)
                total_buy_qty = quote.get('total_buy_quantity', 0)
                total_sell_qty = quote.get('total_sell_quantity', 0)
                upper_circuit = quote.get('upper_circuit', 0)
                lower_circuit = quote.get('lower_circuit', 0)
                
                print(f"  Avg Price: ₹{avg_price:.2f}, Buy Qty: {total_buy_qty:,.0f}, Sell Qty: {total_sell_qty:,.0f}")
                print(f"  Circuit: ₹{lower_circuit:.2f} - ₹{upper_circuit:.2f}")
    
    if price_changes:
        avg_change = sum(price_changes) / len(price_changes)
        print(f"\nMarket Summary:")
        print(f"Average Change: {avg_change:.2f}%")
        print(f"Total Volume: {total_volume:,}")

# Example 4: WebSocket connection monitoring
def monitor_websocket_health(username):
    """
    Monitor WebSocket connection health
    """
    print("Monitoring WebSocket connection health...")
    
    for i in range(10):
        success, status_data, _ = get_websocket_status(username)
        
        print(f"\nCheck {i+1}:")
        print(f"Connected: {status_data.get('connected', False)}")
        print(f"Authenticated: {status_data.get('authenticated', False)}")
        print(f"Active Subscriptions: {status_data.get('active_subscriptions', 0)}")
        print(f"Broker: {status_data.get('broker', 'Unknown')}")
        
        if not status_data.get('connected'):
            print("⚠️  Connection lost! Attempting to reconnect...")
            # The service layer handles reconnection automatically
        
        time.sleep(5)

# Example 5: Bulk operations
def bulk_subscribe_unsubscribe(username):
    """
    Demonstrate bulk subscription operations
    """
    # Large list of symbols
    nifty50_symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'},
        {'symbol': 'HDFCBANK', 'exchange': 'NSE'},
        {'symbol': 'INFY', 'exchange': 'NSE'},
        {'symbol': 'HINDUNILVR', 'exchange': 'NSE'},
        # ... add more symbols
    ]
    
    # Subscribe in batches
    batch_size = 10
    for i in range(0, len(nifty50_symbols), batch_size):
        batch = nifty50_symbols[i:i+batch_size]
        success, result, _ = subscribe_to_symbols(username, None, batch, 'LTP')
        print(f"Batch {i//batch_size + 1}: {'Success' if success else 'Failed'}")
        time.sleep(0.5)  # Small delay between batches
    
    # Get all subscriptions
    from services.websocket_service import get_websocket_subscriptions
    success, subs_data, _ = get_websocket_subscriptions(username)
    print(f"\nTotal active subscriptions: {subs_data.get('count', 0)}")
    
    # Unsubscribe all
    from services.websocket_service import unsubscribe_all
    success, result, _ = unsubscribe_all(username, None)
    print(f"Unsubscribe all: {'Success' if success else 'Failed'}")

# Example 6: Integration with order management
def monitor_order_execution(username, order_id):
    """
    Monitor real-time price for order execution
    """
    # Get order details (pseudo code)
    order = {
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'order_type': 'LIMIT',
        'price': 2500,
        'trigger_price': 2495,
        'quantity': 100
    }
    
    # Subscribe to real-time data
    symbols = [{'symbol': order['symbol'], 'exchange': order['exchange']}]
    subscribe_to_symbols(username, None, symbols, 'Quote')
    
    # Monitor for execution
    executed = False
    for i in range(60):  # Monitor for 1 minute
        quote = get_quote(order['symbol'], order['exchange'])
        if quote:
            ltp = quote['ltp']
            print(f"LTP: ₹{ltp:.2f} | Order Price: ₹{order['price']:.2f}")
            
            # Check if order should be executed
            if order['order_type'] == 'LIMIT' and ltp <= order['price']:
                print(f"✅ Order can be executed at ₹{ltp:.2f}")
                executed = True
                break
            elif ltp <= order['trigger_price']:
                print(f"⚡ Trigger price hit at ₹{ltp:.2f}")
        
        time.sleep(1)
    
    # Cleanup
    unsubscribe_from_symbols(username, None, symbols, 'Quote')
    
    return executed

# Example 7: Direct WebSocket Client Usage (for external applications)
def direct_websocket_example():
    """
    Example using WebSocketClient directly for external applications
    """
    from services.websocket_client import WebSocketClient
    
    # API key would come from user's account
    api_key = "your_api_key_here"
    
    # Create and connect client
    client = WebSocketClient(api_key)
    if not client.connect():
        print("Failed to connect to WebSocket server")
        return
    
    print("Connected to WebSocket server successfully!")
    
    # Subscribe to market data
    symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'}
    ]
    
    # Subscribe to LTP for real-time price updates
    result = client.subscribe(symbols, "LTP")
    print(f"LTP Subscription: {result['status']}")
    
    # Monitor for 10 seconds
    for i in range(10):
        for symbol_info in symbols:
            data = client.get_market_data(symbol_info['symbol'], symbol_info['exchange'])
            if data:
                symbol_key = f"{symbol_info['exchange']}:{symbol_info['symbol']}"
                print(f"{symbol_key}: Latest data available")
        time.sleep(1)
    
    # Clean up
    client.unsubscribe_all()
    client.disconnect()
    print("Disconnected from WebSocket server")

if __name__ == "__main__":
    # Example username (would come from session in real app)
    username = "testuser"
    
    print("WebSocket Service Layer Examples")
    print("=" * 50)
    
    # Run examples (uncomment to test)
    # monitor_portfolio_positions(username)
    # setup_price_alerts(username)
    # calculate_market_metrics()
    # monitor_websocket_health(username)
    # bulk_subscribe_unsubscribe(username)
    # monitor_order_execution(username, 'ORD123')
    # direct_websocket_example()
"""
OpenAlgo WebSocket LTP Example - 1800 Symbols Test
Tests LTP data streaming for 1800+ symbols from CSV file including exchange info
"""

import sys
import os
import time
import json
import csv
from datetime import datetime
from collections import defaultdict
import threading


# Add parent directory to path to import openalgo
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


try:
    from openalgo import api
except ImportError:
    print("Error: Could not import openalgo. Make sure you're running from the correct directory.")
    sys.exit(1)


def load_symbols(limit=1800):
    """Load symbols with exchange info from CSV file in current directory"""
    symbols = []
    csv_path = os.path.join(os.path.abspath(os.path.dirname(__file__)), "symbols.csv")
    
    print(f"Loading symbols from: {csv_path}")
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            count = 0
            
            for row in csv_reader:
                if count >= limit:
                    break
                
                exchange = row.get('exchange', '').strip()
                symbol = row.get('symbol', '').strip()
                
                if exchange and symbol:
                    symbols.append({
                        "exchange": exchange,
                        "symbol": symbol
                    })
                    count += 1
        
        print(f"✅ Successfully loaded {len(symbols)} symbols from CSV")
        return symbols
        
    except FileNotFoundError:
        print(f"❌ NSE SYMBOLS.csv not found at {csv_path}")
        print("Using fallback symbols...")
        
        # Fallback to popular NSE symbols only
        fallback_symbols = [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "KOTAKBANK", "SBIN", "BHARTIARTL",
            "ITC", "LT", "ASIANPAINT", "AXISBANK", "MARUTI", "SUNPHARMA", "ULTRACEMCO", "NESTLEIND",
            "BAJFINANCE", "WIPRO", "ONGC", "TATAMOTORS", "TITAN", "POWERGRID", "NTPC", "COALINDIA",
            "HCLTECH", "BAJAJFINSV", "INDUSINDBK", "M&M", "TECHM", "DRREDDY", "ADANIPORTS", "TATACONSUM",
            "GRASIM", "JSWSTEEL", "HINDALCO", "TATASTEEL", "CIPLA", "BRITANNIA", "DIVISLAB", "EICHERMOT",
            "HEROMOTOCO", "BAJAJ-AUTO", "APOLLOHOSP", "SHREECEM", "UPL", "BPCL", "IOC", "ADANIENT"
        ]
        
        return [{"exchange": "NSE", "symbol": sym} for sym in fallback_symbols[:min(limit, len(fallback_symbols))]]


def main():
    print("OpenAlgo WebSocket LTP Example - 1800 Symbols Test")
    print("=" * 60)
    
    # Initialize the API client
    client = api(
        api_key="be51d361903e0898eafeee5824b2997430acb34116c5677240e1b97fc9c4d068",  # Replace with your actual API key
        host="http://127.0.0.1:5000",
        ws_url="ws://127.0.0.1:8765"
    )
    
    # Load 1800 symbols with exchanges from CSV
    test_symbols = load_symbols(1800)
    
    # Statistics with thread safety
    update_count = 0
    symbol_data = {}
    stats_lock = threading.Lock()
    connection_start_time = None
    subscription_start_time = None
    category_stats = defaultdict(int)
    
    def categorize_symbol(symbol):
        """Categorize symbols for better statistics"""
        symbol_upper = symbol.upper()
        if any(bank in symbol_upper for bank in ['BANK', 'AXIS', 'HDFC', 'ICICI', 'KOTAK', 'INDUS', 'FEDERAL']):
            return 'Banking'
        elif any(it in symbol_upper for it in ['TCS', 'INFY', 'WIPRO', 'HCL', 'MIND', 'PERSISTENT']):
            return 'IT'
        elif any(pharma in symbol_upper for pharma in ['PHARMA', 'CIPLA', 'REDDY', 'LUPIN', 'BIOCON']):
            return 'Pharma'
        elif any(auto in symbol_upper for auto in ['MARUTI', 'TATA', 'BAJAJ', 'HERO', 'ASHOK']):
            return 'Auto'
        elif any(energy in symbol_upper for energy in ['OIL', 'GAS', 'ONGC', 'IOC', 'BPCL', 'POWER', 'NTPC']):
            return 'Energy'
        else:
            return 'Others'
    
    def on_data_received(data):
        """Callback function for LTP data - optimized for high volume"""
        nonlocal update_count, symbol_data, connection_start_time, subscription_start_time
        
        try:
            with stats_lock:
                update_count += 1
                
                # Extract symbol and LTP from data
                symbol = None
                ltp = None
                
                if isinstance(data, dict):
                    if 'symbol' in data and 'ltp' in data:
                        symbol = data['symbol']
                        ltp = data['ltp']
                    elif 'symbol' in data and 'data' in data and isinstance(data['data'], dict) and 'ltp' in data['data']:
                        symbol = data['symbol']
                        ltp = data['data']['ltp']
                
                if symbol and ltp:
                    if symbol not in symbol_data:
                        symbol_data[symbol] = {
                            'first_update': datetime.now(),
                            'category': categorize_symbol(symbol)
                        }
                        category_stats[symbol_data[symbol]['category']] += 1
                    
                    symbol_data[symbol].update({
                        'ltp': ltp,
                        'last_update': datetime.now(),
                        'update_count': symbol_data[symbol].get('update_count', 0) + 1
                    })
                    
                    # Print only every 100th update to avoid spam
                    if update_count % 100 == 0:
                        elapsed = (datetime.now() - connection_start_time).total_seconds() if connection_start_time else 0
                        rate = update_count / elapsed if elapsed > 0 else 0
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Update #{update_count}: {symbol} = ₹{ltp} (Rate: {rate:.1f}/sec)")
                
        except Exception as e:
            print(f"❌ Error processing data: {e}")
    
    def print_statistics():
        """Print comprehensive statistics for 1800 symbols"""
        with stats_lock:
            current_time = datetime.now()
            
            print("\n" + "=" * 80)
            print(f"LIVE STATISTICS - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 80)
            print(f"📊 Total Updates Received: {update_count:,}")
            print(f"📈 Symbols Subscribed: {len(test_symbols):,}")
            print(f"✅ Symbols with Data: {len(symbol_data):,}")
            print(f"📡 Success Rate: {(len(symbol_data)/len(test_symbols)*100):.1f}%")
            
            if connection_start_time:
                elapsed = (current_time - connection_start_time).total_seconds()
                rate = update_count / elapsed if elapsed > 0 else 0
                print(f"⏱️  Running Time: {elapsed:.0f}s")
                print(f"⚡ Update Rate: {rate:.1f} updates/sec")
            
            if subscription_start_time:
                sub_elapsed = (current_time - subscription_start_time).total_seconds()
                print(f"📡 Subscription Time: {sub_elapsed:.1f}s")
            
            print("\n📂 Category-wise Active Symbols:")
            for category, count in sorted(category_stats.items()):
                print(f"  {category:12}: {count:>4} symbols")
            
            if symbol_data:
                # Top 10 most active symbols
                top_symbols = sorted(symbol_data.items(), 
                                   key=lambda x: x[1].get('update_count', 0), 
                                   reverse=True)[:10]
                
                print("\n🔥 Top 10 Most Active Symbols:")
                for i, (symbol, data) in enumerate(top_symbols, 1):
                    updates = data.get('update_count', 0)
                    ltp = data.get('ltp', 0)
                    print(f"  {i:2}. {symbol:12} | ₹{ltp:>8} | {updates:>4} updates")
                
                # Symbols without updates
                no_updates = len(test_symbols) - len(symbol_data)
                if no_updates > 0:
                    print(f"\n⚠️  Symbols without updates: {no_updates}")
                    
            print("=" * 80 + "\n")
    
    try:
        print(f"📡 Connecting to WebSocket at {client.ws_url}...")
        connection_start_time = datetime.now()
        
        client.connect()
        print("✅ Connected successfully!")
        
        # Inform about all exchanges subscribed
        exchanges = sorted(set(s['exchange'] for s in test_symbols))
        print(f"📊 Subscribing to {len(test_symbols):,} symbols across exchanges: {', '.join(exchanges)}")
        print("⏳ This may take a few minutes due to batching...")
        
        subscription_start_time = datetime.now()
        client.subscribe_ltp(test_symbols, on_data_received=on_data_received)
        
        subscription_end_time = datetime.now()
        subscription_duration = (subscription_end_time - subscription_start_time).total_seconds()
        print(f"✅ Subscription completed in {subscription_duration:.1f} seconds!")
        
        print("\n🚀 Starting LTP monitoring for 1800 symbols...")
        print("📈 Statistics will be printed every 15 seconds")
        print("💡 Only every 100th update is printed to avoid spam")
        print("🛑 Press Ctrl+C to stop\n")
        
        # Monitor with longer intervals for 1800 symbols
        test_start_time = time.time()
        
        while True:
            time.sleep(15)  # Print stats every 15 seconds for high volume
            print_statistics()
            
            # Check if we're receiving data
            if update_count == 0 and time.time() - test_start_time > 60:
                print("⚠️ No data received for 60 seconds.")
                print("💡 This might be normal if market is closed or during low activity periods.")
                
                # Ask user if they want to continue
                try:
                    response = input("Continue waiting? (y/n): ").lower().strip()
                    if response != 'y':
                        break
                    test_start_time = time.time()  # Reset timer
                except:
                    break
                
    except KeyboardInterrupt:
        print("\n🛑 Stopping test...")
        
    except Exception as e:
        print(f"❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n🧹 Cleaning up...")
        cleanup_start = time.time()
        
        try:
            print("📡 Unsubscribing from all symbols...")
            client.unsubscribe_ltp(test_symbols)
            print("✅ Unsubscribed successfully")
        except Exception as e:
            print(f"❌ Error during unsubscribe: {e}")
            
        try:
            print("🔌 Disconnecting from WebSocket...")
            client.disconnect()
            print("✅ Disconnected successfully")
        except Exception as e:
            print(f"❌ Error during disconnect: {e}")
        
        cleanup_time = time.time() - cleanup_start
        
        # Final comprehensive statistics
        print("\n" + "="*80)
        print("FINAL TEST RESULTS - 1800 SYMBOLS")
        print("="*80)
        
        with stats_lock:
            if connection_start_time:
                total_time = (datetime.now() - connection_start_time).total_seconds()
                print(f"🕐 Total Test Duration: {total_time:.1f} seconds ({total_time/60:.1f} minutes)")
            
            print(f"📊 Total Updates Received: {update_count:,}")
            print(f"📈 Symbols Subscribed: {len(test_symbols):,}")
            print(f"✅ Symbols with Data: {len(symbol_data):,}")
            print(f"📡 Overall Success Rate: {(len(symbol_data)/len(test_symbols)*100):.1f}%")
            
            if update_count > 0 and connection_start_time:
                avg_rate = update_count / total_time
                print(f"⚡ Average Update Rate: {avg_rate:.1f} updates/second")
            
            print(f"🧹 Cleanup Time: {cleanup_time:.1f} seconds")
            
            if category_stats:
                print("\n📂 Final Category Statistics:")
                for category, count in sorted(category_stats.items()):
                    print(f"  {category:12}: {count:>4} symbols with data")
            
            if symbol_data:
                # Most active symbols
                most_active = max(symbol_data.items(), key=lambda x: x[1].get('update_count', 0))
                print(f"\n🏆 Most Active Symbol: {most_active[0]} ({most_active[1].get('update_count', 0)} updates)")
                
                # Average updates per symbol
                total_symbol_updates = sum(data.get('update_count', 0) for data in symbol_data.values())
                avg_updates = total_symbol_updates / len(symbol_data)
                print(f"📊 Average Updates per Symbol: {avg_updates:.1f}")
        
        print("\n🎉 1800 Symbol LTP Test Completed!")
        print("="*80)


if __name__ == "__main__":
    main()

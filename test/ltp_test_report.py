#!/usr/bin/env python3
"""
Enhanced LTP Test - 30 minutes
Streamlined version that runs for exactly 30 minutes with interactive symbol loading
"""

import sys
import os
import time
import csv
from datetime import datetime, timedelta
from collections import defaultdict
import threading

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from openalgo import api
except ImportError:
    print("Error: Could not import openalgo. Make sure you're running from the correct directory.")
    sys.exit(1)

def get_user_input(prompt):
    """Cross-platform user input function"""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n❌ Operation cancelled by user")
        sys.exit(0)

def display_symbol_loading_menu():
    """Display interactive symbol loading menu"""
    print("\n🎯 SYMBOL LOADING OPTIONS")
    print("=" * 50)
    print("1. Load ALL symbols from CSV")
    print("2. Load specific number of symbols")
    print("3. Use fallback symbols (10 symbols)")
    print("-" * 50)

def get_symbol_loading_choice():
    """Get user's symbol loading preference"""
    while True:
        display_symbol_loading_menu()
        choice = get_user_input("Select option (1-3): ")
        
        if choice in ['1', '2', '3']:
            return int(choice)
        else:
            print("❌ Invalid choice. Please select 1, 2, or 3.")
            print()

def get_symbol_count():
    """Get specific number of symbols to load"""
    while True:
        try:
            count_input = get_user_input("Enter number of symbols to load (e.g., 1500, 2500): ")
            count = int(count_input)
            if count <= 0:
                print("❌ Please enter a positive number.")
                continue
            return count
        except ValueError:
            print("❌ Please enter a valid number.")

def load_test_symbols_interactive():
    """Load symbols based on user's interactive choice"""
    choice = get_symbol_loading_choice()
    
    print(f"\n📊 Processing your selection...")
    
    if choice == 1:
        print("🔄 Loading ALL symbols from CSV...")
        return load_symbols_from_csv(limit=None)
    elif choice == 2:
        count = get_symbol_count()
        print(f"🔄 Loading {count} symbols from CSV...")
        return load_symbols_from_csv(limit=count)
    else:  # choice == 3
        print("🔄 Using fallback symbols...")
        return get_fallback_symbols()

def load_symbols_from_csv(limit=None):
    """Load symbols from CSV file with optional limit"""
    symbols = []
    
    # Try multiple possible locations for symbols.csv
    possible_paths = [
        os.path.join(os.path.abspath(os.path.dirname(__file__)), "all_symbols.csv"),
        os.path.join(os.path.abspath(os.path.dirname(__file__)), "symbols.csv"),
        "all_symbols.csv",
        "symbols.csv",
    ]
    
    csv_path = None
    for path in possible_paths:
        if os.path.exists(path):
            csv_path = path
            break
    
    if csv_path:
        print(f"✅ Found symbols file at: {csv_path}")
        try:
            with open(csv_path, 'r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)
                count = 0
                
                for row in csv_reader:
                    if limit and count >= limit:
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
            
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            print("🔄 Falling back to default symbols...")
            return get_fallback_symbols()
    
    # CSV not found
    print("❌ CSV file not found in expected locations:")
    for path in possible_paths:
        print(f"   - {path}")
    print("🔄 Using fallback symbols instead...")
    return get_fallback_symbols()

def get_fallback_symbols():
    """Get hardcoded fallback symbols"""
    fallback_symbols = [
        {"exchange": "NSE", "symbol": "RELIANCE"},
        {"exchange": "NSE", "symbol": "TCS"},
        {"exchange": "NSE", "symbol": "HDFCBANK"},
        {"exchange": "NSE", "symbol": "INFY"},
        {"exchange": "NSE", "symbol": "ICICIBANK"},
        {"exchange": "NSE", "symbol": "KOTAKBANK"},
        {"exchange": "NSE", "symbol": "SBIN"},
        {"exchange": "NSE", "symbol": "BHARTIARTL"},
        {"exchange": "NSE", "symbol": "ITC"},
        {"exchange": "NSE", "symbol": "LT"},
    ]
    
    print(f"✅ Using {len(fallback_symbols)} fallback symbols")
    return fallback_symbols

def display_usage_examples():
    """Display usage examples for different scenarios"""
    print("\n🔧 USAGE EXAMPLES")
    print("=" * 50)
    print("📈 For 1500 symbols test:")
    print("   Select option (1-3): 2")
    print("   Enter number of symbols: 1500")
    print()
    print("📈 For all symbols:")
    print("   Select option (1-3): 1")
    print()
    print("📈 For quick testing:")
    print("   Select option (1-3): 3")
    print("=" * 50)

def save_comprehensive_report(test_symbols, symbol_data, update_count, start_time, end_time):
    """Save comprehensive LTP symbols report"""
    try:
        subscribed_symbols = {s['symbol'] for s in test_symbols}
        symbols_with_data_set = set(symbol_data.keys())
        symbols_without_data = subscribed_symbols - symbols_with_data_set
        
        # Create comprehensive report
        report_file = f"ltp_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("COMPREHENSIVE LTP SYMBOLS REPORT\n")
            f.write("=" * 60 + "\n\n")
            
            # Test summary
            f.write("TEST SUMMARY\n")
            f.write("-" * 20 + "\n")
            f.write(f"Test Duration: {(end_time - start_time).total_seconds():.1f} seconds\n")
            f.write(f"Total Symbols Subscribed: {len(test_symbols)}\n")
            f.write(f"Symbols with Data: {len(symbol_data)}\n")
            f.write(f"Symbols without Data: {len(symbols_without_data)}\n")
            f.write(f"Success Rate: {(len(symbol_data)/len(test_symbols)*100):.1f}%\n")
            f.write(f"Total Updates Received: {update_count}\n\n")
            
            # Exchange breakdown
            f.write("EXCHANGE BREAKDOWN\n")
            f.write("-" * 20 + "\n")
            exchange_stats = defaultdict(lambda: {'total': 0, 'with_data': 0})
            
            for symbol_info in test_symbols:
                exchange = symbol_info['exchange']
                symbol = symbol_info['symbol']
                exchange_stats[exchange]['total'] += 1
                
                if symbol in symbol_data:
                    exchange_stats[exchange]['with_data'] += 1
            
            for exchange, stats in sorted(exchange_stats.items()):
                success_rate = (stats['with_data'] / stats['total'] * 100) if stats['total'] > 0 else 0
                f.write(f"{exchange}: {stats['with_data']}/{stats['total']} ({success_rate:.1f}% success)\n")
            f.write("\n")
            
            # Missing symbols
            if symbols_without_data:
                f.write("SYMBOLS WITHOUT DATA (MISSING)\n")
                f.write("-" * 30 + "\n")
                
                # Group by exchange
                missing_by_exchange = defaultdict(list)
                for symbol_info in test_symbols:
                    if symbol_info['symbol'] in symbols_without_data:
                        missing_by_exchange[symbol_info['exchange']].append(symbol_info['symbol'])
                
                for exchange, symbols in sorted(missing_by_exchange.items()):
                    f.write(f"\n{exchange} Exchange ({len(symbols)} symbols):\n")
                    for i, symbol in enumerate(sorted(symbols), 1):
                        f.write(f"{i:4d}. {symbol}\n")
        
        print(f"📊 Comprehensive report saved to '{report_file}'")
        return report_file
        
    except Exception as e:
        print(f"❌ Error saving comprehensive report: {e}")
        return None

def main():
    print("🧪 Enhanced LTP Test - 30 minutes")
    print("=" * 50)
    
    # Display usage examples
    display_usage_examples()
    
    # Test duration
    TEST_DURATION = 30 * 60  # 30 minutes in seconds
    STATS_INTERVAL = 60  # Print stats every 60 seconds
    
    # Initialize API client
    client = api(
        api_key="be51d361903e0898eafeee5824b2997430acb34116c5677240e1b97fc9c4d068",
        host="http://127.0.0.1:5000",
        ws_url="ws://127.0.0.1:8765"
    )
    
    # Load symbols based on user choice
    test_symbols = load_test_symbols_interactive()
    
    if not test_symbols:
        print("❌ No symbols loaded. Exiting...")
        sys.exit(1)
    
    # Confirm with user before starting
    print(f"\n📋 READY TO START")
    print("-" * 30)
    print(f"🔢 Symbols to monitor: {len(test_symbols)}")
    print(f"⏱️  Test duration: 30 minutes")
    print(f"📊 Stats interval: Every 60 seconds")
    
    # Show exchange breakdown
    exchange_count = defaultdict(int)
    for symbol in test_symbols:
        exchange_count[symbol['exchange']] += 1
    
    print(f"\n📈 Exchange breakdown:")
    for exchange, count in sorted(exchange_count.items()):
        print(f"   {exchange}: {count} symbols")
    
    print("\n" + "="*50)
    proceed = get_user_input("Press Enter to start the test (or Ctrl+C to cancel)...")
    
    # Statistics tracking
    update_count = 0
    symbol_data = {}
    stats_lock = threading.Lock()
    start_time = None
    
    def on_data_received(data):
        """Callback for LTP data"""
        nonlocal update_count, symbol_data
        
        try:
            with stats_lock:
                update_count += 1
                
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
                        symbol_data[symbol] = {'first_update': datetime.now(), 'update_count': 0}
                    
                    symbol_data[symbol].update({
                        'ltp': ltp,
                        'last_update': datetime.now(),
                        'update_count': symbol_data[symbol]['update_count'] + 1
                    })
                
        except Exception as e:
            print(f"❌ Error processing data: {e}")
    
    def print_statistics():
        """Print current statistics"""
        with stats_lock:
            current_time = datetime.now()
            elapsed = (current_time - start_time).total_seconds() if start_time else 0
            remaining = max(0, TEST_DURATION - elapsed)
            
            print(f"\n📊 STATISTICS - {current_time.strftime('%H:%M:%S')}")
            print("-" * 50)
            print(f"⏱️  Time Elapsed: {elapsed/60:.1f} minutes")
            print(f"⏰ Time Remaining: {remaining/60:.1f} minutes")
            print(f"📈 Symbols Subscribed: {len(test_symbols)}")
            print(f"✅ Symbols with Data: {len(symbol_data)}")
            print(f"📊 Total Updates: {update_count}")
            print(f"📡 Success Rate: {(len(symbol_data)/len(test_symbols)*100):.1f}%")
            
            if elapsed > 0:
                rate = update_count / elapsed
                print(f"⚡ Update Rate: {rate:.1f} updates/sec")
            
            # Show missing symbols count
            subscribed_symbols = {s['symbol'] for s in test_symbols}
            symbols_with_data_set = set(symbol_data.keys())
            missing_count = len(subscribed_symbols - symbols_with_data_set)
            
            if missing_count > 0:
                print(f"⚠️  Missing Symbols: {missing_count}")
            
            print("-" * 50)
    
    try:
        print(f"📡 Connecting to WebSocket...")
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=TEST_DURATION)
        
        client.connect()
        print("✅ Connected successfully!")
        
        print(f"📊 Subscribing to {len(test_symbols)} symbols...")
        client.subscribe_ltp(test_symbols, on_data_received=on_data_received)
        print("✅ Subscription completed!")
        
        print(f"\n🚀 Starting 30-minute monitoring session...")
        print(f"🕐 Start Time: {start_time.strftime('%H:%M:%S')}")
        print(f"🕐 End Time: {end_time.strftime('%H:%M:%S')}")
        print("📊 Statistics will be printed every minute")
        print("🛑 Press Ctrl+C to stop early\n")
        
        # Monitor for 30 minutes
        last_stats_time = start_time
        
        while datetime.now() < end_time:
            current_time = datetime.now()
            
            # Print statistics every minute
            if (current_time - last_stats_time).total_seconds() >= STATS_INTERVAL:
                print_statistics()
                last_stats_time = current_time
            
            # Check if test should continue
            if (current_time - start_time).total_seconds() >= TEST_DURATION:
                break
                
            time.sleep(1)  # Check every second
        
        print(f"\n✅ 30-minute test completed!")
        
    except KeyboardInterrupt:
        print("\n🛑 Test interrupted by user")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        print("\n🧹 Cleaning up...")
        try:
            client.unsubscribe_ltp(test_symbols)
            client.disconnect()
            print("✅ Cleanup completed")
        except Exception as e:
            print(f"❌ Cleanup error: {e}")
        
        # Final comprehensive report and statistics
        end_time_actual = datetime.now()
        print("\n" + "="*60)
        print("COMPREHENSIVE LTP SYMBOLS REPORT")
        print("="*60)
        
        with stats_lock:
            # TEST SUMMARY
            print("\nTEST SUMMARY")
            print("-" * 20)
            if start_time:
                total_time = (end_time_actual - start_time).total_seconds()
                print(f"Test Duration: {total_time:.1f} seconds")
            
            print(f"Total Symbols Subscribed: {len(test_symbols)}")
            print(f"Symbols with Data: {len(symbol_data)}")
            
            # Calculate missing symbols
            subscribed_symbols = {s['symbol'] for s in test_symbols}
            symbols_with_data_set = set(symbol_data.keys())
            missing_symbols = subscribed_symbols - symbols_with_data_set
            print(f"Symbols without Data: {len(missing_symbols)}")
            
            if len(test_symbols) > 0:
                success_rate = (len(symbol_data)/len(test_symbols)*100)
                print(f"Success Rate: {success_rate:.1f}%")
            
            print(f"Total Updates Received: {update_count}")
            
            # EXCHANGE BREAKDOWN
            print(f"\nEXCHANGE BREAKDOWN")
            print("-" * 20)
            exchange_stats = defaultdict(lambda: {'total': 0, 'with_data': 0})
            
            for symbol_info in test_symbols:
                exchange = symbol_info['exchange']
                symbol = symbol_info['symbol']
                exchange_stats[exchange]['total'] += 1
                
                if symbol in symbol_data:
                    exchange_stats[exchange]['with_data'] += 1
            
            for exchange, stats in sorted(exchange_stats.items()):
                success_rate = (stats['with_data'] / stats['total'] * 100) if stats['total'] > 0 else 0
                print(f"{exchange}: {stats['with_data']}/{stats['total']} ({success_rate:.1f}% success)")
            
            # Save comprehensive report to file
            if start_time:
                report_file = save_comprehensive_report(test_symbols, symbol_data, update_count, start_time, end_time_actual)
                if report_file:
                    print(f"\n📄 Detailed report saved to: {report_file}")
            
            # Show missing symbols summary
            if missing_symbols:
                print(f"\n⚠️  Missing Symbols: {len(missing_symbols)}")
                if len(missing_symbols) <= 10:
                    print("Missing symbols:", ", ".join(sorted(list(missing_symbols))))
            else:
                print("\n🎉 All symbols received data!")
                
            if symbol_data:
                # Show top 5 most active symbols
                top_symbols = sorted(symbol_data.items(), 
                                   key=lambda x: x[1].get('update_count', 0), 
                                   reverse=True)[:5]
                print("\n🏆 Most Active Symbols:")
                for i, (symbol, data) in enumerate(top_symbols, 1):
                    updates = data.get('update_count', 0)
                    ltp = data.get('ltp', 0)
                    print(f"  {i}. {symbol}: ₹{ltp} ({updates} updates)")
        
        print("="*60)

if __name__ == "__main__":
    main()
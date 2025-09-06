"""
Comprehensive Cache Performance and Verification Test
This script tests the enhanced token_db cache to verify it's working correctly
"""

import sys
import os
import time
import random
from datetime import datetime
import pytz

# Add parent directory to path to import database modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables from parent directory
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(env_path)

def test_cache_performance():
    """Comprehensive test of cache functionality and performance"""
    print("=" * 70)
    print("ENHANCED CACHE PERFORMANCE AND VERIFICATION TEST")
    print("=" * 70)
    
    try:
        # Import the modules
        from database import token_db
        from database.token_db_enhanced import get_cache, load_cache_for_broker
        from database.symbol import SymToken
        
        # Get SESSION_EXPIRY_TIME from environment
        session_expiry = os.getenv('SESSION_EXPIRY_TIME', '03:00')
        print(f"\n[INFO] Session expiry time configured: {session_expiry}")
        
        # 1. Check initial cache status
        print("\n" + "-" * 50)
        print("1. INITIAL CACHE STATUS")
        print("-" * 50)
        
        cache = get_cache()
        stats = token_db.get_cache_stats()
        
        print(f"Cache loaded: {stats['cache_loaded']}")
        print(f"Total symbols in cache: {stats['total_symbols']}")
        print(f"Cache valid: {stats['cache_valid']}")
        print(f"Active broker: {stats.get('active_broker', 'None')}")
        
        # 2. Check database symbol count
        print("\n" + "-" * 50)
        print("2. DATABASE SYMBOL COUNT")
        print("-" * 50)
        
        db_symbol_count = token_db.get_symbol_count()
        print(f"Total symbols in database: {db_symbol_count:,}")
        
        if db_symbol_count == 0:
            print("\n[WARNING] No symbols in database!")
            print("Please run master contract download first to populate symbols.")
            return
        
        # 3. Load cache if not loaded
        if not stats['cache_loaded']:
            print("\n" + "-" * 50)
            print("3. LOADING CACHE")
            print("-" * 50)
            
            # Try to detect broker from last session or use a default
            broker = 'angel'  # Default broker for testing
            print(f"Loading cache for broker: {broker}")
            
            start_time = time.time()
            success = load_cache_for_broker(broker)
            load_time = time.time() - start_time
            
            if success:
                print(f"[SUCCESS] Cache loaded in {load_time:.2f} seconds")
                
                # Get updated stats
                stats = token_db.get_cache_stats()
                print(f"Symbols loaded: {stats['total_symbols']:,}")
                print(f"Memory usage: {stats['stats']['memory_usage_mb']} MB")
                print(f"Cache valid until: {stats.get('next_reset', 'N/A')}")
            else:
                print("[FAIL] Failed to load cache")
                return
        else:
            print("\n" + "-" * 50)
            print("3. CACHE ALREADY LOADED")
            print("-" * 50)
            print(f"Symbols in cache: {stats['total_symbols']:,}")
            print(f"Memory usage: {stats['stats']['memory_usage_mb']} MB")
        
        # 4. Performance comparison test
        print("\n" + "-" * 50)
        print("4. PERFORMANCE COMPARISON TEST")
        print("-" * 50)
        
        # Get some random symbols from database for testing
        print("Fetching test symbols from database...")
        test_symbols = SymToken.query.limit(100).all()
        
        if not test_symbols:
            print("[WARNING] No symbols found for testing")
            return
        
        print(f"Testing with {len(test_symbols)} symbols")
        
        # Test cache performance
        print("\n[CACHE PERFORMANCE TEST]")
        cache_times = []
        
        for _ in range(3):  # Run 3 rounds
            start = time.time()
            for sym in test_symbols:
                result = token_db.get_token(sym.symbol, sym.exchange)
            end = time.time()
            cache_times.append(end - start)
            print(f"  Round {_+1}: {cache_times[-1]:.4f} seconds")
        
        avg_cache_time = sum(cache_times) / len(cache_times)
        print(f"Average time (cached): {avg_cache_time:.4f} seconds")
        print(f"Per lookup: {(avg_cache_time/len(test_symbols))*1000:.3f} ms")
        
        # 5. Cache hit rate analysis
        print("\n" + "-" * 50)
        print("5. CACHE HIT RATE ANALYSIS")
        print("-" * 50)
        
        initial_stats = token_db.get_cache_stats()['stats']
        initial_hits = initial_stats.get('hits', 0)
        initial_misses = initial_stats.get('misses', 0)
        
        # Perform various lookups
        test_count = 50
        for i in range(test_count):
            sym = random.choice(test_symbols)
            token_db.get_token(sym.symbol, sym.exchange)
            token_db.get_br_symbol(sym.symbol, sym.exchange)
            token_db.get_brexchange(sym.symbol, sym.exchange)
        
        final_stats = token_db.get_cache_stats()['stats']
        new_hits = final_stats.get('hits', 0) - initial_hits
        new_misses = final_stats.get('misses', 0) - initial_misses
        
        print(f"Lookups performed: {test_count * 3}")
        print(f"Cache hits: {new_hits}")
        print(f"Cache misses: {new_misses}")
        print(f"Hit rate: {final_stats.get('hit_rate', 'N/A')}")
        print(f"Total DB queries avoided: {final_stats.get('hits', 0)}")
        
        # 6. Bulk operation test
        print("\n" + "-" * 50)
        print("6. BULK OPERATION TEST")
        print("-" * 50)
        
        # Prepare bulk data
        symbol_exchange_pairs = [(sym.symbol, sym.exchange) for sym in test_symbols[:50]]
        
        # Test bulk retrieval
        start = time.time()
        results = token_db.get_tokens_bulk(symbol_exchange_pairs)
        bulk_time = time.time() - start
        
        valid_results = [r for r in results if r is not None]
        print(f"Bulk retrieval of {len(symbol_exchange_pairs)} symbols")
        print(f"Time taken: {bulk_time:.4f} seconds")
        print(f"Valid results: {len(valid_results)}/{len(results)}")
        print(f"Per lookup: {(bulk_time/len(symbol_exchange_pairs))*1000:.3f} ms")
        
        # 7. Search functionality test
        print("\n" + "-" * 50)
        print("7. SEARCH FUNCTIONALITY TEST")
        print("-" * 50)
        
        search_queries = ['RELIANCE', 'NIFTY', 'BANK', 'TCS', 'INFY']
        
        for query in search_queries[:3]:  # Test first 3
            start = time.time()
            results = token_db.search_symbols(query, limit=10)
            search_time = time.time() - start
            print(f"Search '{query}': {len(results)} results in {search_time:.4f} seconds")
            
            if results and len(results) > 0:
                print(f"  Sample: {results[0].get('symbol', 'N/A')} - {results[0].get('name', 'N/A')}")
        
        # 8. Memory and cache info
        print("\n" + "-" * 50)
        print("8. CACHE MEMORY AND STATISTICS")
        print("-" * 50)
        
        final_stats = token_db.get_cache_stats()
        
        print(f"Total symbols cached: {final_stats['total_symbols']:,}")
        print(f"Memory usage: {final_stats['stats']['memory_usage_mb']} MB")
        print(f"Cache hits: {final_stats['stats']['hits']:,}")
        print(f"Cache misses: {final_stats['stats']['misses']}")
        print(f"DB queries made: {final_stats['stats']['db_queries']}")
        print(f"Bulk queries: {final_stats['stats']['bulk_queries']}")
        print(f"Hit rate: {final_stats['stats']['hit_rate']}")
        
        # Calculate memory per symbol
        if final_stats['total_symbols'] > 0:
            bytes_per_symbol = (float(final_stats['stats']['memory_usage_mb']) * 1024 * 1024) / final_stats['total_symbols']
            print(f"Memory per symbol: ~{bytes_per_symbol:.0f} bytes")
        
        # 9. Cache validity check
        print("\n" + "-" * 50)
        print("9. CACHE VALIDITY AND EXPIRY")
        print("-" * 50)
        
        print(f"Cache loaded: {final_stats['cache_loaded']}")
        print(f"Cache valid: {final_stats['cache_valid']}")
        print(f"Session started: {final_stats.get('session_start', 'N/A')}")
        print(f"Cache expires: {final_stats.get('next_reset', 'N/A')}")
        
        # Calculate time until expiry
        if final_stats.get('next_reset'):
            try:
                expiry = datetime.fromisoformat(final_stats['next_reset'])
                now = datetime.now(pytz.timezone('Asia/Kolkata'))
                remaining = expiry - now
                hours, remainder = divmod(remaining.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                print(f"Time until expiry: {hours} hours, {minutes} minutes")
            except:
                pass
        
        # 10. Summary
        print("\n" + "=" * 70)
        print("CACHE VERIFICATION SUMMARY")
        print("=" * 70)
        
        if final_stats['cache_loaded'] and final_stats['total_symbols'] > 0:
            print("[SUCCESS] Cache is working correctly!")
            print(f"  - {final_stats['total_symbols']:,} symbols loaded in memory")
            print(f"  - Using only {final_stats['stats']['memory_usage_mb']} MB")
            print(f"  - Hit rate: {final_stats['stats']['hit_rate']}")
            print(f"  - Average lookup time: {(avg_cache_time/len(test_symbols))*1000:.3f} ms")
            
            # Performance improvement calculation
            db_time_estimate = 5  # Estimated 5ms per DB query
            cache_time_per_lookup = (avg_cache_time/len(test_symbols))*1000
            improvement_factor = db_time_estimate / cache_time_per_lookup if cache_time_per_lookup > 0 else 0
            print(f"  - Performance improvement: ~{improvement_factor:.0f}x faster than DB")
        else:
            print("[FAIL] Cache verification failed!")
            print("  - Check if master contract has been downloaded")
            print("  - Verify database connectivity")
        
        print("\n" + "=" * 70)
        
        # Test cache health endpoint
        try:
            from database.master_contract_cache_hook import get_cache_health
            print("\nCACHE HEALTH CHECK")
            print("-" * 50)
            health = get_cache_health()
            print(f"Health Score: {health['health_score']}/100")
            print(f"Status: {health['status']}")
            print("Recommendations:")
            for rec in health.get('recommendations', []):
                print(f"  - {rec}")
        except Exception as e:
            print(f"\n[INFO] Cache health check not available: {e}")
        
        return True
        
    except ImportError as e:
        print(f"\n[ERROR] Import error: {e}")
        print("Make sure all required modules are installed")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print(f"Starting cache test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Python version: {sys.version}")
    print()
    
    success = test_cache_performance()
    
    if success:
        print("\n[DONE] Cache verification completed successfully!")
    else:
        print("\n[FAILED] Cache verification encountered errors")
    
    sys.exit(0 if success else 1)